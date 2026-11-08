"""
Tests Sprint 2.7 — Gouvernance §XVIII Phase 2 — immutabilité par couche (403).

- **Service** (`user_can_edit_node`) : sous-arbre (admin national édite local), ancêtre
  interdit (admin local n'édite pas national), nœud NULL libre, bypass org-admin.
- **HTTP** : CRUD admins de nœud ; enforcement 403→201 sur create_schedule gouverné ;
  schedule non gouverné éditable par tous.
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.governance import CmsGovernanceNode, CmsGovernanceNodeAdmin
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
from app.services.governance_access import user_can_edit_node


# ── Fixtures & helpers ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovImm", org_slug=f"govimm-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _node(db: AsyncSession, org: CmsOrganization, name: str, parent=None) -> CmsGovernanceNode:
    n = CmsGovernanceNode(
        id_org=org.id_org, node_name=name,
        parent_id=parent.id_node if parent else None,
        node_level=(parent.node_level + 1) if parent else 0, path="",
    )
    db.add(n)
    await db.flush()
    n.path = f"{parent.path}.{n.id_node}" if parent else str(n.id_node)
    await db.flush()
    return n


async def _user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    u = CmsUser(
        id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _assign_role_key(db: AsyncSession, org: CmsOrganization, user: CmsUser, role_key: str) -> None:
    """Affecte un rôle système (role_key globalement unique) à un utilisateur (get-or-create)."""
    await db.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key=role_key, label=role_key, is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.flush()


# ── Tests service : user_can_edit_node ────────────────────────────────────────

async def test_admin_of_national_edits_subtree(db_session: AsyncSession, org: CmsOrganization) -> None:
    national = await _node(db_session, org, "National")
    local = await _node(db_session, org, "Local", parent=national)
    user = await _user(db_session, org)
    db_session.add(CmsGovernanceNodeAdmin(id_node=national.id_node, id_user=user.id_user))
    await db_session.commit()

    assert await user_can_edit_node(db_session, user, national.id_node) is True
    assert await user_can_edit_node(db_session, user, local.id_node) is True  # descendant


async def test_admin_of_local_cannot_edit_national(db_session: AsyncSession, org: CmsOrganization) -> None:
    national = await _node(db_session, org, "National")
    local = await _node(db_session, org, "Local", parent=national)
    user = await _user(db_session, org)
    db_session.add(CmsGovernanceNodeAdmin(id_node=local.id_node, id_user=user.id_user))
    await db_session.commit()

    assert await user_can_edit_node(db_session, user, local.id_node) is True
    assert await user_can_edit_node(db_session, user, national.id_node) is False  # ancêtre interdit


async def test_null_node_is_unrestricted(db_session: AsyncSession, org: CmsOrganization) -> None:
    user = await _user(db_session, org)
    await db_session.commit()
    assert await user_can_edit_node(db_session, user, None) is True


async def test_org_admin_bypass(db_session: AsyncSession, org: CmsOrganization) -> None:
    national = await _node(db_session, org, "National")
    user = await _user(db_session, org)
    await _assign_role_key(db_session, org, user, "CMS_ORG_ADMIN")
    await db_session.commit()
    # pas admin du nœud, mais org-admin → True
    assert await user_can_edit_node(db_session, user, national.id_node) is True


async def test_node_without_admin_denies_regular_user(db_session: AsyncSession, org: CmsOrganization) -> None:
    national = await _node(db_session, org, "National")
    user = await _user(db_session, org)
    await db_session.commit()
    # nœud gouverné sans aucun admin + utilisateur lambda → False (seul org-admin pourrait)
    assert await user_can_edit_node(db_session, user, national.id_node) is False


# ── Tests HTTP ────────────────────────────────────────────────────────────────

async def _token(
    client: AsyncClient, db: AsyncSession, org: CmsOrganization, perms: list[tuple[str, str]]
) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"h-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_IMM_{uid}", label="Imm", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in perms:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation
            )
        )).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db.flush()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Password1!"}
    )
    assert resp.status_code == 200, resp.text
    return user, resp.json()["access_token"]


async def _playlist(db: AsyncSession, org: CmsOrganization) -> int:
    uid = uuid.uuid4().hex[:6]
    m = CmsMedia(
        id_org=org.id_org, media_name=f"v-{uid}", media_type="video",
        storage_key=f"k/{uid}", checksum_sha256=uid * 4, duration_ms=5000,
    )
    db.add(m)
    await db.flush()
    pl = CmsPlaylist(id_org=org.id_org, playlist_name=f"pl-{uid}")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media, sort_order=0))
    await db.flush()
    return pl.id_playlist


_FULL_PERMS = [
    ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    ("schedules", "create"), ("schedules", "read"), ("schedules", "edit"), ("schedules", "delete"),
]


async def test_node_admins_crud(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    manager, token = await _token(client, db_session, org, _FULL_PERMS)
    headers = {"Authorization": f"Bearer {token}"}
    target, _ = await _token(client, db_session, org, [("schedules", "create")])

    # N1 (2026-07-27) : le manager n'agit que sur un nœud qu'il administre — on l'y installe
    # (en prod, c'est l'org-admin qui crée la racine et nomme le premier admin).
    node = await _node(db_session, org, "N")
    db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=manager.id_user))
    await db_session.commit()

    add = await client.post(
        f"/api/v1/governance/nodes/{node.id_node}/admins",
        json={"id_user": target.id_user}, headers=headers,
    )
    assert add.status_code == 201, add.text
    assert add.json()["email"] == target.email

    lst = (await client.get(f"/api/v1/governance/nodes/{node.id_node}/admins", headers=headers)).json()
    assert {a["id_user"] for a in lst} == {manager.id_user, target.id_user}

    rm = await client.request(
        "DELETE", f"/api/v1/governance/nodes/{node.id_node}/admins",
        json={"id_user": target.id_user}, headers=headers,
    )
    assert rm.status_code == 204
    lst = (await client.get(f"/api/v1/governance/nodes/{node.id_node}/admins", headers=headers)).json()
    assert {a["id_user"] for a in lst} == {manager.id_user}


async def test_create_governed_schedule_403_then_201(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    manager, mtoken = await _token(client, db_session, org, _FULL_PERMS)
    mheaders = {"Authorization": f"Bearer {mtoken}"}
    operator, otoken = await _token(
        client, db_session, org,
        [("schedules", "create"), ("schedules", "edit"), ("schedules", "delete")],
    )
    oheaders = {"Authorization": f"Bearer {otoken}"}

    # N1 : nœud créé côté ORM + manager installé admin (rôle tenu par l'org-admin en prod).
    node = await _node(db_session, org, "Magasin")
    db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=manager.id_user))
    pl = await _playlist(db_session, org)
    await db_session.commit()

    body = {
        "schedule_name": "Promo", "schedule_kind": "content", "id_playlist": pl,
        "id_governance_node": node.id_node,
        "rules": [{"rule_type": "always"}], "targets": [],
    }
    # L'opérateur n'administre pas le nœud → 403
    denied = await client.post("/api/v1/schedules", json=body, headers=oheaders)
    assert denied.status_code == 403, denied.text

    # Le manager le nomme admin du nœud → 201
    await client.post(
        f"/api/v1/governance/nodes/{node.id_node}/admins",
        json={"id_user": operator.id_user}, headers=mheaders,
    )
    ok = await client.post("/api/v1/schedules", json=body, headers=oheaders)
    assert ok.status_code == 201, ok.text
    assert ok.json()["id_governance_node"] == node.id_node


async def test_ungoverned_schedule_unrestricted(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    operator, otoken = await _token(client, db_session, org, [("schedules", "create")])
    oheaders = {"Authorization": f"Bearer {otoken}"}
    pl = await _playlist(db_session, org)
    await db_session.commit()

    body = {
        "schedule_name": "Libre", "schedule_kind": "content", "id_playlist": pl,
        "rules": [{"rule_type": "always"}], "targets": [],
    }
    # Pas de nœud de gouvernance → aucune restriction
    ok = await client.post("/api/v1/schedules", json=body, headers=oheaders)
    assert ok.status_code == 201, ok.text
    assert ok.json()["id_governance_node"] is None
