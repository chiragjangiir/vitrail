"""Tests Phase B — passthrough / conformité média : API + propagation sync_ready (§XVI.2).

Couvre :
  - PATCH /media/{id}/encode-mode (auto|passthrough, re-trigger, validations)
  - POST  /media/{id}/reanalyze
  - POST  /media/{id}/passthrough-ack → entrée cms_audit_log
  - propagation : un média non sync-ready (conformance playable/nonconform) rend
    la playlist non sync_ready (détail) + remonte conformance_status par item
"""

import uuid
from unittest.mock import patch

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.audit_log import CmsAuditLog
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PtOrg", org_slug=f"pt-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"pt-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_PT_{uid}", label="Pt", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("media", "read"), ("media", "edit"), ("playlists", "read")]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation
            )
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Password1!"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _video(db_session, org, **over) -> CmsMedia:
    media = CmsMedia(
        id_org=org.id_org, media_name="clip.mp4", media_type="video",
        storage_key=f"test/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        transcode_status="done",
    )
    for k, v in over.items():
        setattr(media, k, v)
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)
    return media


async def test_encode_mode_toggle_and_validation(client, auth_token, db_session, org):
    headers = {"Authorization": f"Bearer {auth_token}"}
    media = await _video(db_session, org)

    with patch("app.workers.media_worker.transcode_media.delay") as mock_delay:
        resp = await client.patch(
            f"/api/v1/media/{media.id_media}/encode-mode",
            json={"encode_mode": "passthrough"}, headers=headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["encode_mode"] == "passthrough"
    assert resp.json()["transcode_status"] == "pending"
    mock_delay.assert_called_once_with(media.id_media)

    # Mode invalide → 422
    bad = await client.patch(
        f"/api/v1/media/{media.id_media}/encode-mode",
        json={"encode_mode": "turbo"}, headers=headers,
    )
    assert bad.status_code == 422


async def test_encode_mode_rejected_for_image(client, auth_token, db_session, org):
    headers = {"Authorization": f"Bearer {auth_token}"}
    img = CmsMedia(
        id_org=org.id_org, media_name="logo.png", media_type="image",
        storage_key=f"test/{uuid.uuid4().hex}.png", checksum_sha256=uuid.uuid4().hex,
        transcode_status="done",
    )
    db_session.add(img)
    await db_session.commit()
    await db_session.refresh(img)
    resp = await client.patch(
        f"/api/v1/media/{img.id_media}/encode-mode",
        json={"encode_mode": "passthrough"}, headers=headers,
    )
    assert resp.status_code == 422


async def test_reanalyze(client, auth_token, db_session, org):
    headers = {"Authorization": f"Bearer {auth_token}"}
    media = await _video(db_session, org, encode_mode="passthrough", conformance_status="ready")
    with patch("app.workers.media_worker.transcode_media.delay") as mock_delay:
        resp = await client.post(f"/api/v1/media/{media.id_media}/reanalyze", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["transcode_status"] == "pending"
    mock_delay.assert_called_once_with(media.id_media)


async def test_passthrough_ack_writes_audit(client, auth_token, db_session, org):
    headers = {"Authorization": f"Bearer {auth_token}"}
    media = await _video(
        db_session, org, encode_mode="passthrough", conformance_status="playable",
        media_metadata={"conformance": {"status": "playable", "reasons": ["Framerate variable (VFR)"]}},
    )
    resp = await client.post(
        f"/api/v1/media/{media.id_media}/passthrough-ack",
        json={"note": "validé par le client"}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["conformance_status"] == "playable"

    row = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "media_passthrough_ack",
            CmsAuditLog.resource_id == str(media.id_media),
        )
    )).scalar_one()
    assert row.resource_type == "media"
    assert row.detail["note"] == "validé par le client"
    assert "Framerate variable (VFR)" in row.detail["reasons"]


async def test_sync_ready_blocked_by_nonconform_media(client, auth_token, db_session, org):
    headers = {"Authorization": f"Bearer {auth_token}"}
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Mur", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()

    # Média sync-ready (durée résolue) → playlist sync_ready
    ok_media = await _video(db_session, org, duration_ms=5000, conformance_status="ready")
    db_session.add(CmsPlaylistItem(
        id_playlist=pl.id_playlist, id_media=ok_media.id_media, sort_order=0, duration_ms=5000,
    ))
    await db_session.commit()

    detail = await client.get(f"/api/v1/playlists/{pl.id_playlist}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["sync_ready"] is True

    # Ajout d'un média passthrough non conforme → casse la sync_ready
    bad_media = await _video(db_session, org, duration_ms=5000, conformance_status="nonconform")
    db_session.add(CmsPlaylistItem(
        id_playlist=pl.id_playlist, id_media=bad_media.id_media, sort_order=1, duration_ms=5000,
    ))
    await db_session.commit()

    detail2 = await client.get(f"/api/v1/playlists/{pl.id_playlist}", headers=headers)
    assert detail2.json()["sync_ready"] is False
    confs = {it["id_media"]: it["conformance_status"] for it in detail2.json()["items"]}
    assert confs[bad_media.id_media] == "nonconform"
    assert confs[ok_media.id_media] == "ready"
