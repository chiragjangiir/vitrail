"""Retail Media S3 — compilation des campagnes vers la boucle de diffusion (§2.8).

Une campagne APPROUVÉE dont les dates couvrent aujourd'hui (statut effectif « live »)
et dont la fenêtre horaire quotidienne (`daily_hours`) contient l'instant courant
injecte ses créatifs comme items intercalés dans la boucle du player. Le player ne
change PAS : un créatif = un item média normal → PoP signé automatique (la mesure
du SOV servi = PoP par id_media des créatifs, S4).

Fréquence (plan §3) : SOV = part du temps d'antenne. Pour un cycle « maison » de durée
H et des campagnes de parts s_i (Σ = S, plafonnée à AD_SHARE_CAP), le cycle final dure
T = H / (1 - S) et la campagne i y joue n_i = round(s_i × T / d_i) fois (d_i = durée
moyenne pondérée de ses créatifs), au moins 1 — une campagne live doit passer, même
dans une boucle courte (léger sur-service assumé, jamais de sous-service à zéro).

DÉTERMINISME (wall-clock / LAN sync) : aucune source d'aléa — mêmes entrées (boucle,
campagnes, date) → même liste d'items pour tous les players d'un groupe, et le
wall-clock (calculé APRÈS injection) reste stable au fil des re-syncs de la journée.
La rotation pondérée des créatifs tourne d'un cran par JOUR (ordinal de date), pas
par sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import (
    CmsAdvertiserIndustryCategory,
    CmsCampaign,
    CmsCampaignCreative,
    CmsCampaignTarget,
    CmsSiteExcludedCategory,
)
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization
from app.models.player import CmsPlayer
from app.services.targeting import Target, players_for_targets

# Part d'antenne publicitaire maximale du cycle final (garde-fou : un surbooking
# overridé au-delà réduit toutes les SOV proportionnellement — le contenu maison
# garde toujours au moins 10 % du temps).
AD_SHARE_CAP = 0.90
# Borne dure d'insertions par campagne et par cycle (taille de payload).
MAX_PLAYS_PER_CYCLE = 200
_DEFAULT_CREATIVE_MS = 10_000


@dataclass
class AdSlot:
    """Une insertion de créatif à une position fractionnaire du cycle maison."""

    id_campaign: int
    id_creative: int
    id_media: int
    duration_ms: int
    position: float  # 0..1 — fraction du cycle maison APRÈS laquelle insérer


def in_daily_window(daily_hours: dict | None, now_local: datetime) -> bool:
    """La fenêtre quotidienne {"start": "09:00", "end": "20:00"} contient-elle l'instant ?

    Pas de fenêtre (ou fenêtre incomplète) = diffusion toute la journée. Une fenêtre
    start > end est à cheval sur minuit (ex. 22:00 → 06:00). Comparaison en heure
    LOCALE (même convention que les règles de schedule)."""
    if not daily_hours:
        return True
    start = str(daily_hours.get("start") or "").strip()
    end = str(daily_hours.get("end") or "").strip()
    if not start or not end:
        return True
    hhmm = now_local.strftime("%H:%M")
    if start <= end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end


async def campaign_ad_slots(
    db: AsyncSession,
    id_org: int,
    id_player: int,
    now_local: datetime,
    home_duration_ms: int,
) -> list[AdSlot]:
    """Insertions de créatifs dues à ce player pour un cycle maison de `home_duration_ms`.

    Campagnes retenues : approuvées, dates couvrant aujourd'hui, fenêtre quotidienne
    ouverte, ciblant ce player (cibles canoniques résolues par le noyau targeting).
    Retour trié par position (puis id_campaign — stable), prêt pour `splice_ad_items`.
    """
    if home_duration_ms <= 0:
        return []
    # Player exclu des campagnes (campaigns_optout, migr 0075) → jamais de créatif,
    # même si son site/groupe/org est ciblé (écran caisse, back-office…).
    prow = (await db.execute(
        select(CmsPlayer.campaigns_optout, CmsPlayer.id_site)
        .where(CmsPlayer.id_player == id_player)
    )).one_or_none()
    if prow is None or prow[0]:
        return []
    # Exclusion concurrentielle (migr 0087) : catégories exclues par le SITE du
    # player → toute campagne d'un annonceur de ces catégories est écartée.
    excluded_cats: set[int] = set()
    if prow[1] is not None:
        excluded_cats = set((await db.execute(
            select(CmsSiteExcludedCategory.id_category).where(
                CmsSiteExcludedCategory.id_site == prow[1])
        )).scalars().all())
    # Approbation des créatifs (S5, flag org) : quand active, seuls les créatifs
    # `approved` sont diffusables. Flag OFF = comportement historique inchangé.
    approval_on = bool((await db.execute(
        select(CmsOrganization.campaign_creative_approval)
        .where(CmsOrganization.id_org == id_org)
    )).scalar_one_or_none())
    today = now_local.date()
    camps = (await db.execute(
        select(CmsCampaign).where(
            CmsCampaign.id_org == id_org,
            CmsCampaign.is_deleted == False,  # noqa: E712
            CmsCampaign.status == "approved",
            # S2 audio (migr 0094) : les campagnes AUDIO passent par les paniers §XIX
            # (services/campaign_audio), jamais par la boucle visuelle.
            CmsCampaign.campaign_kind == "visual",
            CmsCampaign.starts_on <= today,
            CmsCampaign.ends_on >= today,
        ).order_by(CmsCampaign.priority.desc(), CmsCampaign.id_campaign)
    )).scalars().all()
    if not camps:
        return []
    adv_cats: dict[int, set[int]] = {}
    if excluded_cats:
        for aid, cid in (await db.execute(
            select(CmsAdvertiserIndustryCategory.id_advertiser,
                   CmsAdvertiserIndustryCategory.id_category)
            .where(CmsAdvertiserIndustryCategory.id_advertiser.in_(
                {c.id_advertiser for c in camps}))
        )).all():
            adv_cats.setdefault(aid, set()).add(cid)

    # Campagnes réellement actives sur CE player, avec leurs créatifs jouables.
    live: list[tuple[CmsCampaign, list[CmsCampaignCreative], dict[int, int]]] = []
    for camp in camps:
        if not in_daily_window(camp.daily_hours, now_local):
            continue
        if excluded_cats and adv_cats.get(camp.id_advertiser, set()) & excluded_cats:
            continue
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        targets = [
            Target(target_type=t.target_type, target_id=t.target_id, tag_expr=t.tag_expr or {})
            for t in trows
        ]
        pids = await players_for_targets(db, id_org, targets)
        if id_player not in pids:
            continue
        creatives_q = select(CmsCampaignCreative).where(
            CmsCampaignCreative.id_campaign == camp.id_campaign,
            CmsCampaignCreative.status == "active",
        )
        if approval_on:
            creatives_q = creatives_q.where(CmsCampaignCreative.approval_status == "approved")
        creatives = (await db.execute(
            creatives_q.order_by(CmsCampaignCreative.sort_order, CmsCampaignCreative.id_creative)
        )).scalars().all()
        if not creatives:
            continue
        native = dict((await db.execute(
            select(CmsMedia.id_media, CmsMedia.duration_ms).where(
                CmsMedia.id_media.in_({c.id_media for c in creatives}),
                CmsMedia.is_deleted == False,  # noqa: E712
                CmsMedia.is_blocked == False,  # noqa: E712
            )
        )).all())
        usable = [c for c in creatives if c.id_media in native]
        if not usable:
            continue
        dur_by_creative = {
            c.id_creative: int(c.duration_ms or native[c.id_media] or _DEFAULT_CREATIVE_MS)
            for c in usable
        }
        live.append((camp, usable, dur_by_creative))

    if not live:
        return []

    total_sov = sum(float(c.sov_percent) for c, _, _ in live) / 100.0
    if total_sov <= 0:
        return []
    scale = min(1.0, AD_SHARE_CAP / total_sov)
    eff_total = total_sov * scale  # ≤ AD_SHARE_CAP
    cycle_ms = home_duration_ms / (1.0 - eff_total)

    slots: list[AdSlot] = []
    day_offset = today.toordinal()
    for camp, creatives, dur_by_creative in live:
        share = float(camp.sov_percent) / 100.0 * scale
        # Rotation pondérée déterministe : liste répétée par weight, décalée d'un cran/jour.
        rotation: list[CmsCampaignCreative] = []
        for c in creatives:
            rotation.extend([c] * max(1, int(c.weight or 1)))
        d_avg = sum(dur_by_creative[c.id_creative] for c in rotation) / len(rotation)
        n = max(1, min(MAX_PLAYS_PER_CYCLE, round(share * cycle_ms / d_avg)))
        # Plafond optionnel de passages/heure (mode slots) — ramené au cycle.
        if camp.max_plays_per_hour:
            per_cycle_cap = max(1, int(camp.max_plays_per_hour * cycle_ms / 3_600_000))
            n = min(n, per_cycle_cap)
        for k in range(n):
            c = rotation[(k + day_offset) % len(rotation)]
            slots.append(AdSlot(
                id_campaign=camp.id_campaign,
                id_creative=c.id_creative,
                id_media=c.id_media,
                duration_ms=dur_by_creative[c.id_creative],
                position=(k + 0.5) / n,
            ))
    slots.sort(key=lambda a: (a.position, a.id_campaign))
    return slots


def splice_ad_items(home_items: list[dict], ad_items: list[tuple[AdSlot, dict]]) -> list[dict]:
    """Intercale les items publicitaires dans la boucle maison, positions fractionnaires.

    `ad_items` = [(slot, item_dict)] trié par position. Chaque pub vise la frontière
    APRÈS l'item maison où le temps cumulé atteint `position × H`.

    ⚠️ RÈGLE ANTI-MARTÈLEMENT (bug NUC 2026-07-12, retour Ed) : **au plus UNE pub par
    frontière** — jamais deux spots dos à dos à l'écran. L'ancien splice enchaînait
    toutes les pubs tombant au même point : avec une boucle maison de PEU d'items
    LONGS (NUC : 6 vidéos de 2-3 min) et une SOV exigeant beaucoup de passages
    (25 % × spot 10 s ≈ 29/cycle), le même créatif passait 4 à 6 fois d'affilée
    (confirmé PoP). Désormais une pub en collision glisse à la frontière libre
    suivante, et l'excédent (plus de pubs que de frontières) est ABANDONNÉ : le
    sous-service qui en découle est mesuré (rapport S4, SOV servi) et alerté
    (§XXII `campaign_underserved`) — un martèlement ne « sert » personne.
    Déterministe (fonction pure des listes) → wall-clock/LAN sync stables.

    Frontières INTERDITES : un item marqué `no_ad_before` (page 2..N d'un document
    multipage déroulé) ne peut pas être précédé d'une pub — un spot ne coupe jamais
    un document en pleine lecture ; la pub glisse à la frontière autorisée suivante.
    """
    if not ad_items:
        return home_items
    durations = [max(int(i.get("duration_ms") or 0), 0) for i in home_items]
    total = sum(durations) or 1
    n_boundaries = len(home_items)

    def _allowed(idx: int) -> bool:
        """Frontière APRÈS home_items[idx] : interdite si l'item suivant est une
        page de continuation (fin de boucle = autorisée, le tour suivant repart p.1)."""
        nxt = idx + 1
        return nxt >= n_boundaries or not home_items[nxt].get("no_ad_before")

    # Frontière naturelle de chaque pub (première frontière où cum ≥ position × H),
    # puis résolution des collisions : glisser à la frontière libre suivante ;
    # au-delà de la dernière frontière → pub abandonnée (pas de dos-à-dos en fin
    # de boucle non plus).
    cums: list[int] = []
    acc = 0
    for d in durations:
        acc += d
        cums.append(acc)
    by_boundary: dict[int, dict] = {}
    next_free = 0
    for slot, item in ad_items:
        target = slot.position * total
        natural = next(
            (idx for idx, c in enumerate(cums) if c >= target), n_boundaries - 1)
        b = max(natural, next_free)
        while b < n_boundaries and not _allowed(b):
            b += 1  # glisse au-delà des pages de continuation d'un document
        if b >= n_boundaries:
            continue  # excédent abandonné (sous-service assumé, cf. docstring)
        by_boundary[b] = item
        next_free = b + 1

    out: list[dict] = []
    for idx, item in enumerate(home_items):
        out.append(item)
        if idx in by_boundary:
            out.append(by_boundary[idx])
    for i, item in enumerate(out):
        item["sort_order"] = i
    return out
