"""Retail Media S2 — inventaire & part de voix (docs/PLAN_RETAIL_MEDIA.md §3).

Inventaire v1 = temps de boucle par player : chaque campagne APPROUVÉE réserve
`sov_percent` % du temps d'antenne des players qu'elle cible, sur sa période.
Occupation d'un player = Σ SOV des campagnes approuvées qui se CHEVAUCHENT en
dates (les brouillons/pausées/terminées ne réservent rien ; le raffinement par
fenêtre horaire quotidienne = v2). Politique actée (Ed 2026-07-09) : warning à
80 %, BLOCAGE à 100 % au publish — contournable par `overbook_override`
(org-admin, décision explicite).

Inventaire v2 (migr 0082, demandes Ed 2026-07-11) :
- **plafond d'occupation par player** (`campaign_max_occupancy_pct`, héritage
  player > site > 100) : les seuils deviennent RELATIFS au plafond (warning
  ≥ 80 % du plafond, blocage au-delà du plafond) — « écran de caisse max 20 % » ;
- **tarif SOV par écran** (`campaign_sov_daily_rate` = € / 1 % SOV / jour,
  héritage player > site > défaut org) → `estimate_campaign_price` = PRIX
  INDICATIF (devis annonceur) ; le prix contractuel reste le champ manuel ;
- **`occupancy_breakdown`** : les campagnes qui occupent déjà les cibles —
  le reviewer §21 voit d'où vient l'occupation, pas juste le total.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import (
    CmsAdvertiserIndustryCategory,
    CmsCampaign,
    CmsCampaignTarget,
    CmsSiteExcludedCategory,
)
from app.models.organization import CmsOrganization, CmsSite
from app.models.player import CmsPlayer
from app.services.targeting import Target, players_for_targets

OCCUPANCY_WARN_PCT = 80.0
OCCUPANCY_BLOCK_PCT = 100.0
# Le warning se déclenche à 80 % du plafond effectif (plafond 100 → warning 80 = v1).
WARN_RATIO = OCCUPANCY_WARN_PCT / OCCUPANCY_BLOCK_PCT


async def player_caps_and_rates(
    db: AsyncSession, id_org: int, pids: set[int]
) -> dict[int, dict]:
    """{id_player: {cap, rate, player_name}} — plafond d'occupation et tarif SOV
    EFFECTIFS (héritage player > site > org[tarif]/100[plafond])."""
    if not pids:
        return {}
    org_rate = (await db.execute(
        select(CmsOrganization.campaign_sov_daily_rate).where(
            CmsOrganization.id_org == id_org)
    )).scalar_one_or_none()
    players = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_player.in_(pids))
    )).scalars().all()
    site_ids = {p.id_site for p in players if p.id_site is not None}
    sites = {
        s.id_site: s
        for s in (await db.execute(
            select(CmsSite).where(CmsSite.id_site.in_(site_ids))
        )).scalars().all()
    } if site_ids else {}
    out: dict[int, dict] = {}
    for p in players:
        site = sites.get(p.id_site) if p.id_site is not None else None
        cap = p.campaign_max_occupancy_pct
        if cap is None and site is not None:
            cap = site.campaign_max_occupancy_pct
        rate = p.campaign_sov_daily_rate
        if rate is None and site is not None:
            rate = site.campaign_sov_daily_rate
        if rate is None:
            rate = org_rate
        out[p.id_player] = {
            "cap": float(cap) if cap is not None else OCCUPANCY_BLOCK_PCT,
            "rate": float(rate) if rate is not None else None,
            "player_name": p.player_name,
        }
    return out


async def advertiser_excluded_sites(
    db: AsyncSession, id_advertiser: int | None
) -> set[int]:
    """Sites qui excluent AU MOINS UNE des catégories d'industrie de l'annonceur
    (exclusion concurrentielle, migr 0087 ; multi-catégories migr 0088 — une agence
    de pub porte plusieurs industries). Vide si pas d'annonceur / pas de catégorie."""
    if id_advertiser is None:
        return set()
    cats = set((await db.execute(
        select(CmsAdvertiserIndustryCategory.id_category).where(
            CmsAdvertiserIndustryCategory.id_advertiser == id_advertiser)
    )).scalars().all())
    if not cats:
        return set()
    return set((await db.execute(
        select(CmsSiteExcludedCategory.id_site).where(
            CmsSiteExcludedCategory.id_category.in_(cats))
    )).scalars().all())


async def campaign_eligible_players(
    db: AsyncSession, pids: set[int], id_advertiser: int | None = None
) -> set[int]:
    """Retire les players EXCLUS des campagnes : opt-out player (`campaigns_optout`,
    migr 0075 — écran caisse, back-office…) + exclusion concurrentielle par SITE
    (migr 0087 — le site exclut la catégorie d'industrie de l'annonceur). Appliqué à
    toute résolution de cible campagne : diffusion, occupation, projection,
    inventaire, devis — un player exclu n'est pas de l'inventaire de CET annonceur."""
    if not pids:
        return pids
    rows = (await db.execute(
        select(CmsPlayer.id_player, CmsPlayer.id_site).where(
            CmsPlayer.id_player.in_(pids),
            CmsPlayer.campaigns_optout == False,  # noqa: E712
        )
    )).all()
    excluded_sites = await advertiser_excluded_sites(db, id_advertiser)
    return {pid for pid, sid in rows if sid is None or sid not in excluded_sites}


def _to_targets(rows) -> list[Target]:
    return [
        Target(target_type=r.target_type, target_id=r.target_id, tag_expr=r.tag_expr or {})
        for r in rows
    ]


async def occupancy_by_player(
    db: AsyncSession,
    id_org: int,
    starts_on: date,
    ends_on: date,
    *,
    exclude_id_campaign: int | None = None,
) -> dict[int, float]:
    """{id_player: Σ sov_percent} des campagnes APPROUVÉES chevauchant [starts_on, ends_on].

    Les cibles de chaque campagne sont résolues en players via le noyau targeting
    (player/group/site/tags/org) — même résolution que la diffusion.
    """
    q = select(CmsCampaign).where(
        CmsCampaign.id_org == id_org,
        CmsCampaign.is_deleted == False,  # noqa: E712
        CmsCampaign.status == "approved",
        CmsCampaign.campaign_kind == "visual",  # l'audio a son propre inventaire (spots/h)
        CmsCampaign.starts_on <= ends_on,
        CmsCampaign.ends_on >= starts_on,
    )
    if exclude_id_campaign is not None:
        q = q.where(CmsCampaign.id_campaign != exclude_id_campaign)
    campaigns = (await db.execute(q)).scalars().all()

    occ: dict[int, float] = {}
    for camp in campaigns:
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        pids = await campaign_eligible_players(
            db, await players_for_targets(db, id_org, _to_targets(trows)),
            camp.id_advertiser)
        for pid in pids:
            occ[pid] = occ.get(pid, 0.0) + float(camp.sov_percent)
    return occ


async def occupancy_by_day(
    db: AsyncSession,
    id_org: int,
    date_from: date,
    date_to: date,
) -> dict[str, float]:
    """{date ISO: max sur les players de Σ sov_percent} pour chaque jour de la fenêtre.

    Vue « calendrier » (S6) : le pire player du jour donne la charge du jour — mêmes
    seuils que l'occupancy-check (ambre ≥ 80, rouge > 100). Une seule résolution de
    cibles par campagne pour toute la fenêtre (les cibles ne dépendent pas du jour).
    """
    from datetime import timedelta

    campaigns = (await db.execute(
        select(CmsCampaign).where(
            CmsCampaign.id_org == id_org,
            CmsCampaign.is_deleted == False,  # noqa: E712
            CmsCampaign.status == "approved",
            CmsCampaign.campaign_kind == "visual",  # l'audio a son propre inventaire
            CmsCampaign.starts_on <= date_to,
            CmsCampaign.ends_on >= date_from,
        )
    )).scalars().all()

    resolved: list[tuple[CmsCampaign, set[int]]] = []
    for camp in campaigns:
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        pids = await campaign_eligible_players(
            db, await players_for_targets(db, id_org, _to_targets(trows)),
            camp.id_advertiser)
        if pids:
            resolved.append((camp, pids))

    out: dict[str, float] = {}
    day = date_from
    while day <= date_to:
        per_player: dict[int, float] = {}
        for camp, pids in resolved:
            if camp.starts_on <= day <= camp.ends_on:
                sov = float(camp.sov_percent)
                for pid in pids:
                    per_player[pid] = per_player.get(pid, 0.0) + sov
        out[day.isoformat()] = round(max(per_player.values(), default=0.0), 2)
        day += timedelta(days=1)
    return out


async def site_campaign_stats(
    db: AsyncSession,
    id_org: int,
    date_from: date,
    date_to: date,
) -> dict[int, dict]:
    """{id_site: {player_count, eligible_count, days: [{date, avg_pct, max_pct}]}}.

    Tooltip des sites (retour Ed #4) : nb de players rattachés, nb éligibles
    campagnes (opt-out déduits) + occupation SOV par jour sur la fenêtre — moyenne
    et pire player parmi les ÉLIGIBLES du site (un éligible sans campagne = 0).
    Une seule résolution de cibles par campagne pour toute la fenêtre (comme
    occupancy_by_day)."""
    from datetime import timedelta

    players = (await db.execute(
        select(CmsPlayer.id_player, CmsPlayer.id_site, CmsPlayer.campaigns_optout)
        .where(CmsPlayer.id_org == id_org, CmsPlayer.id_site.is_not(None))
    )).all()
    if not players:
        return {}
    eligible_by_site: dict[int, list[int]] = {}
    counts: dict[int, dict] = {}
    for pid, sid, optout in players:
        c = counts.setdefault(sid, {"player_count": 0, "eligible_count": 0})
        c["player_count"] += 1
        if not optout:
            c["eligible_count"] += 1
            eligible_by_site.setdefault(sid, []).append(pid)

    campaigns = (await db.execute(
        select(CmsCampaign).where(
            CmsCampaign.id_org == id_org,
            CmsCampaign.is_deleted == False,  # noqa: E712
            CmsCampaign.status == "approved",
            CmsCampaign.campaign_kind == "visual",  # l'audio a son propre inventaire
            CmsCampaign.starts_on <= date_to,
            CmsCampaign.ends_on >= date_from,
        )
    )).scalars().all()
    resolved: list[tuple[CmsCampaign, set[int]]] = []
    for camp in campaigns:
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        pids = await campaign_eligible_players(
            db, await players_for_targets(db, id_org, _to_targets(trows)),
            camp.id_advertiser)
        if pids:
            resolved.append((camp, pids))

    out: dict[int, dict] = {
        sid: {**c, "days": []} for sid, c in counts.items()
    }
    day = date_from
    while day <= date_to:
        per_player: dict[int, float] = {}
        for camp, pids in resolved:
            if camp.starts_on <= day <= camp.ends_on:
                sov = float(camp.sov_percent)
                for pid in pids:
                    per_player[pid] = per_player.get(pid, 0.0) + sov
        for sid, entry in out.items():
            pids = eligible_by_site.get(sid, [])
            vals = [per_player.get(pid, 0.0) for pid in pids]
            entry["days"].append({
                "date": day.isoformat(),
                "avg_pct": round(sum(vals) / len(vals), 1) if vals else 0.0,
                "max_pct": round(max(vals), 1) if vals else 0.0,
            })
        day += timedelta(days=1)
    return out


async def check_campaign_occupancy(
    db: AsyncSession,
    id_org: int,
    *,
    starts_on: date,
    ends_on: date,
    sov_percent: float,
    targets: list[Target],
    exclude_id_campaign: int | None = None,
    id_advertiser: int | None = None,
) -> dict:
    """Projette l'occupation si la campagne candidate est approuvée.

    → {blocked, warning, max_projected_pct, players: [{id_player, current_pct,
    projected_pct, cap_pct} triés du pire au meilleur]}. v2 : les seuils sont
    relatifs au PLAFOND effectif de chaque player (héritage player > site > 100) —
    `blocked` = au moins un player dépasserait SON plafond ; `warning` = au moins
    un ≥ 80 % de son plafond.
    """
    pids = await players_for_targets(db, id_org, targets) if targets else set()
    pids = await campaign_eligible_players(db, pids, id_advertiser)
    if not pids:
        return {"blocked": False, "warning": False, "max_projected_pct": 0.0, "players": []}
    existing = await occupancy_by_player(
        db, id_org, starts_on, ends_on, exclude_id_campaign=exclude_id_campaign
    )
    caps = await player_caps_and_rates(db, id_org, pids)
    blocked = warning = False
    rows = []
    for pid in pids:
        current = round(existing.get(pid, 0.0), 2)
        projected = round(current + float(sov_percent), 2)
        cap = caps.get(pid, {}).get("cap", OCCUPANCY_BLOCK_PCT)
        blocked = blocked or projected > cap
        warning = warning or projected >= cap * WARN_RATIO
        rows.append({
            "id_player": pid,
            "current_pct": current,
            "projected_pct": projected,
            "cap_pct": cap,
        })
    # Tri du pire au meilleur RELATIVEMENT au plafond (90 % d'un plafond 20 % est
    # pire que 50 % d'un plafond 100 %).
    rows.sort(key=lambda r: -(r["projected_pct"] / max(r["cap_pct"], 1.0)))
    max_proj = max((r["projected_pct"] for r in rows), default=0.0)
    return {
        "blocked": blocked,
        "warning": warning,
        "max_projected_pct": max_proj,
        "players": rows[:50],
    }


async def occupancy_breakdown(
    db: AsyncSession,
    id_org: int,
    *,
    starts_on: date,
    ends_on: date,
    pids: set[int],
    exclude_id_campaign: int | None = None,
) -> list[dict]:
    """Campagnes APPROUVÉES qui occupent DÉJÀ au moins un des players ciblés sur la
    période — le reviewer voit d'où vient l'occupation (retour Ed 2026-07-11 :
    « 45 % pour 25 % demandés, comment le valideur le sait ? »)."""
    if not pids:
        return []
    q = select(CmsCampaign).where(
        CmsCampaign.id_org == id_org,
        CmsCampaign.is_deleted == False,  # noqa: E712
        CmsCampaign.status == "approved",
        CmsCampaign.campaign_kind == "visual",  # l'audio a son propre inventaire (spots/h)
        CmsCampaign.starts_on <= ends_on,
        CmsCampaign.ends_on >= starts_on,
    )
    if exclude_id_campaign is not None:
        q = q.where(CmsCampaign.id_campaign != exclude_id_campaign)
    out = []
    for camp in (await db.execute(q)).scalars().all():
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        cpids = await campaign_eligible_players(
            db, await players_for_targets(db, id_org, _to_targets(trows)),
            camp.id_advertiser)
        overlap = len(cpids & pids)
        if overlap:
            out.append({
                "id_campaign": camp.id_campaign,
                "campaign_name": camp.campaign_name,
                "sov_percent": float(camp.sov_percent),
                "starts_on": camp.starts_on,
                "ends_on": camp.ends_on,
                "shared_players": overlap,
            })
    out.sort(key=lambda r: -r["sov_percent"])
    return out


async def estimate_campaign_price(
    db: AsyncSession,
    id_org: int,
    *,
    targets: list[Target],
    sov_percent: float,
    starts_on: date,
    ends_on: date,
    id_advertiser: int | None = None,
) -> dict | None:
    """PRIX INDICATIF (devis) = Σ players ciblés (tarif effectif € / 1 % SOV / jour
    × SOV × nb jours). Héritage tarif : player > site > défaut org. → None si AUCUN
    tarif n'est configuré nulle part (la feature est opt-in) ; sinon
    {estimated_price, priced_players, unpriced_players, days}. Le prix CONTRACTUEL
    reste le champ manuel de la campagne (décision Ed 2026-07-11)."""
    pids = await players_for_targets(db, id_org, targets) if targets else set()
    pids = await campaign_eligible_players(db, pids, id_advertiser)
    if not pids:
        return None
    rates = await player_caps_and_rates(db, id_org, pids)
    days = (ends_on - starts_on).days + 1
    if days <= 0:
        return None
    total = 0.0
    priced = unpriced = 0
    for pid in pids:
        rate = rates.get(pid, {}).get("rate")
        if rate is None:
            unpriced += 1
            continue
        priced += 1
        total += rate * float(sov_percent) * days
    if priced == 0:
        return None
    return {
        "estimated_price": round(total, 2),
        "priced_players": priced,
        "unpriced_players": unpriced,
        "days": days,
    }


# ── Retail Media AUDIO S2 (migr 0094) — inventaire en SPOTS/HEURE ────────────────────
# Unité de vente = spots/heure (décision Ed 16/07). Plafond par écran (héritage
# player > site > org, défaut 12/h) ; l'inventaire audio ne compte que les players à
# VOCATION AUDIO (player_role audio|mixed — approximation STABLE du « panier musical
# actif », qui est dynamique ; la diffusion, elle, gate au sync sur la présence réelle
# d'un panier music). Mêmes politiques que le visuel : warning 80 % du plafond,
# blocage au-delà (409 + overbook_override), exclusion concurrentielle, opt-out.

DEFAULT_AUDIO_SPOTS_CAP = 12


async def audio_eligible_players(
    db: AsyncSession, pids: set[int], id_advertiser: int | None = None
) -> set[int]:
    """Sous-ensemble AUDIO de l'éligibilité campagnes : gardes communes
    (`campaign_eligible_players`) + player_role audio|mixed."""
    pids = await campaign_eligible_players(db, pids, id_advertiser)
    if not pids:
        return pids
    return set((await db.execute(
        select(CmsPlayer.id_player).where(
            CmsPlayer.id_player.in_(pids),
            CmsPlayer.player_role.in_(("audio", "mixed")),
        )
    )).scalars().all())


async def audio_caps_and_rates(
    db: AsyncSession, id_org: int, pids: set[int]
) -> dict[int, dict]:
    """{id_player: {cap, rate, player_name}} — plafond spots/h et tarif audio EFFECTIFS
    (cap : player > site > org[12] ; tarif €/spot/h/jour : player > site > org)."""
    if not pids:
        return {}
    org_row = (await db.execute(
        select(
            CmsOrganization.campaign_audio_spots_cap,
            CmsOrganization.campaign_audio_spot_daily_rate,
        ).where(CmsOrganization.id_org == id_org)
    )).first()
    org_cap = org_row.campaign_audio_spots_cap if org_row else DEFAULT_AUDIO_SPOTS_CAP
    org_rate = org_row.campaign_audio_spot_daily_rate if org_row else None
    players = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_player.in_(pids))
    )).scalars().all()
    site_ids = {p.id_site for p in players if p.id_site is not None}
    sites = {
        s.id_site: s
        for s in (await db.execute(
            select(CmsSite).where(CmsSite.id_site.in_(site_ids))
        )).scalars().all()
    } if site_ids else {}
    out: dict[int, dict] = {}
    for p in players:
        site = sites.get(p.id_site) if p.id_site is not None else None
        cap = p.campaign_audio_spots_cap
        if cap is None and site is not None:
            cap = site.campaign_audio_spots_cap
        if cap is None:
            cap = org_cap if org_cap is not None else DEFAULT_AUDIO_SPOTS_CAP
        rate = p.campaign_audio_spot_daily_rate
        if rate is None and site is not None:
            rate = site.campaign_audio_spot_daily_rate
        if rate is None:
            rate = org_rate
        out[p.id_player] = {
            "cap": int(cap),
            "rate": float(rate) if rate is not None else None,
            "player_name": p.player_name,
        }
    return out


async def audio_spots_by_player(
    db: AsyncSession,
    id_org: int,
    starts_on: date,
    ends_on: date,
    *,
    exclude_id_campaign: int | None = None,
) -> dict[int, int]:
    """{id_player: Σ spots_per_hour} des campagnes AUDIO approuvées chevauchant la période."""
    q = select(CmsCampaign).where(
        CmsCampaign.id_org == id_org,
        CmsCampaign.is_deleted == False,  # noqa: E712
        CmsCampaign.status == "approved",
        CmsCampaign.campaign_kind == "audio",
        CmsCampaign.starts_on <= ends_on,
        CmsCampaign.ends_on >= starts_on,
    )
    if exclude_id_campaign is not None:
        q = q.where(CmsCampaign.id_campaign != exclude_id_campaign)
    occ: dict[int, int] = {}
    for camp in (await db.execute(q)).scalars().all():
        if not camp.spots_per_hour:
            continue
        trows = (await db.execute(
            select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
        )).scalars().all()
        if not trows:
            continue
        pids = await audio_eligible_players(
            db, await players_for_targets(db, id_org, _to_targets(trows)),
            camp.id_advertiser)
        for pid in pids:
            occ[pid] = occ.get(pid, 0) + int(camp.spots_per_hour)
    return occ


async def check_audio_occupancy(
    db: AsyncSession,
    id_org: int,
    *,
    starts_on: date,
    ends_on: date,
    spots_per_hour: int,
    targets: list[Target],
    exclude_id_campaign: int | None = None,
    id_advertiser: int | None = None,
) -> dict:
    """Projette l'inventaire audio si la campagne candidate est approuvée.

    Même contrat de sortie que `check_campaign_occupancy` (les pct sont RELATIFS au
    plafond spots/h de chaque player : 100 = plafond atteint) + champs spots par ligne
    (`current_spots`/`projected_spots`/`cap_spots`) + **`achievable_spots_per_hour`**
    (= min sur les players du plafond restant — l'équivalent audio du « SOV
    réalisable » : en mode horloge-minute, la cadence ne dépend pas du volume de
    pistes, seul le plafond restant borne la vente)."""
    pids = await players_for_targets(db, id_org, targets) if targets else set()
    pids = await audio_eligible_players(db, pids, id_advertiser)
    if not pids:
        return {
            "blocked": False, "warning": False, "max_projected_pct": 0.0,
            "players": [], "achievable_spots_per_hour": None,
        }
    existing = await audio_spots_by_player(
        db, id_org, starts_on, ends_on, exclude_id_campaign=exclude_id_campaign
    )
    caps = await audio_caps_and_rates(db, id_org, pids)
    blocked = warning = False
    rows = []
    achievable: int | None = None
    for pid in pids:
        current = existing.get(pid, 0)
        projected = current + int(spots_per_hour)
        cap = caps.get(pid, {}).get("cap", DEFAULT_AUDIO_SPOTS_CAP)
        blocked = blocked or projected > cap
        warning = warning or projected >= cap * WARN_RATIO
        remaining = max(0, cap - current)
        achievable = remaining if achievable is None else min(achievable, remaining)
        rows.append({
            "id_player": pid,
            "current_pct": round(current / cap * 100.0, 2) if cap else 100.0,
            "projected_pct": round(projected / cap * 100.0, 2) if cap else 100.0,
            "cap_pct": 100.0,
            "current_spots": current,
            "projected_spots": projected,
            "cap_spots": cap,
        })
    rows.sort(key=lambda r: -r["projected_pct"])
    max_proj = max((r["projected_pct"] for r in rows), default=0.0)
    return {
        "blocked": blocked,
        "warning": warning,
        "max_projected_pct": max_proj,
        "players": rows[:50],
        "achievable_spots_per_hour": achievable,
    }


async def estimate_audio_price(
    db: AsyncSession,
    id_org: int,
    *,
    targets: list[Target],
    spots_per_hour: int,
    starts_on: date,
    ends_on: date,
    id_advertiser: int | None = None,
) -> dict | None:
    """PRIX INDICATIF audio (devis) = Σ players ciblés (tarif effectif €/spot/h/jour ×
    spots_per_hour × nb jours). Miroir exact d'`estimate_campaign_price` — le prix
    CONTRACTUEL reste le champ manuel de la campagne (décision Ed 16/07)."""
    pids = await players_for_targets(db, id_org, targets) if targets else set()
    pids = await audio_eligible_players(db, pids, id_advertiser)
    if not pids:
        return None
    rates = await audio_caps_and_rates(db, id_org, pids)
    days = (ends_on - starts_on).days + 1
    if days <= 0:
        return None
    total = 0.0
    priced = unpriced = 0
    for pid in pids:
        rate = rates.get(pid, {}).get("rate")
        if rate is None:
            unpriced += 1
            continue
        priced += 1
        total += rate * int(spots_per_hour) * days
    if priced == 0:
        return None
    return {
        "estimated_price": round(total, 2),
        "priced_players": priced,
        "unpriced_players": unpriced,
        "days": days,
    }
