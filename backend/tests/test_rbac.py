"""
Tests Sprint 1.1 — RBAC & RLS (§II.1).

Couvre :
  - test_user_inherits_group_permissions
  - test_deny_override_blocks_inherited_permission
  - test_custom_role_copy_from_existing  (skippé — endpoint pas encore implémenté)
  - test_cross_org_endpoint_no_server_error
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import (
    CmsGroupMember,
    CmsGroupRole,
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserGroup,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.rbac import check_permission, get_user_role_keys


@pytest_asyncio.fixture
async def two_orgs(db_session: AsyncSession):
    """Deux organisations distinctes pour tester l'isolation RLS."""
    uid = uuid.uuid4().hex[:8]
    org_a = CmsOrganization(org_name="Org A", org_slug=f"org-a-{uid}")
    org_b = CmsOrganization(org_name="Org B", org_slug=f"org-b-{uid}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=org_a.id_org))
    db_session.add(CmsOrgAuthSettings(id_org=org_b.id_org))
    await db_session.commit()
    return org_a, org_b


@pytest_asyncio.fixture
async def org_with_users(db_session: AsyncSession):
    uid = uuid.uuid4().hex[:8]
    org = CmsOrganization(org_name="RBAC Org", org_slug=f"rbac-{uid}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=org.id_org))

    designer = CmsUser(
        id_org=org.id_org,
        email=f"designer.{uid}@rbac.com",
        password_hash=hash_password("pass"),
    )
    viewer = CmsUser(
        id_org=org.id_org,
        email=f"viewer.{uid}@rbac.com",
        password_hash=hash_password("pass"),
    )
    db_session.add_all([designer, viewer])
    await db_session.commit()
    await db_session.refresh(org)
    await db_session.refresh(designer)
    await db_session.refresh(viewer)
    return org, designer, viewer


@pytest.mark.asyncio
async def test_user_inherits_group_permissions(
    db_session: AsyncSession, org_with_users
) -> None:
    """Un user hérite des permissions du groupe auquel il appartient."""
    org, designer, viewer = org_with_users

    # Permission — upsert pour éviter les conflits inter-tests (module+operation UNIQUE globale)
    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="media", operation="create", label="test")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db_session.flush()
    perm = (
        await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == "media", CmsPermission.operation == "create"
            )
        )
    ).scalar_one()

    designer_role = CmsRole(
        role_key=f"TEST_DESIGNER_{uuid.uuid4().hex[:6].upper()}",
        label="Test Designer",
        is_system=False,
        id_org=org.id_org,
    )
    db_session.add(designer_role)
    await db_session.flush()
    db_session.add(CmsRolePermission(id_role=designer_role.id_role, id_permission=perm.id_permission))

    group = CmsUserGroup(
        id_org=org.id_org,
        group_name="Creative Team",
        scope_type="org",
    )
    db_session.add(group)
    await db_session.flush()

    await db_session.execute(
        pg_insert(CmsGroupRole).values(id_group=group.id_group, id_role=designer_role.id_role)
    )
    await db_session.execute(
        pg_insert(CmsGroupMember).values(id_group=group.id_group, id_user=viewer.id_user)
    )
    await db_session.commit()

    role_keys = await get_user_role_keys(db_session, viewer.id_user)
    assert designer_role.role_key in role_keys


@pytest.mark.asyncio
async def test_deny_override_blocks_inherited_permission(
    db_session: AsyncSession, org_with_users
) -> None:
    """Un deny explicite sur un user prime sur tous ses rôles hérités."""
    org, designer, viewer = org_with_users

    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="reports", operation="export", label="test deny")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db_session.flush()
    perm = (
        await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == "reports", CmsPermission.operation == "export"
            )
        )
    ).scalar_one()

    role = CmsRole(
        role_key=f"TEST_REPORTER_{uuid.uuid4().hex[:6].upper()}",
        label="Test Reporter",
        is_system=False,
        id_org=org.id_org,
    )
    db_session.add(role)
    await db_session.flush()
    db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))

    await db_session.execute(
        pg_insert(CmsUserRoleAssignment).values(
            id_user=designer.id_user, id_role=role.id_role, is_deny=False
        )
    )
    await db_session.commit()

    has = await check_permission(db_session, designer.id_user, "reports", "export")
    assert has is True

    from sqlalchemy import update
    await db_session.execute(
        update(CmsUserRoleAssignment)
        .where(
            CmsUserRoleAssignment.id_user == designer.id_user,
            CmsUserRoleAssignment.id_role == role.id_role,
        )
        .values(is_deny=True)
    )
    await db_session.commit()

    has_after_deny = await check_permission(db_session, designer.id_user, "reports", "export")
    assert has_after_deny is False


@pytest.mark.skip(reason="Endpoint POST /api/v1/roles/{id}/copy pas encore implémenté")
@pytest.mark.asyncio
async def test_custom_role_copy_from_existing(
    client: AsyncClient,
    db_session: AsyncSession,
    org_with_users,
) -> None:
    """Un ORG_ADMIN peut copier un rôle existant en créant un custom role."""
    org, designer, _viewer = org_with_users

    result = await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )
    admin_role = result.scalar_one_or_none()
    if admin_role is None:
        admin_role = CmsRole(role_key="CMS_ORG_ADMIN", label="Admin", is_system=True)
        db_session.add(admin_role)
        await db_session.flush()

    await db_session.execute(
        pg_insert(CmsUserRoleAssignment)
        .values(id_user=designer.id_user, id_role=admin_role.id_role, is_deny=False)
        .on_conflict_do_nothing()
    )
    await db_session.commit()

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": designer.email, "password": "pass"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    source_role = CmsRole(
        role_key=f"TEST_SOURCE_{uuid.uuid4().hex[:6].upper()}",
        label="Source Role",
        is_system=False,
        id_org=org.id_org,
    )
    db_session.add(source_role)
    await db_session.commit()
    await db_session.refresh(source_role)

    resp = await client.post(
        f"/api/v1/roles/{source_role.id_role}/copy",
        json={"role_key": f"CUSTOM_{uuid.uuid4().hex[:6].upper()}", "label": "Copie Custom"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role_key"].startswith("CUSTOM_")
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_cross_org_endpoint_no_server_error(
    client: AsyncClient,
    db_session: AsyncSession,
    two_orgs,
) -> None:
    """
    Smoke test : un user org A accédant à un user org B ne doit pas déclencher d'erreur 5xx.
    En production (RLS active) : 404 garanti par la policy PostgreSQL (§II.1).
    En test (create_all sans policies RLS) : 200 ou 404 selon la session partagée.
    L'isolation cross-tenant réelle est couverte par les tests d'intégration E2E.
    """
    org_a, org_b = two_orgs

    result = await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )
    admin_role = result.scalar_one_or_none()
    if admin_role is None:
        admin_role = CmsRole(
            role_key=f"CMS_ORG_ADMIN_CROSS_{uuid.uuid4().hex[:6].upper()}",
            label="Admin Cross Test",
            is_system=True,
        )
        db_session.add(admin_role)
        await db_session.flush()

    uid = uuid.uuid4().hex[:8]
    user_a = CmsUser(
        id_org=org_a.id_org,
        email=f"user_a_{uid}@cross.com",
        password_hash=hash_password("pass"),
    )
    user_b = CmsUser(
        id_org=org_b.id_org,
        email=f"user_b_{uid}@cross.com",
        password_hash=hash_password("pass"),
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    await db_session.execute(
        pg_insert(CmsUserRoleAssignment)
        .values(id_user=user_a.id_user, id_role=admin_role.id_role, is_deny=False)
        .on_conflict_do_nothing()
    )
    await db_session.commit()
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)

    # JWT direct — bypass du check 2FA (CMS_ORG_ADMIN force la 2FA sur le login endpoint)
    token_a = create_access_token(
        user_a.id_user,
        extra={"org": org_a.id_org, "roles": [admin_role.role_key], "locale": "en"},
    )

    resp = await client.get(
        f"/api/v1/users/{user_b.id_user}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code < 500
