"""Tests URL Display (§XXV.2) — « Site Web » comme contenu schedulable.

Un url_display est un cms_media (media_type='url_display', sans fichier) ; URL + config webview
dans media_metadata. Couvre : CRUD `/url-display` (https-only, métadonnées), le bloc media émis
au sync (URL live, pas d'URL signée, pas de cache), et l'alerte d'inaccessibilité → audit log.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _audit_player_event, _url_display_media_dict
from app.core.security import hash_password
from app.models.audit_log import CmsAuditLog
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.user import CmsUser

_MEDIA_PERMS = [("media", "create"), ("media", "read"), ("media", "edit"), ("media", "delete")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="URL", org_slug=f"url-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def auth(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    """Utilisateur avec les permissions media (url_display réutilise le module media)."""
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"url-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_URL_{uid}", label="Url", is_system=False)
    db_session.add_all([user, role])
    await db_session.flush()
    for module, operation in _MEDIA_PERMS:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
    await db_session.flush()
    for module, operation in _MEDIA_PERMS:
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ── CRUD endpoint ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_url_display(client, db_session, org, auth):
    resp = await client.post("/api/v1/url-display", headers=_h(auth), json={
        "name": "Dashboard",
        "url": "https://example.com/board",
        "config": {"refresh_interval_s": 300, "scroll_mode": "auto"},
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://example.com/board"
    assert body["config"]["refresh_interval_s"] == 300
    assert body["config"]["scroll_mode"] == "auto"
    # Média sous-jacent : type url_display, sans fichier, directement diffusable.
    media = (await db_session.execute(
        select(CmsMedia).where(CmsMedia.id_media == body["id_media"]))).scalar_one()
    assert media.media_type == "url_display"
    assert media.storage_key == ""           # sentinelle (pas de fichier)
    assert media.transcode_status == "done"  # pas de transcodage
    assert media.media_metadata["url"] == "https://example.com/board"


@pytest.mark.asyncio
async def test_create_rejects_non_https(client, org, auth):
    resp = await client.post("/api/v1/url-display", headers=_h(auth), json={
        "name": "Insecure", "url": "http://example.com",
    })
    assert resp.status_code == 422  # http:// en clair bloqué (§25.2)


@pytest.mark.asyncio
async def test_list_update_delete_roundtrip(client, db_session, org, auth):
    created = (await client.post("/api/v1/url-display", headers=_h(auth), json={
        "name": "Site", "url": "https://a.example.com",
    })).json()
    mid = created["id_media"]

    listing = (await client.get("/api/v1/url-display", headers=_h(auth))).json()
    assert any(x["id_media"] == mid for x in listing)

    upd = await client.put(f"/api/v1/url-display/{mid}", headers=_h(auth), json={
        "name": "Site v2", "url": "https://b.example.com",
        "config": {"zoom": 1.5, "interaction_blocked": False},
    })
    assert upd.status_code == 200, upd.text
    assert upd.json()["url"] == "https://b.example.com"
    assert upd.json()["config"]["zoom"] == 1.5
    assert upd.json()["name"] == "Site v2"

    # Impact de suppression consultable (mêmes règles que les autres contenus).
    impact = await client.get(f"/api/v1/url-display/{mid}/deletion-impact", headers=_h(auth))
    assert impact.status_code == 200, impact.text
    assert "summary" in impact.json()

    delete = await client.delete(f"/api/v1/url-display/{mid}", headers=_h(auth))
    assert delete.status_code == 200
    media = (await db_session.execute(
        select(CmsMedia).where(CmsMedia.id_media == mid))).scalar_one()
    assert media.is_deleted is True


@pytest.mark.asyncio
async def test_requires_permission(client, org):
    # Sans token → 401/403 (pas de média créé sans permission media:create).
    resp = await client.post("/api/v1/url-display", json={
        "name": "X", "url": "https://x.example.com"})
    assert resp.status_code in (401, 403)


# ── Bloc media émis au sync ───────────────────────────────────────────────────

def test_url_display_media_dict_emits_live_url_no_cache():
    """Le bloc media d'un url_display porte l'URL live et AUCUN cache (pas de fichier)."""
    class _M:
        id_media = 7
        media_name = "Board"
        mime_type = "text/uri-list"
        media_metadata = {"url": "https://live.example.com", "refresh_interval_s": 60,
                          "scroll_mode": "none"}
    d = _url_display_media_dict(_M())
    assert d["media_type"] == "url_display"
    assert d["url"] == "https://live.example.com"
    assert d["cache_key"] is None            # rien à cacher
    assert d["cache_checksum"] is None
    assert d["url_config"]["refresh_interval_s"] == 60
    assert d["url_config"]["render_mode"] == "webview"
    assert "url" not in d["url_config"]       # l'URL n'est pas dupliquée dans la config


def test_url_display_media_dict_screenshot_server_emits_image():
    """En mode screenshot_server avec capture prête : on sert l'IMAGE + cache_key (offline-first)."""
    class _M:
        id_media = 8
        media_name = "Board"
        mime_type = "text/uri-list"
        media_metadata = {
            "url": "https://live.example.com", "render_mode": "screenshot_server",
            "screenshot_key": "url_display/8/latest.png",
        }
    d = _url_display_media_dict(_M())
    assert d["url_config"]["render_mode"] == "screenshot_server"
    assert d["cache_key"] == "url_display/8/latest.png"   # caché offline-first comme une image
    assert d["mime_type"] == "image/png"
    assert d["url"] and "url_display/8/latest.png" in d["url"]   # URL signée de l'image, pas le site


def test_url_display_media_dict_screenshot_pending_falls_back_to_webview():
    """screenshot_server SANS capture prête → repli webview (iframe du site live)."""
    class _M:
        id_media = 9
        media_name = "Board"
        mime_type = "text/uri-list"
        media_metadata = {"url": "https://live.example.com", "render_mode": "screenshot_server"}
    d = _url_display_media_dict(_M())
    assert d["url_config"]["render_mode"] == "webview"
    assert d["url"] == "https://live.example.com"
    assert d["cache_key"] is None


# ── Alerte d'inaccessibilité (player → serveur) ──────────────────────────────

@pytest.mark.asyncio
async def test_unreachable_event_writes_audit(db_session, org):
    player = CmsPlayer(id_org=org.id_org, player_name="p", player_os="linux")
    db_session.add(player)
    await db_session.flush()
    await db_session.commit()

    await _audit_player_event(db_session, player.id_player, {
        "type": "player:event", "event": "url_display_unreachable",
        "id_media": 42, "url": "https://down.example.com", "error": "timeout",
    })
    row = (await db_session.execute(
        select(CmsAuditLog).where(CmsAuditLog.action == "url_display_unreachable",
                                  CmsAuditLog.id_org == org.id_org))).scalar_one()
    assert row.resource_type == "url_display"
    assert row.resource_id == "42"
    assert row.detail["url"] == "https://down.example.com"
    assert row.source == "player"


@pytest.mark.asyncio
async def test_unrelated_event_ignored(db_session, org):
    player = CmsPlayer(id_org=org.id_org, player_name="p2", player_os="linux")
    db_session.add(player)
    await db_session.flush()
    await db_session.commit()
    # Un événement inconnu ne crée pas d'audit.
    await _audit_player_event(db_session, player.id_player, {
        "type": "player:event", "event": "something_else"})
    rows = (await db_session.execute(
        select(CmsAuditLog).where(CmsAuditLog.id_org == org.id_org))).scalars().all()
    assert rows == []
