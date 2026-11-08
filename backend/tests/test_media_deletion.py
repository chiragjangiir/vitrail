"""Tests de l'analyse d'impact + cascade de suppression d'un média (media_deletion).

Couvre la chaîne content → playlist → programme + événements + paniers audio, et
la classification de diffusion (active / scheduled / expired).
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule
from app.services import media_deletion, scheduling


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="DelOrg", org_slug=f"del-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _media(db, org, name="v.mp4", mtype="video") -> CmsMedia:
    m = CmsMedia(
        id_org=org.id_org, media_name=name, media_type=mtype,
        storage_key=f"{org.id_org}/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        transcode_status="done",
    )
    db.add(m)
    await db.flush()
    return m


async def _playlist(db, org, name="PL") -> CmsPlaylist:
    p = CmsPlaylist(id_org=org.id_org, playlist_name=name)
    db.add(p)
    await db.flush()
    return p


async def _add_item(db, pl, media, order=0):
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media, sort_order=order))
    await db.flush()


async def _schedule(db, org, pl, name="Prog", rule_type="always",
                    valid_from=None, valid_until=None, is_active=True) -> CmsSchedule:
    s = CmsSchedule(
        id_org=org.id_org, schedule_name=name, schedule_kind="content",
        id_playlist=pl.id_playlist, valid_from=valid_from, valid_until=valid_until,
        is_active=is_active,
    )
    db.add(s)
    await db.flush()
    db.add(CmsScheduleRule(id_schedule=s.id_schedule, rule_type=rule_type))
    await db.flush()
    return s


# ── Analyse ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shared_playlist_not_deleted(db_session, org):
    pl = await _playlist(db_session, org)
    m1 = await _media(db_session, org, "a.mp4")
    m2 = await _media(db_session, org, "b.mp4")
    await _add_item(db_session, pl, m1)
    await _add_item(db_session, pl, m2)
    await db_session.commit()

    impact = await media_deletion.analyze(db_session, m1)
    assert len(impact["playlists"]) == 1
    p = impact["playlists"][0]
    assert p["will_be_deleted"] is False
    assert p["remaining_items"] == 1
    assert impact["summary"]["playlists_deleted"] == 0


@pytest.mark.asyncio
async def test_sole_media_cascades_playlist_and_schedule(db_session, org):
    pl = await _playlist(db_session, org, "Solo")
    m = await _media(db_session, org)
    await _add_item(db_session, pl, m)
    sched = await _schedule(db_session, org, pl, "ProgActive", rule_type="always")
    await db_session.commit()

    impact = await media_deletion.analyze(db_session, m)
    assert impact["playlists"][0]["will_be_deleted"] is True
    assert impact["playlists"][0]["broadcast"] == "active"
    assert len(impact["schedules"]) == 1
    assert impact["schedules"][0]["id_schedule"] == sched.id_schedule
    assert impact["schedules"][0]["will_be_deleted"] is True
    assert impact["summary"]["has_live_broadcast"] is True


@pytest.mark.asyncio
async def test_expired_schedule_classified_past(db_session, org):
    today = scheduling.local_now().date()
    pl = await _playlist(db_session, org, "Old")
    m = await _media(db_session, org)
    await _add_item(db_session, pl, m)
    await _schedule(db_session, org, pl, "ProgOld", rule_type="always",
                    valid_until=today - timedelta(days=2))
    await db_session.commit()

    impact = await media_deletion.analyze(db_session, m)
    assert impact["schedules"][0]["broadcast"] == "expired"
    assert impact["summary"]["has_live_broadcast"] is False


@pytest.mark.asyncio
async def test_mono_media_event_surfaced(db_session, org):
    m = await _media(db_session, org)
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Promo", event_type="manual",
        id_media=m.id_media, target_config={}, status="active",
    ))
    await db_session.commit()

    impact = await media_deletion.analyze(db_session, m)
    assert len(impact["events"]) == 1
    assert impact["events"][0]["reason"] == "media"
    assert impact["events"][0]["will_be_cancelled"] is True


@pytest.mark.asyncio
async def test_audio_basket_surfaced(db_session, org):
    m = await _media(db_session, org, "track.ogg", mtype="audio")
    b = CmsAudioBasket(id_org=org.id_org, basket_name="Ambiance", basket_type="music")
    db_session.add(b)
    await db_session.flush()
    db_session.add(CmsAudioBasketItem(id_basket=b.id_basket, id_media=m.id_media))
    await db_session.commit()

    impact = await media_deletion.analyze(db_session, m)
    assert len(impact["baskets"]) == 1
    assert impact["baskets"][0]["basket_name"] == "Ambiance"
    assert impact["baskets"][0]["items_using"] == 1


# ── Cascade ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cascade_delete_applies_all(db_session, org):
    pl = await _playlist(db_session, org, "Solo")
    m = await _media(db_session, org)
    await _add_item(db_session, pl, m)
    sched = await _schedule(db_session, org, pl)
    ev = CmsEvent(
        id_org=org.id_org, event_name="E", event_type="manual",
        id_media=m.id_media, target_config={}, status="inactive",
    )
    db_session.add(ev)
    await db_session.commit()

    await media_deletion.cascade_delete(db_session, m)
    await db_session.commit()

    # Items retirés, playlist + programme soft-deleted, événement annulé.
    items = (await db_session.execute(
        select(CmsPlaylistItem).where(CmsPlaylistItem.id_media == m.id_media)
    )).scalars().all()
    assert items == []
    assert (await db_session.get(CmsPlaylist, pl.id_playlist)).is_deleted is True
    assert (await db_session.get(CmsSchedule, sched.id_schedule)).is_deleted is True
    assert (await db_session.get(CmsEvent, ev.id_event)).status == "cancelled"


@pytest.mark.asyncio
async def test_cascade_keeps_shared_playlist(db_session, org):
    pl = await _playlist(db_session, org, "Shared")
    m1 = await _media(db_session, org, "a.mp4")
    m2 = await _media(db_session, org, "b.mp4")
    await _add_item(db_session, pl, m1)
    await _add_item(db_session, pl, m2)
    await db_session.commit()

    await media_deletion.cascade_delete(db_session, m1)
    await db_session.commit()

    # m1 retiré, m2 conservé, playlist VIVANTE.
    remaining = (await db_session.execute(
        select(CmsPlaylistItem.id_media).where(CmsPlaylistItem.id_playlist == pl.id_playlist)
    )).scalars().all()
    assert remaining == [m2.id_media]
    assert (await db_session.get(CmsPlaylist, pl.id_playlist)).is_deleted is False


@pytest.mark.asyncio
async def test_cascade_removes_media_from_audio_basket(db_session, org):
    b = CmsAudioBasket(id_org=org.id_org, basket_name="Music", basket_type="music")
    db_session.add(b)
    await db_session.flush()
    m = await _media(db_session, org, "track.ogg", "audio")
    db_session.add(CmsAudioBasketItem(id_basket=b.id_basket, id_media=m.id_media))
    await db_session.commit()

    await media_deletion.cascade_delete(db_session, m)
    await db_session.commit()

    # L'item est retiré du panier, mais le panier (vidé) est CONSERVÉ.
    items = (await db_session.execute(
        select(CmsAudioBasketItem).where(CmsAudioBasketItem.id_media == m.id_media)
    )).scalars().all()
    assert items == []
    assert (await db_session.get(CmsAudioBasket, b.id_basket)) is not None
