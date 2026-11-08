"""Tests look-ahead Phase 3 — prévision de readiness (ETA de diffusion).

- forecast_readiness (PUR) : débit illimité, sans fenêtre, avec fenêtres (dont overnight),
  flag on_time, contenu injoignable dans l'horizon.
- player_readiness (DB) : médias à venir non cachés → items datés + résumé.
"""

import uuid
from datetime import datetime, time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.services.readiness import DownloadItem, forecast_readiness, player_readiness

MON = datetime(2026, 6, 1, 20, 0)   # lundi 20:00


# ── Estimateur pur ───────────────────────────────────────────────────────────────

def test_forecast_unlimited_is_now():
    items = [DownloadItem("a", 1_000_000, None)]
    out = forecast_readiness(items, 0, None, MON)
    assert out[0].ready_at == MON and out[0].network_bound and out[0].on_time


def test_forecast_no_window_serial_accumulation():
    # 100 o/s, deux items de 100 o → fin a +1s puis +2s (download serie).
    items = [DownloadItem("a", 100, None), DownloadItem("b", 100, None)]
    out = forecast_readiness(items, 100, None, MON)
    assert out[0].ready_at == datetime(2026, 6, 1, 20, 0, 1)
    assert out[1].ready_at == datetime(2026, 6, 1, 20, 0, 2)


def test_forecast_window_waits_for_open():
    # 10 o/s, 100 o = 10s ; fenetre 22:00-23:00 ; on est a 20:00 → pret a 22:00:10.
    items = [DownloadItem("a", 100, None)]
    out = forecast_readiness(items, 10, [{"start": "22:00", "end": "23:00"}], MON)
    assert out[0].ready_at == datetime(2026, 6, 1, 22, 0, 10)


def test_forecast_overnight_window():
    # fenetre 23:00→01:00 (overnight) ; on est lundi 23:30 (dans la fenetre) ; 10 o/s, 100 o.
    items = [DownloadItem("a", 100, None)]
    out = forecast_readiness(items, 10, [{"start": "23:00", "end": "01:00"}],
                             datetime(2026, 6, 1, 23, 30))
    assert out[0].ready_at == datetime(2026, 6, 1, 23, 30, 10)


def test_forecast_on_time_flag():
    # pret a +10s ; diffuse a +5s → en retard ; diffuse a +20s → a temps.
    late = forecast_readiness([DownloadItem("a", 100, datetime(2026, 6, 1, 20, 0, 5))], 10, None, MON)
    assert not late[0].on_time
    ok = forecast_readiness([DownloadItem("a", 100, datetime(2026, 6, 1, 20, 0, 20))], 10, None, MON)
    assert ok[0].on_time


def test_forecast_unreachable_in_horizon():
    # Fenetre minuscule (1 min/jour) + contenu enorme → injoignable dans l'horizon.
    items = [DownloadItem("a", 10**12, None)]
    out = forecast_readiness(items, 1, [{"start": "03:00", "end": "03:01"}], MON)
    assert out[0].ready_at is None and not out[0].on_time


# ── Orchestrateur DB ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RD", org_slug=f"rd-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest.mark.asyncio
async def test_player_readiness_missing_media(db_session, org):
    media = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                     mime_type="video/mp4", storage_key=f"k/{uuid.uuid4().hex}",
                     checksum_sha256=uuid.uuid4().hex, file_size_bytes=1_000_000)
    player = CmsPlayer(id_org=org.id_org, player_name="rd", player_os="linux",
                       display_config={"download_bandwidth_kbps": 8000},  # 1 Mo/s
                       capabilities={"store": {"cached_ids": []}})
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P")
    db_session.add_all([media, player, pl])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"))
    db_session.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                                     target_id=player.id_player))
    await db_session.commit()

    res = await player_readiness(db_session, player.id_player)
    assert res["reported"] is True
    assert res["summary"]["missing"] == 1
    assert res["summary"]["missing_bytes"] == 1_000_000
    it = res["items"][0]
    assert it["id_media"] == media.id_media and it["ready_at"] is not None
    assert it["network_bound"] is False


@pytest.mark.asyncio
async def test_player_readiness_uses_measured_throughput(db_session, org):
    """Sans plafond manuel mais avec un débit MESURÉ remonté → ETA estimée (pas network-bound)."""
    media = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                     mime_type="video/mp4", storage_key=f"k/{uuid.uuid4().hex}",
                     checksum_sha256=uuid.uuid4().hex, file_size_bytes=1_000_000)
    player = CmsPlayer(id_org=org.id_org, player_name="rd", player_os="linux",
                       display_config={},  # pas de plafond manuel
                       capabilities={"store": {"cached_ids": [], "throughput_kbps": 8000}})
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P")
    db_session.add_all([media, player, pl])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"))
    db_session.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                                     target_id=player.id_player))
    await db_session.commit()

    res = await player_readiness(db_session, player.id_player)
    assert res["throughput_source"] == "measured" and res["measured_kbps"] == 8000
    assert res["summary"]["network_bound"] is False
    assert res["items"][0]["ready_at"] is not None


@pytest.mark.asyncio
async def test_player_readiness_cached_excluded(db_session, org):
    media = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                     mime_type="video/mp4", storage_key=f"k/{uuid.uuid4().hex}",
                     checksum_sha256=uuid.uuid4().hex, file_size_bytes=500)
    player = CmsPlayer(id_org=org.id_org, player_name="rd", player_os="linux",
                       capabilities={"store": {"cached_ids": []}})
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P")
    db_session.add_all([media, player, pl])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"))
    db_session.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                                     target_id=player.id_player))
    await db_session.commit()

    # Le média est caché → exclu de la prévision (déjà prêt).
    player.capabilities = {"store": {"cached_ids": [media.id_media]}}
    await db_session.commit()
    res = await player_readiness(db_session, player.id_player)
    assert res["summary"]["missing"] == 0 and res["items"] == []
