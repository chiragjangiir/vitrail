"""Tests config de repli §17.5 — injection dans player:sync.

Couvre :
  - _resolve_fallback : message vidéo par défaut + audio None sans fallback_audio_id
  - message vidéo custom + video_config remontés tels quels
  - fallback_audio_id résolu en { id_media, media_name, url }
  - player:sync (payload empty ET payload schedule) contient la clé fallback
"""

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.ws as ws
from app.api.v1.endpoints.ws import _resolve_fallback, _resolve_sync_payload
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer


async def _make_org(db: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="FB Org", org_slug=f"fb-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session)


@pytest_asyncio.fixture
async def player(db_session, org) -> CmsPlayer:
    p = CmsPlayer(id_org=org.id_org, player_name="FB Player", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture(autouse=True)
def _stub_signed_url(monkeypatch):
    """URL signée déterministe (pas de MinIO en test)."""
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")


async def _make_audio(db, org) -> CmsMedia:
    m = CmsMedia(
        id_org=org.id_org, media_name="ambient.ogg", media_type="audio", mime_type="audio/ogg",
        storage_key=f"audio/{uuid.uuid4().hex}.ogg", checksum_sha256=uuid.uuid4().hex,
        duration_ms=120000, source="upload", transcode_status="done",
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def test_resolve_fallback_defaults(db_session, player) -> None:
    """Sans fallback_audio_id : message par défaut (server_default), config {}, audio None."""
    fb = await _resolve_fallback(db_session, player)
    assert fb["video_message"] == "No content to display"
    assert fb["video_config"] == {}
    assert fb["audio"] is None


async def test_resolve_fallback_custom_message_and_config(db_session, player) -> None:
    player.fallback_video_message = "Bientôt de retour"
    player.fallback_video_config = {"background_color": "#000", "hide_logo": True}
    await db_session.commit()
    fb = await _resolve_fallback(db_session, player)
    assert fb["video_message"] == "Bientôt de retour"
    assert fb["video_config"] == {"background_color": "#000", "hide_logo": True}


async def test_resolve_fallback_audio_resolved(db_session, player, org) -> None:
    media = await _make_audio(db_session, org)
    player.fallback_audio_id = media.id_media
    await db_session.commit()
    fb = await _resolve_fallback(db_session, player)
    assert fb["audio"] is not None
    assert fb["audio"]["id_media"] == media.id_media
    assert fb["audio"]["media_name"] == "ambient.ogg"
    assert fb["audio"]["url"].startswith("https://minio.test/")


async def test_resolve_fallback_none_player(db_session) -> None:
    fb = await _resolve_fallback(db_session, None)
    assert fb == {"video_message": None, "video_config": {}, "audio": None}


async def test_sync_payload_includes_fallback(db_session, player) -> None:
    """Le payload empty (aucun schedule) porte bien la clé fallback."""
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert "fallback" in payload
    assert payload["fallback"]["video_message"] == "No content to display"
    assert payload["fallback"]["audio"] is None
