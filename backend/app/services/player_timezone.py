"""Alignement du fuseau horaire OS des players sur celui de leur SITE.

Le pilotage offline auto-power et tout le wall-clock local d'un player raisonnent sur
l'horloge OS du device (constaté HW 2026-07-07 : MINIX d'usine en Asia/Shanghai). Le
fuseau de référence est celui du site (`cms_sites.timezone`) : à l'ATTACHEMENT d'un
player au site — ou quand le fuseau du site change — le serveur pousse automatiquement
la commande `set_timezone` aux players dont le fuseau remonté (capabilities.timezone)
diffère. Envoi UNIQUE par événement (pas d'enforcement continu : appliquer un fuseau
RELANCE l'app du player, voire REBOOTE un BrightSign — un opt-in « maintenir aligné »
par site est prévu en phase 2 si le besoin se confirme).

Nuances PAR TYPE de player (un site mélange les OS — tables de correspondance) :
  - linux / rpi / android : tzdata complète → nom IANA du site envoyé tel quel,
    remonté tel quel (alignement exact).
  - windows : ~140 zones larges (tzutil) → on envoie le REPRÉSENTANT CANONIQUE du
    groupe Windows de la zone (ex. site Europe/Monaco → envoi Europe/Berlin, même
    heure) — c'est aussi, à peu près, ce que le player remontera.
  - brightsign : le BOS n'accepte que SES libellés (roSystemTime — IANA et GMT±N
    REFUSÉS, validé HW) → table IANA → libellé BS (Europe/Paris → CET), remonté
    comme tel (l'UI drawer connaît la même équivalence pour le badge).
  - chromeos / chrome_extension : fuseau piloté par la policy Google → jamais envoyé.
Zone du site absente des tables → AUCUN envoi (pas de commande loterie) ; le badge
de mismatch du drawer reste le filet visuel.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timezones import safe_tz_name  # noqa: F401 — ré-exporté (appelants existants)
from app.models.organization import CmsSite
from app.models.player import CmsPlayer

logger = logging.getLogger(__name__)

# ── Windows : zone IANA → représentant canonique de son groupe Windows ─────────
# Groupes = table IANA_TO_WINDOWS_TZ du player (player-windows/src/main.js) ; le
# canonique est CE QUE Chromium remonte après tzutil (CLDR). Une zone déjà canonique
# est envoyée telle quelle (identité) — seuls les membres non-canoniques sont listés.
_WINDOWS_CANONICAL: dict[str, str] = {
    # Romance Standard Time → Europe/Paris
    "Europe/Brussels": "Europe/Paris", "Europe/Madrid": "Europe/Paris",
    "Europe/Copenhagen": "Europe/Paris",
    # W. Europe Standard Time → Europe/Berlin
    "Europe/Amsterdam": "Europe/Berlin", "Europe/Rome": "Europe/Berlin",
    "Europe/Vienna": "Europe/Berlin", "Europe/Zurich": "Europe/Berlin",
    "Europe/Stockholm": "Europe/Berlin", "Europe/Oslo": "Europe/Berlin",
    "Europe/Luxembourg": "Europe/Berlin", "Europe/Monaco": "Europe/Berlin",
    "Europe/Andorra": "Europe/Berlin", "Europe/Malta": "Europe/Berlin",
    "Europe/Gibraltar": "Europe/Berlin", "Europe/Vaduz": "Europe/Berlin",
    "Europe/San_Marino": "Europe/Berlin", "Europe/Vatican": "Europe/Berlin",
    # Central Europe / Central European Standard Time
    "Europe/Prague": "Europe/Budapest", "Europe/Ljubljana": "Europe/Budapest",
    "Europe/Bratislava": "Europe/Budapest", "Europe/Belgrade": "Europe/Budapest",
    "Europe/Tirane": "Europe/Budapest",
    "Europe/Zagreb": "Europe/Warsaw", "Europe/Sarajevo": "Europe/Warsaw",
    "Europe/Skopje": "Europe/Warsaw",
    # GMT Standard Time → Europe/London
    "Europe/Dublin": "Europe/London", "Europe/Lisbon": "Europe/London",
    # GTB / FLE
    "Europe/Athens": "Europe/Bucharest",
    "Europe/Helsinki": "Europe/Kyiv", "Europe/Riga": "Europe/Kyiv",
    "Europe/Vilnius": "Europe/Kyiv",
    # Amériques / divers
    "America/Toronto": "America/New_York", "America/Vancouver": "America/Los_Angeles",
    "Asia/Calcutta": "Asia/Kolkata", "Etc/UTC": "UTC",
}

# Zones que le player Windows sait appliquer (clés de sa table IANA_TO_WINDOWS_TZ,
# APRÈS canonicalisation ci-dessus). Zone hors liste → pas d'envoi à un Windows.
_WINDOWS_KNOWN: frozenset[str] = frozenset({
    "UTC", "Europe/Paris", "Europe/Berlin", "Europe/Warsaw", "Europe/Budapest",
    "Europe/Prague", "Europe/London", "Europe/Athens", "Europe/Bucharest",
    "Europe/Helsinki", "Europe/Kyiv", "Europe/Istanbul", "Europe/Moscow",
    "Africa/Casablanca", "Africa/Cairo", "Africa/Lagos", "Africa/Nairobi",
    "Africa/Johannesburg", "Asia/Dubai", "Asia/Riyadh", "Asia/Jerusalem",
    "Asia/Karachi", "Asia/Kolkata", "Asia/Dhaka", "Asia/Bangkok", "Asia/Singapore",
    "Asia/Kuala_Lumpur", "Asia/Manila", "Asia/Hong_Kong", "Asia/Shanghai",
    "Asia/Taipei", "Asia/Tokyo", "Asia/Seoul", "Asia/Jakarta",
    "Australia/Perth", "Australia/Adelaide", "Australia/Brisbane", "Australia/Sydney",
    "Australia/Melbourne", "Pacific/Auckland", "Pacific/Honolulu",
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "America/Mexico_City",
    "America/Bogota", "America/Lima", "America/Santiago", "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
})

# ── BrightSign : zone IANA → libellé natif BOS (roSystemTime.SetTimeZone) ──────
# Miroir serveur de BS_TZ_EQUIV du drawer (DeviceInfoSection). CET/GMT validés HW ;
# les autres libellés nommés viennent de la doc BrightSign (GMT±N refusés, exclus).
_BS_LABEL: dict[str, str] = {
    "Europe/Paris": "CET", "Europe/Berlin": "CET", "Europe/Brussels": "CET",
    "Europe/Amsterdam": "CET", "Europe/Madrid": "CET", "Europe/Rome": "CET",
    "Europe/Vienna": "CET", "Europe/Zurich": "CET", "Europe/Stockholm": "CET",
    "Europe/Oslo": "CET", "Europe/Copenhagen": "CET", "Europe/Warsaw": "CET",
    "Europe/Prague": "CET", "Europe/Budapest": "CET", "Europe/Monaco": "CET",
    "Europe/Luxembourg": "CET",
    "Europe/Athens": "EET", "Europe/Bucharest": "EET", "Europe/Helsinki": "EET",
    "Europe/Kyiv": "EET", "Europe/Riga": "EET", "Europe/Vilnius": "EET",
    "Europe/Lisbon": "WET",
    "Europe/London": "GMTBST", "Europe/Dublin": "GMTBST",
    "Europe/Moscow": "MSK",
    "America/New_York": "EST", "America/Toronto": "EST",
    "America/Chicago": "CST", "America/Denver": "MST",
    "America/Los_Angeles": "PST", "America/Vancouver": "PST",
    "America/Anchorage": "AKST", "Pacific/Honolulu": "HST",
    "Asia/Tokyo": "JST", "Asia/Kolkata": "IST",
    "Australia/Sydney": "AEST", "Australia/Melbourne": "AEST",
    "Australia/Perth": "AWST", "Australia/Adelaide": "ACST",
    "Pacific/Auckland": "NZST",
    "UTC": "GMT", "Etc/UTC": "GMT",
}

_NOT_CAPABLE = ("chromeos", "chrome_extension")


async def player_tz_name(db: AsyncSession, id_player: int) -> str:
    """Fuseau de RÉFÉRENCE d'un écran pour toute évaluation horaire de son contenu.

    C'est celui de son SITE (`cms_sites.timezone`, migr 0071) — exactement la référence
    qu'on aligne déjà sur l'horloge OS du device (`align_player_timezone`). Un écran à
    New York doit évaluer ses programmes à l'heure de New York, pas à celle du serveur.

    Retombe sur `SIGNFLOW_TZ` quand l'écran n'a pas de site, ou que le site ne déclare
    pas de fuseau : c'est le comportement historique et le bon défaut mono-pays. Le
    retour n'est JAMAIS None — un appelant peut donc distinguer « déjà résolu » de
    « pas encore résolu » sans sentinelle.

    ⚠️ Le retour est aussi garanti UTILISABLE : `cms_sites.timezone` est une chaîne LIBRE,
    jamais validée à l'écriture — une faute de frappe (« Paris ») ferait lever `ZoneInfo`
    chez chaque appelant, donc un 500 sur le chemin de diffusion de tout le parc du site.
    On replie alors sur `SIGNFLOW_TZ` et pas sur UTC : une valeur illisible ne doit pas
    téléporter le site à Greenwich pendant que le serveur est à Paris.
    """
    tz = (await db.execute(
        select(CmsSite.timezone)
        .select_from(CmsPlayer)
        .join(CmsSite, CmsSite.id_site == CmsPlayer.id_site)
        .where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()
    return safe_tz_name(tz)


def target_for(player_os: str | None, site_tz: str) -> str | None:
    """Valeur `timezone` à envoyer à CE type de player pour la zone IANA du site.

    None = ne rien envoyer (OS non pilotable, ou zone hors tables pour cet OS).
    """
    if not player_os or player_os in _NOT_CAPABLE:
        return None
    if player_os == "windows":
        canonical = _WINDOWS_CANONICAL.get(site_tz, site_tz)
        return canonical if canonical in _WINDOWS_KNOWN else None
    if player_os == "brightsign":
        return _BS_LABEL.get(site_tz)
    # linux / linux-x64 / linux-arm64 / rpi / android-* : tzdata complète.
    return site_tz


def is_aligned(player_os: str | None, reported: str | None, site_tz: str | None) -> bool:
    """Le fuseau remonté par le player correspond-il (aux équivalences près) au site ?

    Aligné = remonté == zone du site, OU == ce que ce type de player remonterait après
    application (libellé BS, canonique Windows). Fuseau non remonté (None) → considéré
    NON aligné (on enverra la commande ; un player à jour remonte toujours son fuseau).
    """
    if not site_tz:
        return True  # site sans fuseau = pas de référence → rien à faire
    if not reported:
        return False
    if reported == site_tz:
        return True
    expected = target_for(player_os, site_tz)
    return expected is not None and reported == expected


async def align_player_timezone(db: AsyncSession, player: CmsPlayer,
                                site: CmsSite | None = None) -> bool:
    """Pousse `set_timezone` au player si son fuseau diffère de celui de son site.

    Fire-and-forget (Redis → WS) : un player OFFLINE ne recevra pas la commande
    (pas de file d'attente — il sera réaligné au prochain événement d'attachement,
    ou à la main via le drawer ; le badge de mismatch le signale). Retourne True si
    une commande a été publiée. Ne lève jamais (best-effort : l'attachement/l'update
    du site ne doivent JAMAIS échouer à cause de l'alignement).
    """
    try:
        if site is None:
            if not player.id_site:
                return False
            site = (await db.execute(
                select(CmsSite).where(CmsSite.id_site == player.id_site)
            )).scalar_one_or_none()
        if site is None or not site.timezone:
            return False
        target = target_for(player.player_os, site.timezone)
        if target is None:
            return False
        reported = (player.capabilities or {}).get("timezone")
        if is_aligned(player.player_os, reported, site.timezone):
            return False
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            await r.publish(
                f"signflow:player:{player.id_player}:cmds",
                json.dumps({
                    "type": "player:command",
                    "command": "set_timezone",
                    "params": {"timezone": target},
                }),
            )
        finally:
            await r.aclose()
        logger.info(
            "align_timezone: player %s (%s) %r -> %r (site %s)",
            player.id_player, player.player_os, reported, target, site.timezone,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("align_timezone: échec player %s", player.id_player)
        return False
