"""Audit menu ⑫ IAM / Rôles (2026-07-31).

Deux constats de départ, mesurés avant d'écrire une ligne :

  · **0 ligne d'audit** pour `user` / `role` / `group` en production, sur plus de 800 —
    tous les autres modules en écrivent (399 pour les écrans, 115 pour les playlists…).
    Or c'est le module qui décide QUI PEUT QUOI : « qui a donné les droits d'administration
    à cette personne, et quand ? » n'avait aucune réponse.
  · les routes qui chargent un COMPTE par identifiant (`GET`, `PATCH`, `DELETE`) le font
    **sans aucun filtre d'organisation** — l'isolation repose uniquement sur la RLS. C'est
    exactement la dépendance dont on a mesuré la fragilité le 30/07 : sur une install client,
    le backend tournait en SUPERUSER et toute la RLS était inerte. Le module des COMPTES est
    le dernier endroit où l'on veut que la seule barrière soit celle qu'on a vue tomber.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


async def _mk_org(db: AsyncSession, slug: str) -> CmsOrganization:
    o = CmsOrganization(org_name=slug, org_slug=f"{slug}-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _mk_org(db_session, "iam")


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> CmsOrganization:
    return await _mk_org(db_session, "iamb")


async def _mk_admin(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    user = CmsUser(
        id_org=org.id_org, email=f"iam-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db.flush()
    role = (await db.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    return user


async def _mk_plain_user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    user = CmsUser(
        id_org=org.id_org, email=f"plain-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


async def _audit_count(db: AsyncSession, org, resource_type: str,
                       action: str | None = None) -> int:
    stmt = select(func.count()).select_from(CmsAuditLog).where(
        CmsAuditLog.id_org == org.id_org, CmsAuditLog.resource_type == resource_type)
    if action is not None:
        stmt = stmt.where(CmsAuditLog.action == action)
    return (await db.execute(stmt)).scalar_one()


# ── Cloisonnement inter-organisations DANS LE CODE ───────────────────────────

@pytest.mark.asyncio
async def test_user_detail_is_org_scoped(
    client: AsyncClient, db_session: AsyncSession, org, org_b
) -> None:
    """Lire le compte d'une AUTRE organisation doit répondre 404 par le CODE, pas grâce
    à la RLS seule (mesuré inerte sur une install client le 30/07)."""
    admin = await _mk_admin(db_session, org)
    foreign = await _mk_plain_user(db_session, org_b)
    r = await client.get(f"/api/v1/users/{foreign.id_user}", headers=_h(admin))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_user_patch_is_org_scoped(
    client: AsyncClient, db_session: AsyncSession, org, org_b
) -> None:
    admin = await _mk_admin(db_session, org)
    foreign = await _mk_plain_user(db_session, org_b)
    r = await client.patch(f"/api/v1/users/{foreign.id_user}", headers=_h(admin),
                           json={"full_name": "Renommé de force"})
    assert r.status_code == 404, r.text
    await db_session.refresh(foreign)
    assert foreign.full_name != "Renommé de force"


@pytest.mark.asyncio
async def test_user_delete_is_org_scoped(
    client: AsyncClient, db_session: AsyncSession, org, org_b
) -> None:
    """Le plus grave des trois : désactiver le compte d'une autre organisation."""
    admin = await _mk_admin(db_session, org)
    foreign = await _mk_plain_user(db_session, org_b)
    r = await client.delete(f"/api/v1/users/{foreign.id_user}", headers=_h(admin))
    assert r.status_code == 404, r.text
    await db_session.refresh(foreign)
    assert foreign.is_active is True, "compte d'une autre organisation désactivé"


# ── Traçabilité (0 ligne mesurée en production) ──────────────────────────────

@pytest.mark.asyncio
async def test_user_create_and_delete_are_audited(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    admin = await _mk_admin(db_session, org)
    r = await client.post("/api/v1/users", headers=_h(admin), json={
        "email": f"nouveau-{uuid.uuid4().hex[:6]}@test.com",
        "password": "Password1!", "full_name": "Nouveau",
    })
    assert r.status_code == 201, r.text
    new_id = r.json()["id_user"]
    assert await _audit_count(db_session, org, "user", "create") >= 1

    d = await client.delete(f"/api/v1/users/{new_id}", headers=_h(admin))
    assert d.status_code == 204, d.text
    assert await _audit_count(db_session, org, "user", "delete") >= 1


@pytest.mark.asyncio
async def test_role_assignment_is_audited(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """🔑 Le geste le plus sensible du produit : donner un rôle, c'est donner des droits.
    C'est aussi celui par lequel l'escalade du 20/07 est passée — sans trace, une
    escalade réussie ne laisse RIEN derrière elle."""
    admin = await _mk_admin(db_session, org)
    target = await _mk_plain_user(db_session, org)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_T_{uuid.uuid4().hex[:6]}",
                   label="Test", is_system=False)
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)

    r = await client.post(f"/api/v1/users/{target.id_user}/roles", headers=_h(admin),
                          json={"id_role": role.id_role})
    assert r.status_code == 204, r.text
    assert await _audit_count(db_session, org, "user_role", "assign") >= 1

    d = await client.delete(f"/api/v1/users/{target.id_user}/roles/{role.id_role}",
                            headers=_h(admin))
    assert d.status_code == 204, d.text
    assert await _audit_count(db_session, org, "user_role", "revoke") >= 1


@pytest.mark.asyncio
async def test_totp_disable_is_audited(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Désactiver la double authentification de quelqu'un abaisse le niveau de sécurité
    de son compte — un geste légitime en dépannage, mais qui doit se voir."""
    admin = await _mk_admin(db_session, org)
    target = await _mk_plain_user(db_session, org)
    target.totp_enabled = True
    await db_session.commit()
    r = await client.post(f"/api/v1/users/{target.id_user}/totp/disable", headers=_h(admin))
    assert r.status_code == 204, r.text
    assert await _audit_count(db_session, org, "user", "totp_disable") >= 1


@pytest.mark.asyncio
async def test_role_permissions_change_is_audited(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Changer les permissions d'un rôle change ce que peuvent faire TOUS ses porteurs,
    d'un coup et sans les toucher : la mutation la plus large du produit."""
    admin = await _mk_admin(db_session, org)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_P_{uuid.uuid4().hex[:6]}",
                   label="Perm", is_system=False)
    db_session.add(role)
    # ⚠️ La base de test est bâtie par `create_all`, SANS les migrations : le catalogue de
    # permissions y est vide. On sème celle qu'on va accorder (même piège que la matrice
    # des rôles, documenté le 27/07).
    from app.models.role import CmsPermission
    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="media", operation="read", label="media.read")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db_session.commit()
    await db_session.refresh(role)
    r = await client.put(f"/api/v1/roles/{role.id_role}/permissions",
                         headers=_h(admin), json={"permissions": ["media:read"]})
    assert r.status_code == 200, r.text
    assert await _audit_count(db_session, org, "role", "permissions") >= 1


# ── Groupes (reste de la série, soldé le 31/07) ──────────────────────────────

@pytest.mark.asyncio
async def test_group_mutations_are_audited(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Un groupe porte des RÔLES : y entrer, c'est en hériter (`rbac.get_user_role_keys`
    unionne rôles directs et rôles de groupe). Les 6 gestes doivent donc laisser une trace
    au même titre qu'une attribution directe — et `groups/{id}/roles` est la **2ᵉ porte**
    de l'escalade réelle du 20/07."""
    from app.models.role import CmsUserGroup

    admin = await _mk_admin(db_session, org)
    member = await _mk_plain_user(db_session, org)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_G_{uuid.uuid4().hex[:6]}",
                   label="G", is_system=False)
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)

    r = await client.post("/api/v1/groups", headers=_h(admin),
                          json={"group_name": "Astreinte", "scope_type": "org"})
    assert r.status_code == 201, r.text
    gid = r.json()["id_group"]

    assert (await client.post(f"/api/v1/groups/{gid}/members/{member.id_user}",
                              headers=_h(admin))).status_code == 204
    assert (await client.post(f"/api/v1/groups/{gid}/roles/{role.id_role}",
                              headers=_h(admin))).status_code == 204
    assert (await client.delete(f"/api/v1/groups/{gid}/roles/{role.id_role}",
                                headers=_h(admin))).status_code == 204
    assert (await client.delete(f"/api/v1/groups/{gid}/members/{member.id_user}",
                                headers=_h(admin))).status_code == 204
    assert (await client.delete(f"/api/v1/groups/{gid}", headers=_h(admin))).status_code == 204

    n = await _audit_count(db_session, org, "group")
    assert n >= 6, f"{n} ligne(s) pour les 6 mutations de groupe"

    # Le NOM du groupe survit à sa suppression — sinon plus rien ne dit pourquoi des
    # utilisateurs ont perdu leurs droits.
    rows = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == "group",
            CmsAuditLog.action == "delete")
    )).scalars().all()
    assert any((r0.detail or {}).get("group_name") == "Astreinte" for r0 in rows)
