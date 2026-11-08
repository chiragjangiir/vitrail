"""
Tests Q5 — kill-switch / quarantaine média.

Couvre : enforcement server-side (média bloqué exclu de _resolve_sync_payload +
présent dans blocked_media), endpoints quarantine/unquarantine/purge, audit log.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.ws as ws
from app.api.v1.endpoints.ws import _build_basket_items, _resolve_sync_payload
from app.core.security import hash_password
from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
from app.models.audit_log import CmsAuditLog
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="QR", org_slug=f"qr-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"qr-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_QR_{uid}", label="QR", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("media", "read"), ("media", "edit"), ("media", "delete")]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


async def _scene(db: AsyncSession, org: CmsOrganization):
    """Player + playlist (2 médias) + schedule always ciblant le player."""
    player = CmsPlayer(id_org=org.id_org, player_name="P", player_os="linux")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL", sync_mode="wall_clock")
    db.add_all([player, pl])
    await db.flush()
    m1 = CmsMedia(id_org=org.id_org, media_name="m1", media_type="video",
                  storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="a",
                  transcode_status="done", duration_ms=5000)
    m2 = CmsMedia(id_org=org.id_org, media_name="m2", media_type="video",
                  storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="b",
                  transcode_status="done", duration_ms=5000)
    db.add_all([m1, m2])
    await db.flush()
    db.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m1.id_media, sort_order=0),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m2.id_media, sort_order=1),
    ])
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist, is_active=True)
    db.add(sched)
    await db.flush()
    db.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player", target_id=player.id_player),
    ])
    await db.commit()
    return player, m1, m2


@pytest.mark.asyncio
async def test_blocked_media_excluded_and_listed(db_session, org, monkeypatch):
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    player, m1, m2 = await _scene(db_session, org)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert {i["media"]["id_media"] for i in payload["items"]} == {m1.id_media, m2.id_media}
    assert payload["blocked_media"] == []

    # Quarantaine de m1 → exclu des items + listé dans blocked_media
    m1.is_blocked = True
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert {i["media"]["id_media"] for i in payload["items"]} == {m2.id_media}
    assert m1.id_media in payload["blocked_media"]


@pytest.mark.asyncio
async def test_blocked_audio_excluded_from_basket(db_session, org, monkeypatch):
    """La quarantaine couvre AUSSI l'audio : un média audio bloqué disparaît des paniers."""
    from datetime import datetime
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    audio = CmsMedia(id_org=org.id_org, media_name="track", media_type="audio",
                     storage_key=f"t/{uuid.uuid4().hex}.ogg", checksum_sha256="c",
                     transcode_status="done", duration_ms=120000)
    db_session.add(audio)
    await db_session.flush()
    basket = CmsAudioBasket(id_org=org.id_org, basket_name="B", basket_type="music")
    db_session.add(basket)
    await db_session.flush()
    db_session.add(CmsAudioBasketItem(id_basket=basket.id_basket, id_media=audio.id_media))
    await db_session.commit()

    now = datetime(2026, 6, 3, 12)
    items = await _build_basket_items(db_session, basket.id_basket, now)
    assert any(i["id_media"] == audio.id_media for i in items)

    audio.is_blocked = True
    await db_session.commit()
    items = await _build_basket_items(db_session, basket.id_basket, now)
    assert items == []


@pytest.mark.asyncio
async def test_quarantine_endpoint_sets_flag_and_audit(client, auth_token, db_session, org):
    player, m1, m2 = await _scene(db_session, org)
    h = {"Authorization": f"Bearer {auth_token}"}

    r = await client.post(f"/api/v1/media/{m1.id_media}/quarantine",
                          json={"reason": "droits image non valides"}, headers=h)
    assert r.status_code == 200
    assert r.json()["is_blocked"] is True

    await db_session.refresh(m1)
    assert m1.is_blocked is True and m1.block_reason == "droits image non valides"
    assert m1.blocked_at is not None

    audit = (await db_session.execute(
        select(CmsAuditLog).where(CmsAuditLog.action == "media_quarantine",
                                  CmsAuditLog.resource_id == str(m1.id_media))
    )).scalar_one_or_none()
    assert audit is not None and audit.detail["reason"] == "droits image non valides"


@pytest.mark.asyncio
async def test_unquarantine_restores(client, auth_token, db_session, org):
    player, m1, m2 = await _scene(db_session, org)
    h = {"Authorization": f"Bearer {auth_token}"}
    await client.post(f"/api/v1/media/{m1.id_media}/quarantine", json={}, headers=h)
    r = await client.post(f"/api/v1/media/{m1.id_media}/unquarantine", headers=h)
    assert r.status_code == 200 and r.json()["is_blocked"] is False
    await db_session.refresh(m1)
    assert m1.is_blocked is False and m1.block_reason is None


@pytest.mark.asyncio
async def test_purge_dispatches_and_audits(client, auth_token, db_session, org):
    player, m1, m2 = await _scene(db_session, org)
    h = {"Authorization": f"Bearer {auth_token}"}
    r = await client.post(f"/api/v1/media/{m1.id_media}/purge", headers=h)
    assert r.status_code == 202 and r.json()["purge_dispatched"] is True
    audit = (await db_session.execute(
        select(CmsAuditLog).where(CmsAuditLog.action == "media_purge",
                                  CmsAuditLog.resource_id == str(m1.id_media))
    )).scalar_one_or_none()
    assert audit is not None
