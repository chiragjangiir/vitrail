"""
Tests Sprint 1.8 — Organizations CRUD + auth-settings (§II.1, §2.1.1).

Couvre :
  - test_list_orgs_super_admin
  - test_create_org
  - test_create_org_duplicate_slug
  - test_get_org_super_admin
  - test_get_org_own
  - test_get_org_cross_org_forbidden
  - test_update_org
  - test_get_auth_settings
  - test_update_auth_settings
  - test_update_auth_settings_invalid_policy
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
    slug = f"test-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="Test Org", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def super_admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"superadmin-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SUPER_ADMIN", label="Super Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))
    ).scalar_one()

    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user


@pytest_asyncio.fixture
def super_admin_token(super_admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        super_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"], "locale": "en"},
    )


@pytest_asyncio.fixture
async def org_admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"orgadmin-{uid}@test.com",
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
def org_admin_token(org_admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


# ── Tests CRUD orgs ────────────────────────────────────────────────────────────

async def test_list_orgs_super_admin(
    client: AsyncClient, super_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.get(
        "/api/v1/orgs",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    ids = [o["id_org"] for o in resp.json()]
    assert org.id_org in ids


async def test_list_orgs_forbidden_for_org_admin(
    client: AsyncClient, org_admin_token: str
) -> None:
    resp = await client.get(
        "/api/v1/orgs",
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 403


async def test_create_org(client: AsyncClient, super_admin_token: str) -> None:
    slug = f"new-org-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/orgs",
        json={"org_name": "New Org", "org_slug": slug},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["org_slug"] == slug
    assert data["org_name"] == "New Org"
    assert "id_org" in data


async def test_create_org_duplicate_slug(
    client: AsyncClient, super_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.post(
        "/api/v1/orgs",
        json={"org_name": "Duplicate", "org_slug": org.org_slug},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 409


async def test_get_org_super_admin(
    client: AsyncClient, super_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.get(
        f"/api/v1/orgs/{org.id_org}",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id_org"] == org.id_org


async def test_get_org_own(
    client: AsyncClient, org_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.get(
        f"/api/v1/orgs/{org.id_org}",
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id_org"] == org.id_org


async def test_get_org_cross_org_forbidden(
    client: AsyncClient, org_admin_token: str, db_session: AsyncSession
) -> None:
    other_slug = f"other-{uuid.uuid4().hex[:8]}"
    other = CmsOrganization(org_name="Other Org", org_slug=other_slug)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    resp = await client.get(
        f"/api/v1/orgs/{other.id_org}",
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 404


async def test_update_org(
    client: AsyncClient, super_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.patch(
        f"/api/v1/orgs/{org.id_org}",
        json={"org_name": "Updated Org Name"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["org_name"] == "Updated Org Name"


# ── Tests auth-settings ────────────────────────────────────────────────────────

async def test_get_auth_settings(
    client: AsyncClient, org_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.get(
        f"/api/v1/orgs/{org.id_org}/auth-settings",
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id_org"] == org.id_org
    assert "auth_2fa_policy" in data
    assert "session_lifetime" in data


async def test_update_auth_settings(
    client: AsyncClient, org_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.put(
        f"/api/v1/orgs/{org.id_org}/auth-settings",
        json={"session_lifetime": 120, "auth_2fa_policy": "optional"},
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_lifetime"] == 120
    assert data["auth_2fa_policy"] == "optional"


async def test_update_auth_settings_invalid_policy(
    client: AsyncClient, org_admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.put(
        f"/api/v1/orgs/{org.id_org}/auth-settings",
        json={"auth_2fa_policy": "invalid_value"},
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert resp.status_code == 422
