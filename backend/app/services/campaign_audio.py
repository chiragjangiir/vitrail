"""Retail Media AUDIO S2 (§2.8 × §XIX) — compilation des spots annonceurs vers les paniers.

Une campagne `campaign_kind='audio'` vend des SPOTS/HEURE (`spots_per_hour`). La diffusion
réutilise le mécanisme jingle/message des paniers audio : le serveur compile UN panier
synthétique (`id_basket = AD_BASKET_ID`, type `jingle`, mode `minutes`) ajouté au payload
`audio_baskets` du player — **zéro modification player** :

- `trigger_value = ceil(60 / total_spots_vendus)` minutes → l'horloge minute du player
  (`_startJingleClock`) déclenche un spot par frontière. Anti-martèlement PAR CONSTRUCTION :
  au plus un spot par tick, espacement ≥ trigger_value minutes (≥ 5 min au plafond 12/h).
  Un total qui ne divise pas 60 (ex. 9/h → tick 7 min ≈ 8,6/h) = léger sous-service,
  partagé au prorata et MESURÉ (rapport + alerte campaign_underserved).
- Répartition multi-campagnes : le runtime overlay du player tire un item en ALÉATOIRE
  PONDÉRÉ (`_playMessage._pickWeighted`) → poids d'item = spots_per_hour × weight_créatif
  = parts proportionnelles en espérance. (Round-robin strict déterministe = évolution v2,
  exigerait un curseur séquentiel player-side sur les overlays.)
- Ducking : défauts message (enabled, target 20 %).

Inventaire : un player ne reçoit le panier que s'il a un PANIER MUSICAL ACTIF dans son
payload (gate posé au point de greffe ws.py — « pas de musique = pas d'emplacement »),
en plus des gardes communes (opt-out, exclusion concurrentielle, fenêtre quotidienne).
"""

from __future__ import annotations

import math
from datetime import datetime
from functools import partial

import anyio
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
from app.services.campaign_delivery import in_daily_window
from app.services.media import get_signed_url
from app.services.targeting import Target, players_for_targets

# id de panier SYNTHÉTIQUE (négatif = jamais en collision avec cms_audio_baskets ; le
# runtime player le traite comme un panier normal, y compris dans le Store Control Panel).
AD_BASKET_ID = -100
AD_BASKET_NAME = "Advertisers"  # affiché sur le device (player = anglais)

_DUCKING = {"enabled": True, "target_pct": 20, "fade_in_ms": 400, "fade_out_ms": 800}


async def audio_spot_basket(
    db: AsyncSession, id_org: int, id_player: int, now_local: datetime
) -> dict | None:
    """Panier synthétique des spots annonceurs pour CE player, ou None si aucun.

    Miroir des gardes de `campaign_delivery.campaign_ad_slots` (opt-out inline, exclusion
    concurrentielle par site, fenêtre quotidienne, approbation S5, ciblage canonique).
    """
    prow = (await db.execute(
        select(CmsPlayer.campaigns_optout, CmsPlayer.id_site)
        .where(CmsPlayer.id_player == id_player, CmsPlayer.id_org == id_org)
    )).first()
    if prow is None or prow.campaigns_optout:
        return None
    id_site = prow.id_site

    # Catégories d'industrie exclues par le site du player (migr 0087/0088).
    excluded_cats: set[int] = set()
    if id_site is not None:
        excluded_cats = set((await db.execute(
            select(CmsSiteExcludedCategory.id_category)
            .where(CmsSiteExcludedCategory.id_site == id_site)
        )).scalars().all())

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
            CmsCampaign.campaign_kind == "audio",
            CmsCampaign.starts_on <= today,
            CmsCampaign.ends_on >= today,
        ).order_by(CmsCampaign.priority.desc(), CmsCampaign.id_campaign)
    )).scalars().all()
    if not camps:
        return None

    # (campagne, [(créatif, média)]) retenus pour CE player
    entries: list[tuple[CmsCampaign, list[tuple[CmsCampaignCreative, CmsMedia]]]] = []
    for camp in camps:
        if not camp.spots_per_hour or camp.spots_per_hour <= 0:
            continue
        if not in_daily_window(camp.daily_hours, now_local):
            continue
        if excluded_cats:
            adv_cats = set((await db.execute(
                select(CmsAdvertiserIndustryCategory.id_category).where(
                    CmsAdvertiserIndustryCategory.id_advertiser == camp.id_advertiser
                )
            )).scalars().all())
            if adv_cats & excluded_cats:
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
        creatives_q = select(CmsCampaignCreative, CmsMedia).join(
            CmsMedia, CmsMedia.id_media == CmsCampaignCreative.id_media
        ).where(
            CmsCampaignCreative.id_campaign == camp.id_campaign,
            CmsCampaignCreative.status == "active",
            CmsMedia.is_deleted == False,  # noqa: E712
            CmsMedia.is_blocked == False,  # noqa: E712
            CmsMedia.media_type == "audio",
        ).order_by(CmsCampaignCreative.sort_order, CmsCampaignCreative.id_creative)
        if approval_on:
            creatives_q = creatives_q.where(CmsCampaignCreative.approval_status == "approved")
        crows = (await db.execute(creatives_q)).all()
        if not crows:
            continue
        entries.append((camp, [(c, m) for c, m in crows]))

    if not entries:
        return None

    total_spots = sum(camp.spots_per_hour for camp, _ in entries)
    trigger = max(1, math.ceil(60 / total_spots))

    items: list[dict] = []
    for camp, creatives in entries:
        # Poids TOTAL de la campagne = spots/h vendus, réparti entre ses créatifs au
        # prorata de leur weight (le runtime tire en aléatoire pondéré → parts en
        # espérance = spots_per_hour / total_spots).
        wsum = sum(max(1, c.weight or 1) for c, _ in creatives)
        for creative, media in creatives:
            try:
                url = await anyio.to_thread.run_sync(partial(get_signed_url, media.storage_key, 86400))
            except Exception:  # noqa: BLE001 — stockage indispo : item sans URL = cache only
                url = None
            weight = max(1, round(camp.spots_per_hour * max(1, creative.weight or 1) / wsum))
            items.append({
                "id_media": media.id_media,
                "media_name": media.media_name,
                "url": url,
                "duration_ms": media.duration_ms,
                "weight": weight,
                "checksum_sha256": media.checksum_sha256,
                "cache_key": media.storage_key,
                "cache_checksum": media.checksum_sha256,
                "mime_type": media.mime_type,
                "media_type": "audio",
                # Marqueur campagne (diag/évolutions — ignoré par le runtime player)
                "campaign": {"id_campaign": camp.id_campaign, "id_creative": creative.id_creative},
            })

    if not items:
        return None

    return {
        "id_basket": AD_BASKET_ID,
        "basket_name": AD_BASKET_NAME,
        "basket_type": "jingle",       # famille déclencheur : hors budget de mix, horloge minute
        "mix_ratio": 0,
        "min_ratio": 0,
        "max_ratio": 100,
        "ducking_config": dict(_DUCKING),
        "trigger_mode": "minutes",
        "trigger_value": trigger,
        "shuffle": False,
        "items": items,
    }
