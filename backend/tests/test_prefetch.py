"""Tests du service prefetch (look-ahead) — `upcoming_media`.

- ensemble de médias == expected_media (cohérence inventaire ↔ prefetch).
- play_at = now si le schedule est actif maintenant.
- play_at = date future si le schedule ne joue que plus tard (priorisation).
- contenu hors horizon exclu du datage (reste à now par défaut via un autre schedule).
"""

import uuid
from datetime import datetime, time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.media import CmsMedia
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.services.prefetch import upcoming_media

# 2026-06-01 = LUNDI, 2026-06-03 = MERCREDI.
MON = datetime(2026, 6, 1, 14, 0)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PF", org_slug=f"pf-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


async def _video(db, org, name):
    m = CmsMedia(id_org=org.id_org, media_name=name, media_type="video",
                 mime_type="video/mp4", storage_key=f"k/{uuid.uuid4().hex}",
                 checksum_sha256=uuid.uuid4().hex)
    db.add(m)
    await db.flush()
    return m


async def _scene(db, org, media, rule):
    """Player + playlist (media) + schedule (rule) ciblant le player."""
    player = CmsPlayer(id_org=org.id_org, player_name="pf", player_os="linux")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db.add_all([player, pl])
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                           sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db.add(sched)
    await db.flush()
    db.add(CmsScheduleRule(id_schedule=sched.id_schedule, **rule))
    db.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                             target_id=player.id_player))
    await db.commit()
    return player, sched


@pytest.mark.asyncio
async def test_upcoming_active_now_is_now(db_session, org):
    media = await _video(db_session, org, "live")
    player, _ = await _scene(db_session, org, media, {"rule_type": "always"})
    res = await upcoming_media(db_session, player.id_player, MON)
    assert res == {media.id_media: MON}


@pytest.mark.asyncio
async def test_upcoming_future_weekly_play_at(db_session, org):
    media = await _video(db_session, org, "wed")
    player, _ = await _scene(db_session, org, media,
                             {"rule_type": "weekly", "days_of_week": [2],
                              "time_start": time(9), "time_end": time(12)})
    res = await upcoming_media(db_session, player.id_player, MON)
    # lundi 14h → prochaine diffusion mercredi 3 juin 09:00
    assert res == {media.id_media: datetime(2026, 6, 3, 9, 0)}


@pytest.mark.asyncio
async def test_upcoming_set_matches_expected(db_session, org):
    from app.services.player_inventory import expected_media
    media = await _video(db_session, org, "x")
    player, _ = await _scene(db_session, org, media, {"rule_type": "always"})
    exp = {m["id_media"] for m in await expected_media(db_session, player.id_player)}
    up = set((await upcoming_media(db_session, player.id_player, MON)).keys())
    assert up == exp


@pytest.mark.asyncio
async def test_upcoming_empty_for_unprogrammed(db_session, org):
    player = CmsPlayer(id_org=org.id_org, player_name="lonely", player_os="linux")
    db_session.add(player)
    await db_session.commit()
    assert await upcoming_media(db_session, player.id_player, MON) == {}


@pytest.mark.asyncio
async def test_sync_payload_includes_prefetch(db_session, org):
    """Le payload player:sync porte une liste `prefetch` (cache_key/url + play_at/priority)."""
    from app.api.v1.endpoints.ws import _resolve_sync_payload
    media = await _video(db_session, org, "pf-clip")
    player, _ = await _scene(db_session, org, media, {"rule_type": "always"})
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert "prefetch" in payload
    pf = {p["id_media"]: p for p in payload["prefetch"]}
    assert media.id_media in pf
    entry = pf[media.id_media]
    assert entry["media_type"] == "video"
    assert entry["cache_key"] == media.storage_key   # pas de rendition → parent
    assert "play_at" in entry and "priority" in entry
