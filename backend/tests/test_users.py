"""
Tests Sprint 1.8 — Users, Groups & Roles CRUD (§II.1).

Couvre :
  - test_get_me
  - test_update_me
  - test_create_user
  - test_create_user_duplicate_email
  - test_list_users
  - test_get_user
  - test_update_user
  - test_delete_user
  - test_delete_self_forbidden
  - test_assign_role_to_user
  - test_remove_role_from_user
  - test_create_group
  - test_list_groups
  - test_add_and_remove_group_member
  - test_list_roles
  - test_create_custom_role
  - test_copy_role
  - test_delete_custom_role
  - test_delete_system_role_forbidden
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"users-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="Users Org", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def org_admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"admin-{uid}@users-test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))
    ).scalar_one()

    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user


@pytest_asyncio.fixture
def admin_token(org_admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


@pytest_asyncio.fixture
async def member(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"member-{uid}@users-test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── /users/me ──────────────────────────────────────────────────────────────────

async def test_get_me(client: AsyncClient, admin_token: str, org_admin: CmsUser) -> None:
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id_user"] == org_admin.id_user
    assert resp.json()["email"] == org_admin.email


async def test_update_me(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Alice Updated", "locale": "fr"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Alice Updated"
    assert data["locale"] == "fr"


async def test_update_me_theme(client: AsyncClient, admin_token: str) -> None:
    # défaut = light
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert me.json()["theme"] == "light"
    # bascule en dark = persisté
    resp = await client.patch(
        "/api/v1/users/me",
        json={"theme": "dark"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["theme"] == "dark"
    # valeur invalide rejetée
    bad = await client.patch(
        "/api/v1/users/me",
        json={"theme": "rainbow"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad.status_code == 422


# ── CRUD users ─────────────────────────────────────────────────────────────────

async def test_create_user(client: AsyncClient, admin_token: str) -> None:
    email = f"newuser-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Password1!", "full_name": "New User"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == email
    assert data["full_name"] == "New User"
    assert data["is_active"] is True


async def test_create_user_duplicate_email(
    client: AsyncClient, admin_token: str, member: CmsUser
) -> None:
    resp = await client.post(
        "/api/v1/users",
        json={"email": member.email, "password": "Password1!"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


async def test_list_users(
    client: AsyncClient, admin_token: str, member: CmsUser
) -> None:
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    ids = [u["id_user"] for u in resp.json()]
    assert member.id_user in ids


async def test_get_user(
    client: AsyncClient, admin_token: str, member: CmsUser
) -> None:
    resp = await client.get(
        f"/api/v1/users/{member.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id_user"] == member.id_user


async def test_get_user_not_found(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/users/999999999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


async def test_update_user(
    client: AsyncClient, admin_token: str, member: CmsUser
) -> None:
    resp = await client.patch(
        f"/api/v1/users/{member.id_user}",
        json={"full_name": "Updated Name"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name"


async def test_delete_user(client: AsyncClient, admin_token: str, org: CmsOrganization, db_session: AsyncSession) -> None:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"todel-{uid}@test.com",
        password_hash=hash_password("pass"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.delete(
        f"/api/v1/users/{user.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204

    # User should still exist but be inactive (soft delete)
    get_resp = await client.get(
        f"/api/v1/users/{user.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is False


async def test_delete_self_forbidden(
    client: AsyncClient, admin_token: str, org_admin: CmsUser
) -> None:
    resp = await client.delete(
        f"/api/v1/users/{org_admin.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


# ── Role assignments ───────────────────────────────────────────────────────────

async def test_assign_role_to_user(
    client: AsyncClient, admin_token: str, member: CmsUser, db_session: AsyncSession
) -> None:
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_VIEWER", label="Viewer", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_VIEWER"))
    ).scalar_one()

    resp = await client.post(
        f"/api/v1/users/{member.id_user}/roles",
        json={"id_role": role.id_role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


async def test_org_admin_cannot_assign_super_admin(
    client: AsyncClient, admin_token: str, member: CmsUser, db_session: AsyncSession
) -> None:
    """Régression sécurité (audit 2026-06-24) : un org-admin ne doit PAS pouvoir
    s'assigner / assigner le rôle plateforme CMS_SUPER_ADMIN (escalade verticale
    → contrôle cross-tenant). Doit renvoyer 403, pas 204."""
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SUPER_ADMIN", label="Super Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.commit()
    super_role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))
    ).scalar_one()

    resp = await client.post(
        f"/api/v1/users/{member.id_user}/roles",
        json={"id_role": super_role.id_role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
    # L'assignation ne doit pas avoir été créée
    exists = (
        await db_session.execute(
            select(CmsUserRoleAssignment).where(
                CmsUserRoleAssignment.id_user == member.id_user,
                CmsUserRoleAssignment.id_role == super_role.id_role,
            )
        )
    ).scalar_one_or_none()
    assert exists is None


async def test_org_admin_cannot_assign_other_org_custom_role(
    client: AsyncClient, admin_token: str, member: CmsUser, db_session: AsyncSession
) -> None:
    """Un org-admin ne peut pas assigner un custom role appartenant à une AUTRE org."""
    other = CmsOrganization(org_name="Other", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign_role = CmsRole(
        id_org=other.id_org, role_key=f"custom-{uuid.uuid4().hex[:6]}", label="Foreign", is_system=False
    )
    db_session.add(foreign_role)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/users/{member.id_user}/roles",
        json={"id_role": foreign_role.id_role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


async def test_org_admin_cannot_assign_super_admin_via_group(
    client: AsyncClient, admin_token: str, member: CmsUser, db_session: AsyncSession
) -> None:
    """Régression sécurité (audit rôles 2026-07-20) : l'ESCALADE PAR GROUPE.

    Le correctif du 2026-06-24 avait fermé `POST /users/{id}/roles` mais laissé
    `POST /groups/{id}/roles/{id_role}` sans aucune vérification du rôle demandé.
    Or `rbac.get_user_role_keys` unionne rôles DIRECTS et rôles de GROUPE : un
    org-admin pouvait donc créer un groupe, y attacher CMS_SUPER_ADMIN, s'y
    ajouter, et obtenir le bypass RBAC/RLS/gouvernance + le contrôle cross-tenant.
    Reproduit en réel le 2026-07-20 (204/204, `check_permission` passait à True).
    """
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SUPER_ADMIN", label="Super Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.commit()
    super_role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))
    ).scalar_one()

    h = {"Authorization": f"Bearer {admin_token}"}
    g = await client.post(
        "/api/v1/groups", json={"group_name": f"esc-{uuid.uuid4().hex[:6]}", "scope_type": "org"}, headers=h
    )
    assert g.status_code == 201
    id_group = g.json()["id_group"]

    resp = await client.post(f"/api/v1/groups/{id_group}/roles/{super_role.id_role}", headers=h)
    assert resp.status_code == 403, "Escalade par groupe : CMS_SUPER_ADMIN ne doit pas être attachable"

    # Et surtout : le rôle ne doit pas avoir été réellement attaché au groupe.
    from app.models.role import CmsGroupRole
    linked = (
        await db_session.execute(
            select(CmsGroupRole).where(
                CmsGroupRole.id_group == id_group,
                CmsGroupRole.id_role == super_role.id_role,
            )
        )
    ).scalar_one_or_none()
    assert linked is None


async def test_org_admin_cannot_attach_other_org_role_to_group(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """Même porte : un custom role d'une AUTRE org ne s'attache pas à un groupe."""
    other = CmsOrganization(org_name="Other", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsRole(
        id_org=other.id_org, role_key=f"custom-{uuid.uuid4().hex[:6]}", label="Foreign", is_system=False
    )
    db_session.add(foreign)
    await db_session.commit()

    h = {"Authorization": f"Bearer {admin_token}"}
    g = await client.post(
        "/api/v1/groups", json={"group_name": f"grp-{uuid.uuid4().hex[:6]}", "scope_type": "org"}, headers=h
    )
    id_group = g.json()["id_group"]
    resp = await client.post(f"/api/v1/groups/{id_group}/roles/{foreign.id_role}", headers=h)
    assert resp.status_code == 403


async def test_org_admin_cannot_copy_super_admin_role(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """Troisième porte : `POST /roles/{id}/copy` recopie les PERMISSIONS de la
    source. Copier CMS_SUPER_ADMIN produirait un custom role portant les 71
    permissions du catalogue — assignable, lui, sans restriction."""
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SUPER_ADMIN", label="Super Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.commit()
    super_role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))
    ).scalar_one()

    resp = await client.post(
        f"/api/v1/roles/{super_role.id_role}/copy",
        json={"role_key": f"clone-{uuid.uuid4().hex[:6]}", "label": "Clone"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


async def test_remove_role_from_user(
    client: AsyncClient, admin_token: str, member: CmsUser, db_session: AsyncSession
) -> None:
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SCHEDULER", label="Scheduler", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SCHEDULER"))
    ).scalar_one()

    await db_session.execute(
        pg_insert(CmsUserRoleAssignment)
        .values(id_user=member.id_user, id_role=role.id_role)
        .on_conflict_do_nothing()
    )
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/users/{member.id_user}/roles/{role.id_role}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


# ── Groups ─────────────────────────────────────────────────────────────────────

async def test_create_group(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/groups",
        json={"group_name": f"Team-{uuid.uuid4().hex[:6]}", "scope_type": "org"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id_group" in data
    assert data["is_active"] is True


async def test_list_groups(client: AsyncClient, admin_token: str) -> None:
    await client.post(
        "/api/v1/groups",
        json={"group_name": f"ListGroup-{uuid.uuid4().hex[:6]}", "scope_type": "org"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        "/api/v1/groups",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_add_and_remove_group_member(
    client: AsyncClient, admin_token: str, member: CmsUser
) -> None:
    create_resp = await client.post(
        "/api/v1/groups",
        json={"group_name": f"Grp-{uuid.uuid4().hex[:6]}", "scope_type": "org"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    gid = create_resp.json()["id_group"]

    add_resp = await client.post(
        f"/api/v1/groups/{gid}/members/{member.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert add_resp.status_code == 204

    del_resp = await client.delete(
        f"/api/v1/groups/{gid}/members/{member.id_user}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204


# ── Roles ──────────────────────────────────────────────────────────────────────

async def test_list_roles(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_custom_role(client: AsyncClient, admin_token: str) -> None:
    role_key = f"CUSTOM_{uuid.uuid4().hex[:8].upper()}"
    resp = await client.post(
        "/api/v1/roles",
        json={"role_key": role_key, "label": "Custom Role"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role_key"] == role_key
    assert data["is_system"] is False


async def test_copy_role(
    client: AsyncClient, admin_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_DESIGNER", label="Designer", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    source = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_DESIGNER"))
    ).scalar_one()
    await db_session.commit()

    new_key = f"CUSTOM_DESIGNER_{uuid.uuid4().hex[:6].upper()}"
    resp = await client.post(
        f"/api/v1/roles/{source.id_role}/copy",
        json={"role_key": new_key, "label": "Custom Designer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role_key"] == new_key
    assert data["is_system"] is False


async def test_delete_custom_role(client: AsyncClient, admin_token: str) -> None:
    role_key = f"TODEL_{uuid.uuid4().hex[:8].upper()}"
    create_resp = await client.post(
        "/api/v1/roles",
        json={"role_key": role_key, "label": "To Delete"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    id_role = create_resp.json()["id_role"]

    del_resp = await client.delete(
        f"/api/v1/roles/{id_role}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204


async def test_delete_system_role_forbidden(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    # System roles have id_org=None — the endpoint guards with id_org check → 404
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))
    ).scalar_one()

    resp = await client.delete(
        f"/api/v1/roles/{role.id_role}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404



# Le schéma de test est créé par `Base.metadata.create_all` — les migrations, donc
# le SEED du catalogue de permissions (0002_iam), ne tournent pas. Sans cette
# fixture, `/permissions` renvoie une liste vide et toute écriture de permissions
# échoue en 422 « permissions inconnues » : le test passerait à côté du sujet.
@pytest_asyncio.fixture
async def permissions_catalog(db_session: AsyncSession) -> None:
    from app.models.role import CmsPermission
    rows = [
        ("media", "read"), ("media", "create"),
        ("playlists", "read"), ("schedules", "create"),
        ("users", "read"), ("users", "assign_roles"),
        ("spf", "create"), ("spf", "read"),
    ]
    for module, operation in rows:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}:{operation}")
            .on_conflict_do_nothing()
        )
    await db_session.commit()


# ── Éditeur de permissions (audit rôles 2026-07-20) ───────────────────────────
# Avant : `POST /roles` fabriquait un rôle vide qu'AUCUN endpoint ne pouvait
# ensuite garnir → inerte à vie. Seule la copie d'un rôle système donnait un
# rôle utile, au jeu de droits figé.

async def test_permissions_catalog_marks_spf_unavailable(
    client: AsyncClient, admin_token: str, permissions_catalog: None
) -> None:
    """Le catalogue expose `available=False` pour les modules spécifiés mais non
    développés (`spf:*`, moteur §XIV) — l'éditeur les grise au lieu de laisser
    cocher un droit qui ne protège rien (décision Ed)."""
    resp = await client.get("/api/v1/permissions", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    perms = resp.json()
    assert len(perms) > 0
    by_key = {f"{p['module']}:{p['operation']}": p for p in perms}
    assert by_key["media:read"]["available"] is True
    # spf:* présent au catalogue mais annoncé indisponible
    spf = [p for p in perms if p["module"] == "spf"]
    assert spf and all(p["available"] is False for p in spf)


async def test_set_and_get_custom_role_permissions(
    client: AsyncClient, admin_token: str, permissions_catalog: None
) -> None:
    """Le cycle complet enfin possible : créer un rôle vierge PUIS le garnir."""
    h = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/roles",
        json={"role_key": f"ops-{uuid.uuid4().hex[:6]}", "label": "Ops"},
        headers=h,
    )
    assert created.status_code == 201
    id_role = created.json()["id_role"]

    # Rôle neuf = aucune permission (c'était l'état DÉFINITIF avant ce correctif).
    before = await client.get(f"/api/v1/roles/{id_role}/permissions", headers=h)
    assert before.json() == []

    wanted = ["media:read", "playlists:read", "schedules:create"]
    resp = await client.put(
        f"/api/v1/roles/{id_role}/permissions", json={"permissions": wanted}, headers=h
    )
    assert resp.status_code == 200
    assert sorted(resp.json()) == sorted(wanted)

    after = await client.get(f"/api/v1/roles/{id_role}/permissions", headers=h)
    assert sorted(after.json()) == sorted(wanted)

    # Remplacement (et non fusion) : le jeu envoyé fait foi.
    await client.put(
        f"/api/v1/roles/{id_role}/permissions", json={"permissions": ["media:read"]}, headers=h
    )
    final = await client.get(f"/api/v1/roles/{id_role}/permissions", headers=h)
    assert final.json() == ["media:read"]


async def test_system_role_permissions_are_immutable(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """Un rôle système est partagé par TOUTES les organisations (id_org NULL) :
    le modifier depuis une org changerait son sens pour les autres."""
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_VIEWER"))
    ).scalar_one_or_none()
    if role is None:
        return  # catalogue non seedé sur cette base de test
    resp = await client.put(
        f"/api/v1/roles/{role.id_role}/permissions",
        json={"permissions": ["media:read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code in (403, 404)


async def test_unavailable_and_unknown_permissions_refused(
    client: AsyncClient, admin_token: str, permissions_catalog: None
) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/roles", json={"role_key": f"x-{uuid.uuid4().hex[:6]}", "label": "X"}, headers=h
    )
    id_role = created.json()["id_role"]

    unknown = await client.put(
        f"/api/v1/roles/{id_role}/permissions",
        json={"permissions": ["media:read", "nawak:boom"]}, headers=h,
    )
    assert unknown.status_code == 422

    # spf:* existe au catalogue mais la fonctionnalité n'est pas développée.
    unavailable = await client.put(
        f"/api/v1/roles/{id_role}/permissions", json={"permissions": ["spf:create"]}, headers=h
    )
    assert unavailable.status_code == 422
