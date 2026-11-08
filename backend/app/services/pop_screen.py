"""Proof of Play — qualification « écran coupé » à l'ingestion (§XXIV).

Un PoP atteste un AFFICHAGE. Or la lecture et l'alimentation de l'écran suivent deux
fenêtres INDÉPENDANTES : la fenêtre horaire des programmations d'un côté, les heures
d'ouverture du site + marges lead/lag (auto-power) de l'autre. Quand elles diffèrent,
le player joue dans le vide et émettait jusqu'ici des preuves signées d'une diffusion
invisible (constaté en prod le 2026-07-23, cf. migration 0102).

Ce module répond à une seule question, pour chaque preuve d'un lot :
« la sortie vidéo de ce player était-elle programmée ÉTEINTE à cet instant ? »

Parité STRICTE avec `event_worker.apply_site_power` et `ws._resolve_offline_power` —
les trois doivent répondre pareil, sinon on marquerait comme non diffusé un média que
le worker a bel et bien laissé à l'écran :
  - opt-in PAR SITE (`cms_sites.auto_power_enabled`) : sans lui, aucun écran n'est
    piloté, donc on ne sait rien de son état → jamais de marquage ;
  - écran piloté (display_config.type ∈ rs232|ip|cec) OU repli sortie vidéo
    (`output_power_fallback`) : sinon le player n'a aucun moyen de couper l'image ;
  - mode d'alimentation du player (follow_site / custom / always_on / manual) via
    `site_hours.scheduled_off_at`, qui applique exceptions datées, fériés et marges.

⚠️ VISUEL UNIQUEMENT (décision Ed 2026-07-23). Écran éteint ≠ haut-parleurs éteints :
un magasin coupe ses écrans en gardant la musique, et un player audio-only n'a parfois
aucun écran. Marquer l'audio fausserait la facturation Retail Media Audio (spots
réellement entendus). Une preuve dont le média est `media_type = 'audio'` n'est donc
JAMAIS marquée.

Limite assumée : on ne connaît ici que les extinctions PROGRAMMÉES. Un `power_off`
manuel (UI, assistant, commande en masse) n'est pas rattrapé — c'est le rôle du garde
côté player (ne plus émettre quand il sait son écran coupé), prévu en OTA groupé.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media import CmsMedia
from app.models.organization import CmsSite, CmsSiteException, CmsSiteHours
from app.models.player import CmsPlayer
from app.services import site_hours as site_hours_svc

logger = logging.getLogger(__name__)

_PILOTED_TYPES = ("rs232", "ip", "cec")


async def resolve_screen_off(
    db: AsyncSession,
    player: CmsPlayer,
    entries: list,
) -> list[bool]:
    """Pour chaque preuve du lot, True si l'écran était programmé éteint.

    `entries` : objets portant `id_media` et `played_at` (datetime aware).
    Renvoie une liste de même longueur et dans le même ordre. Toute incertitude
    (site inconnu, écran non piloté, fuseau illisible) répond False : on ne retire
    de l'antenne que ce dont on est sûr.
    """
    n = len(entries)
    if n == 0:
        return []

    # 1. Écran piloté ? (repli sortie vidéo compris) — sinon on ne sait rien de son état.
    dc = player.display_config or {}
    if dc.get("type") not in _PILOTED_TYPES and not dc.get("output_power_fallback"):
        return [False] * n

    # 2. Auto-power activé sur le site du player ? (opt-in par site, cf. worker)
    if not player.id_site:
        return [False] * n
    site = (await db.execute(
        select(CmsSite).where(CmsSite.id_site == player.id_site)
    )).scalar_one_or_none()
    if site is None or not site.auto_power_enabled:
        return [False] * n

    try:
        tz = ZoneInfo(site.timezone or settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "pop_screen: fuseau illisible pour le site %s (%r) — aucun marquage",
            site.id_site, site.timezone,
        )
        return [False] * n

    # Instants locaux du site (naïfs), un par preuve — l'heure d'ouverture est une
    # heure LOCALE, jamais UTC. Un lot peut couvrir plusieurs jours (flush d'un
    # backlog offline), d'où le calcul entrée par entrée.
    locals_naive = [
        e.played_at.astimezone(tz).replace(tzinfo=None) for e in entries
    ]

    # 3. Horaires hebdomadaires + exceptions datées couvrant la plage du lot.
    hours = (await db.execute(
        select(CmsSiteHours).where(CmsSiteHours.id_site == site.id_site)
    )).scalars().all()
    weekly = {
        h.weekday: site_hours_svc.DayHours(
            is_closed=h.is_closed, open_time=h.open_time, close_time=h.close_time
        )
        for h in hours
    }

    d_min = min(locals_naive).date() - timedelta(days=1)
    d_max = max(locals_naive).date() + timedelta(days=1)
    exc_rows = (await db.execute(
        select(CmsSiteException).where(
            CmsSiteException.id_site == site.id_site,
            CmsSiteException.date_to >= d_min,
            CmsSiteException.date_from <= d_max,
        )
    )).scalars().all()
    exceptions = [
        site_hours_svc.Exception_(
            date_from=e.date_from, date_to=e.date_to, kind=e.kind,
            open_time=e.open_time, close_time=e.close_time,
        )
        for e in exc_rows
    ]

    # 4. Médias AUDIO du lot : jamais marqués (les haut-parleurs ne s'éteignent pas
    #    avec l'écran). Un id_media inconnu (média supprimé depuis) est traité comme
    #    visuel : c'est le cas majoritaire et le marquage reste conservateur.
    media_ids = {e.id_media for e in entries if e.id_media is not None}
    audio_ids: set[int] = set()
    if media_ids:
        rows = (await db.execute(
            select(CmsMedia.id_media).where(
                CmsMedia.id_media.in_(media_ids),
                CmsMedia.media_type == "audio",
            )
        )).scalars().all()
        audio_ids = set(rows)

    power_cfg = dc.get("power_schedule")
    lead = site.power_lead_min or 0
    lag = site.power_lag_min or 0

    flags: list[bool] = []
    for entry, now_local in zip(entries, locals_naive):
        if entry.id_media is not None and entry.id_media in audio_ids:
            flags.append(False)
            continue
        flags.append(site_hours_svc.scheduled_off_at(
            now_local, weekly, exceptions, power_cfg,
            lead_min=lead, lag_min=lag,
            respect_holidays=site.respect_holidays,
            region=site.holiday_region or "",
        ))
    return flags
