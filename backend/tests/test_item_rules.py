"""
Tests I1 — règles de diffusion par item de playlist (§ retours clients item 4, P1).

Couvre : CRUD des règles (PUT/GET, vide=perpétuel), validation scope/rule_type (422),
propagation sync_ready + has_item_rules + has_rules, et la résolution runtime
`_filter_items_by_rules` (item perpétuel gardé, item hors-fenêtre retiré).
"""

import uuid
from datetime import datetime, time

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _filter_items_by_rules
from app.core.security import hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist, CmsPlaylistItem, CmsPlaylistItemRule
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

# 2026-06-01 = lundi
MON = datetime(2026, 6, 1)
assert MON.weekday() == 0


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="IR", org_slug=f"ir-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"ir-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_IR_{uid}", label="IR", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("playlists", "create"), ("playlists", "read"),
                              ("playlists", "edit"), ("playlists", "delete")]:
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


@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                 storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                 transcode_status="done", duration_ms=5000)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


async def _make_playlist_with_item(client, headers, media_id):
    pl = (await client.post("/api/v1/playlists",
                            json={"playlist_name": "P", "sync_mode": "wall_clock"},
                            headers=headers)).json()
    item = (await client.post(f"/api/v1/playlists/{pl['id_playlist']}/items",
                              json={"id_media": media_id, "sort_order": 0},
                              headers=headers)).json()
    return pl["id_playlist"], item["id_item"]


# ── CRUD & validation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_and_get_rules(client, auth_token, media_item):
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id, item_id = await _make_playlist_with_item(client, h, media_item.id_media)

    body = [{"rule_type": "weekly", "days_of_week": [5, 6],
             "time_start": "09:00:00", "time_end": "18:00:00"}]
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules", json=body, headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["days_of_week"] == [5, 6]

    got = await client.get(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules", headers=h)
    assert got.status_code == 200 and len(got.json()) == 1


@pytest.mark.asyncio
async def test_empty_put_clears_rules(client, auth_token, media_item):
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id, item_id = await _make_playlist_with_item(client, h, media_item.id_media)
    await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                     json=[{"rule_type": "always"}], headers=h)
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules", json=[], headers=h)
    assert r.status_code == 200 and r.json() == []
    got = await client.get(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules", headers=h)
    assert got.json() == []


@pytest.mark.asyncio
async def test_scope_player_requires_target(client, auth_token, media_item):
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id, item_id = await _make_playlist_with_item(client, h, media_item.id_media)
    # scope player sans target_id → 422
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                         json=[{"rule_type": "always", "scope": "player"}], headers=h)
    assert r.status_code == 422
    # scope default avec target_id → 422
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                         json=[{"rule_type": "always", "scope": "default", "target_id": 9}], headers=h)
    assert r.status_code == 422
    # scope invalide → 422
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                         json=[{"rule_type": "always", "scope": "site", "target_id": 1}], headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_rule_type_rejected(client, auth_token, media_item):
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id, item_id = await _make_playlist_with_item(client, h, media_item.id_media)
    r = await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                         json=[{"rule_type": "monthly"}], headers=h)
    assert r.status_code == 422


# ── Propagation sync_ready ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_item_rule_default_keeps_windowed_sync(client, auth_token, media_item):
    """Règle scope=default → sync de groupe préservée (sync_ready reste True, sync_windowed).
    Un override scope=player/group casse la synchro (jeux d'items divergents)."""
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id, _ = await _make_playlist_with_item(client, h, media_item.id_media)
    # Staging : on publie l'item neuf pour obtenir un id publié stable (les vues détail
    # reflètent le brouillon, la liste reflète le publié).
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=h)

    # Sans règle : sync_ready True, item perpétuel
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert detail["sync_ready"] is True
    assert detail["has_item_rules"] is False
    assert detail.get("sync_windowed") is False
    item_id = detail["items"][0]["id_item"]  # id publié (stable aux publications suivantes)

    # Règle scope=default : contenu time-varying MAIS player-uniforme → reste syncable (à fenêtres)
    await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                     json=[{"rule_type": "weekly", "days_of_week": [5, 6]}], headers=h)
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=h)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert detail["sync_ready"] is True
    assert detail["sync_windowed"] is True
    assert detail["has_item_rules"] is True
    assert detail["items"][0]["has_rules"] is True

    # La liste reflète aussi sync_windowed (état publié)
    listed = (await client.get("/api/v1/playlists/", headers=h)).json()
    row = next(p for p in listed if p["id_playlist"] == pl_id)
    assert row["has_item_rules"] is True and row["sync_ready"] is True and row["sync_windowed"] is True

    # Override scope=player_group → jeux d'items divergents → casse la synchro
    await client.put(f"/api/v1/playlists/{pl_id}/items/{item_id}/rules",
                     json=[{"rule_type": "weekly", "days_of_week": [5, 6], "scope": "player_group", "target_id": 999}],
                     headers=h)
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=h)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert detail["sync_ready"] is False
    assert detail["sync_windowed"] is False
    assert detail["has_item_rules"] is True


# ── Résolution runtime ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_filter_items_by_rules(db_session, org, media_item):
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    perpetual = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_item.id_media, sort_order=0)
    boxed = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_item.id_media, sort_order=1)
    db_session.add_all([perpetual, boxed])
    await db_session.flush()
    # boxed ne joue que le lundi 09:00-18:00
    db_session.add(CmsPlaylistItemRule(
        id_item=boxed.id_item, scope="default", rule_type="weekly",
        days_of_week=[0], time_start=time(9, 0), time_end=time(18, 0),
    ))
    await db_session.commit()

    items = [{"id_item": perpetual.id_item}, {"id_item": boxed.id_item}]

    # Lundi 12:00 → les deux passent (id_player/groupes indifférents pour default)
    kept = await _filter_items_by_rules(items, MON.replace(hour=12), db_session, 1, set())
    assert {i["id_item"] for i in kept} == {perpetual.id_item, boxed.id_item}

    # Lundi 20:00 → seul le perpétuel passe
    kept = await _filter_items_by_rules(items, MON.replace(hour=20), db_session, 1, set())
    assert {i["id_item"] for i in kept} == {perpetual.id_item}


@pytest.mark.asyncio
async def test_filter_items_by_rules_override_specificity(db_session, org, media_item):
    """Override par cible : player > player_group > default (remplace, pas union)."""
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    item = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_item.id_media, sort_order=0)
    db_session.add(item)
    await db_session.flush()
    # default : lundi 09-12 ; override groupe 7 : lundi 09-18 ; override player 42 : lundi 09-23
    db_session.add_all([
        CmsPlaylistItemRule(id_item=item.id_item, scope="default", rule_type="weekly",
                            days_of_week=[0], time_start=time(9), time_end=time(12)),
        CmsPlaylistItemRule(id_item=item.id_item, scope="player_group", target_id=7, rule_type="weekly",
                            days_of_week=[0], time_start=time(9), time_end=time(18)),
        CmsPlaylistItemRule(id_item=item.id_item, scope="player", target_id=42, rule_type="weekly",
                            days_of_week=[0], time_start=time(9), time_end=time(23)),
    ])
    await db_session.commit()
    items = [{"id_item": item.id_item}]

    async def kept_at(hour, id_player, groups):
        r = await _filter_items_by_rules(items, MON.replace(hour=hour), db_session, id_player, groups)
        return bool(r)

    # Lundi 20:00 : player 42 (override player 09-23) → garde
    assert await kept_at(20, 42, {7})
    # Lundi 20:00 : un membre du groupe 7 sans override player (09-18) → retiré
    assert not await kept_at(20, 99, {7})
    # Lundi 15:00 : membre groupe 7 (09-18) → garde
    assert await kept_at(15, 99, {7})
    # Lundi 15:00 : player sans override ni groupe (default 09-12) → retiré
    assert not await kept_at(15, 99, set())
    # Lundi 10:00 : default 09-12 → garde
    assert await kept_at(10, 99, set())
