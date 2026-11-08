"""Le contenu d'un écran s'évalue dans le fuseau de son SITE (P2.2).

Le fuseau par site existe depuis la migration 0071 et sert déjà à aligner l'horloge OS
du device (`player_timezone.align_player_timezone`) et à piloter l'alimentation écran
(`ws._resolve_offline_power`). Ce qui ne s'en servait PAS, c'est l'évaluation du
contenu : `ws._local_now()` produisait un instant en `SIGNFLOW_TZ` pour tout le parc,
donc un écran à New York comparait ses règles horaires à l'heure de Paris.

Défaut SILENCIEUX : rien ne casse, tout diffuse à la mauvaise heure. Ces tests le
mesurent par un A/B — un programme calé sur l'heure DU SITE doit passer, un programme
calé sur l'heure DU SERVEUR ne doit pas.

⚠️ Construction volontairement indépendante de l'heure réelle d'exécution : on choisit
le fuseau du site à partir de l'instant courant pour que l'heure locale du site tombe
sur une heure ronde ÉLOIGNÉE d'au moins 4 h de l'heure serveur (donc jamais la même
fenêtre) et LOIN de minuit (donc jamais un changement de jour au milieu d'une fenêtre).
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _build_sync_payload, _resolve_audio_baskets
from app.core.config import settings
from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import (
    CmsSchedule,
    CmsScheduleBasket,
    CmsScheduleRule,
    CmsScheduleTarget,
)
from app.services.player_timezone import player_tz_name
from app.services.scheduling import local_now

# Heures candidates pour l'heure locale du site : espacées de 6 h et toutes très loin de
# minuit. Pour n'importe quelle heure serveur, au moins une est à >= 4 h de distance
# circulaire — c'est ce qui garantit que les deux fenêtres d'une heure ne se recouvrent
# jamais, quelle que soit l'heure à laquelle la suite tourne.
_CANDIDATE_HOURS = (6, 12, 18)


def _hours_apart(a: int, b: int) -> int:
    d = abs(a - b) % 24
    return min(d, 24 - d)


def _site_tz_for(server_now: datetime) -> tuple[str, datetime]:
    """(nom de fuseau, heure locale du site) tels que l'heure du site soit ronde, loin de
    minuit, et à >= 4 h de l'heure serveur.

    On passe par les zones `Etc/GMT±N` (décalages entiers, sans heure d'été) : le décalage
    obtenu est donc EXACT et stable, ce qu'aucune vraie zone géographique ne garantit un
    jour de changement d'heure.

    ⚠️ Le décalage se calcule depuis UTC, pas depuis le serveur : `SIGNFLOW_TZ` n'est PAS
    UTC ici (Europe/Paris sur le banc, et propre à chaque installation). Ancrer sur
    l'horloge serveur décalait le fuseau du site de l'offset de Paris — premier jet écrit
    ainsi, et il rendait rouges des tests que le correctif avait déjà rendus justes.
    """
    utc_now = datetime.now(UTC).replace(tzinfo=None)
    target = next(h for h in _CANDIDATE_HOURS if _hours_apart(h, server_now.hour) >= 4)
    # Décalage UTC → heure visée, ramené dans [-11, +12] (bornes des zones Etc/GMT).
    shift = ((target - utc_now.hour + 12) % 24) - 12
    site_now = utc_now + timedelta(hours=shift)
    # Etc/GMT a le signe INVERSÉ : Etc/GMT+5 = UTC-5.
    tz = "UTC" if shift == 0 else f"Etc/GMT{'-' if shift > 0 else '+'}{abs(shift)}"
    return tz, site_now


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="TZ Org", org_slug=f"tz-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def clock(db_session: AsyncSession) -> dict:
    """Instant serveur + fuseau du site choisi pour être franchement décalé."""
    server_now = local_now()
    tz, site_now = _site_tz_for(server_now)
    return {"server_now": server_now, "tz": tz, "site_now": site_now}


@pytest_asyncio.fixture
async def player_on_site(db_session: AsyncSession, org, clock) -> CmsPlayer:
    site = CmsSite(id_org=org.id_org, site_name="Boutique NY", timezone=clock["tz"])
    db_session.add(site)
    await db_session.flush()
    p = CmsPlayer(
        id_org=org.id_org, player_name="TZ Player", player_os="linux", id_site=site.id_site
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _playlist_with_item(db: AsyncSession, org) -> CmsPlaylist:
    media = CmsMedia(
        id_org=org.id_org, media_name="clip.mp4", media_type="video", mime_type="video/mp4",
        storage_key=f"video/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        duration_ms=10000, source="upload", transcode_status="done",
    )
    db.add(media)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="TZ Playlist")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(
        id_playlist=pl.id_playlist, id_media=media.id_media, sort_order=1, duration_ms=10000
    ))
    await db.commit()
    await db.refresh(pl)
    return pl


async def _hour_window_schedule(
    db: AsyncSession, org, player: CmsPlayer, pl: CmsPlaylist, ref: datetime, name: str
) -> int:
    """Programme actif exactement pendant l'heure ronde qui contient `ref`."""
    s = CmsSchedule(id_org=org.id_org, schedule_name=name, id_playlist=pl.id_playlist)
    db.add(s)
    await db.flush()
    db.add(CmsScheduleRule(
        id_schedule=s.id_schedule, rule_type="weekly", days_of_week=[ref.weekday()],
        time_start=time(ref.hour, 0), time_end=time(ref.hour, 59, 59),
    ))
    db.add(CmsScheduleTarget(
        id_schedule=s.id_schedule, target_type="player", target_id=player.id_player
    ))
    await db.commit()
    return s.id_schedule


# ── Le résolveur de fuseau ──────────────────────────────────────────────────────

async def test_player_tz_is_its_site_tz(db_session, player_on_site, clock) -> None:
    assert await player_tz_name(db_session, player_on_site.id_player) == clock["tz"]


async def test_unusable_site_tz_falls_back_instead_of_crashing(
    db_session, org, clock
) -> None:
    """`cms_sites.timezone` porte de la donnée ANCIENNE, saisie sans validation : une valeur
    illisible ne doit pas faire lever `ZoneInfo` sur le chemin de diffusion de tout un site.
    Repli sur SIGNFLOW_TZ — et pas sur UTC, qui téléporterait le site à Greenwich."""
    site = CmsSite(id_org=org.id_org, site_name="Site cassé", timezone="Paris")
    db_session.add(site)
    await db_session.flush()
    p = CmsPlayer(
        id_org=org.id_org, player_name="Broken tz", player_os="linux", id_site=site.id_site
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    assert await player_tz_name(db_session, p.id_player) == settings.SIGNFLOW_TZ
    # Et le payload se construit quand même (c'est ça qui compte pour le parc).
    assert await _build_sync_payload(db_session, p.id_player) is not None


def test_site_schema_refuses_an_unknown_timezone() -> None:
    """La garde à la SAISIE : depuis P2.2 ce champ décide de l'heure de diffusion, une
    faute de frappe ne doit plus s'enregistrer en silence."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.site import SiteCreate, SiteUpdate

    assert SiteCreate(site_name="OK", timezone="America/New_York").timezone == "America/New_York"
    assert SiteCreate(site_name="OK", timezone=None).timezone is None
    assert SiteUpdate(timezone="").timezone is None  # champ vidé = pas de fuseau
    for bad in ("Paris", "UTC+2", "Europe/Pariss"):
        with pytest.raises(ValidationError):
            SiteCreate(site_name="KO", timezone=bad)
        with pytest.raises(ValidationError):
            SiteUpdate(timezone=bad)


async def test_player_without_site_falls_back_to_server_tz(db_session, org) -> None:
    """Un écran sans site garde le comportement historique — c'est le défaut mono-pays,
    et c'est ce qui rend le correctif neutre au déploiement pour un parc existant."""
    p = CmsPlayer(id_org=org.id_org, player_name="Orphan", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    assert await player_tz_name(db_session, p.id_player) == settings.SIGNFLOW_TZ


# ── Diffusion : le contenu suit l'heure du site ─────────────────────────────────

async def test_schedule_on_site_local_hour_is_served(
    db_session, org, player_on_site, clock
) -> None:
    """Le cas du client international : à 12 h chez lui, son programme de midi passe.

    ROUGE AVANT : le serveur comparait à SA propre heure → aucune règle ne matchait,
    l'écran recevait un payload vide alors que son programme était censé diffuser.
    """
    pl = await _playlist_with_item(db_session, org)
    sched_id = await _hour_window_schedule(
        db_session, org, player_on_site, pl, clock["site_now"], "Heure du site"
    )
    payload = await _build_sync_payload(db_session, player_on_site.id_player)
    assert payload["id_schedule"] == sched_id
    assert payload["items"]


async def test_schedule_on_server_local_hour_is_not_served(
    db_session, org, player_on_site, clock
) -> None:
    """Le pendant du précédent, et c'est LUI qui mesure le défaut : un programme calé sur
    l'heure du SERVEUR ne doit plus rien diffuser sur un écran d'un autre fuseau.

    ROUGE AVANT : il était servi — l'écran de New York diffusait le créneau de Paris."""
    pl = await _playlist_with_item(db_session, org)
    await _hour_window_schedule(
        db_session, org, player_on_site, pl, clock["server_now"], "Heure du serveur"
    )
    payload = await _build_sync_payload(db_session, player_on_site.id_player)
    assert payload["id_schedule"] is None
    assert payload["items"] == []


async def test_resolved_at_is_the_site_clock(db_session, player_on_site, clock) -> None:
    """`resolved_at` est l'horloge sur laquelle le payload a été construit : elle doit être
    celle du site, sinon le diagnostic ment sur l'instant qui a servi à décider."""
    payload = await _build_sync_payload(db_session, player_on_site.id_player)
    resolved = datetime.fromisoformat(payload["resolved_at"])
    assert abs((resolved - clock["site_now"]).total_seconds()) < 120


# ── Audio : le même instant, sinon les deux chemins divergent ───────────────────

async def test_audio_basket_follows_site_hour(db_session, org, player_on_site, clock) -> None:
    """Les paniers audio ont leur PROPRE calcul d'instant (`_resolve_audio_baskets`) :
    l'oublier ferait diverger le son et l'image sur le même écran."""
    media = CmsMedia(
        id_org=org.id_org, media_name="track.ogg", media_type="audio", mime_type="audio/ogg",
        storage_key=f"audio/{uuid.uuid4().hex}.ogg", checksum_sha256=uuid.uuid4().hex,
        duration_ms=120000, source="upload", transcode_status="done",
    )
    db_session.add(media)
    b = CmsAudioBasket(id_org=org.id_org, basket_name="Ambiance", basket_type="music")
    db_session.add(b)
    await db_session.flush()
    db_session.add(CmsAudioBasketItem(id_basket=b.id_basket, id_media=media.id_media, weight=1))

    s = CmsSchedule(id_org=org.id_org, schedule_name="Audio site", schedule_kind="audio")
    db_session.add(s)
    await db_session.flush()
    db_session.add(CmsScheduleBasket(id_schedule=s.id_schedule, id_basket=b.id_basket, mix_ratio=60))
    ref = clock["site_now"]
    db_session.add(CmsScheduleRule(
        id_schedule=s.id_schedule, rule_type="weekly", days_of_week=[ref.weekday()],
        time_start=time(ref.hour, 0), time_end=time(ref.hour, 59, 59),
    ))
    db_session.add(CmsScheduleTarget(
        id_schedule=s.id_schedule, target_type="player", target_id=player_on_site.id_player
    ))
    await db_session.commit()

    baskets = await _resolve_audio_baskets(db_session, player_on_site.id_player)
    assert [x["id_basket"] for x in baskets] == [b.id_basket]
