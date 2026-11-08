"""Audit menu ⑪ Players (2026-07-31) — traçabilité des gestes qui touchent un écran.

Le PÉRIMÈTRE de ce menu est déjà couvert (Phase 2 gouvernance du 27/07 : `_enforce_user_scope`
sur le détail, le programme compilé, la disponibilité et l'inventaire ; les autres lectures
sont org-admin). Ce qui manque est ailleurs :

🔑 **L'asymétrie qui met sur la piste** — la commande EN MASSE est journalisée (« un clic
distrait coûte cher », dit son propre commentaire), la commande UNITAIRE ne l'est pas. Or
redémarrer UN écran de vitrine en pleine journée coûte exactement le même prix à l'exploitant.
Le même trou vaut pour le renommage/la configuration d'affichage, la SUPPRESSION d'un écran
et la ROTATION DE SON JETON — trois gestes dont « qui, et quand ? » est la première question
posée après coup.
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
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PlayAudit", org_slug=f"pa-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org) -> CmsUser:
    """Org-admin : toutes les mutations de ce menu lui sont réservées."""
    user = CmsUser(
        id_org=org.id_org, email=f"pa-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org) -> CmsPlayer:
    site = CmsSite(id_org=org.id_org, site_name="Mag")
    db_session.add(site)
    await db_session.flush()
    p = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Vitrine")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


async def _audit_count(db: AsyncSession, org, action: str | None = None) -> int:
    stmt = select(func.count()).select_from(CmsAuditLog).where(
        CmsAuditLog.id_org == org.id_org, CmsAuditLog.resource_type == "player")
    if action is not None:
        stmt = stmt.where(CmsAuditLog.action == action)
    return (await db.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_single_command_is_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin, player
) -> None:
    """La commande EN MASSE est journalisée, la commande UNITAIRE ne l'était pas — or
    redémarrer un écran de vitrine en pleine journée coûte le même prix à l'exploitant."""
    r = await client.post(f"/api/v1/players/{player.id_player}/command",
                          headers=_h(admin), json={"command": "restart"})
    assert r.status_code == 202, r.text
    assert await _audit_count(db_session, org, "command") >= 1


@pytest.mark.asyncio
async def test_update_is_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin, player
) -> None:
    """Renommer un écran ou changer sa configuration d'affichage change ce qu'on voit à
    l'antenne (résolution, rotation, sync LAN) : le journal doit dire qui l'a fait."""
    r = await client.put(f"/api/v1/players/{player.id_player}",
                         headers=_h(admin), json={"player_name": "Vitrine renommée"})
    assert r.status_code == 200, r.text
    assert await _audit_count(db_session, org, "update") >= 1


@pytest.mark.asyncio
async def test_delete_is_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin, player
) -> None:
    """Le geste le plus destructif du menu — et le seul dont on ne pouvait pas dire l'auteur."""
    r = await client.delete(f"/api/v1/players/{player.id_player}", headers=_h(admin))
    assert r.status_code == 204, r.text
    assert await _audit_count(db_session, org, "delete") >= 1


@pytest.mark.asyncio
async def test_token_rotation_is_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin, player
) -> None:
    """Émettre un nouveau jeton machine, c'est délivrer une identité d'écran : un geste de
    SÉCURITÉ. Il doit laisser une trace — sans le jeton lui-même, évidemment."""
    r = await client.post(f"/api/v1/players/{player.id_player}/token", headers=_h(admin))
    assert r.status_code == 200, r.text
    n = await _audit_count(db_session, org, "token_rotate")
    assert n >= 1
    rows = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == "player",
            CmsAuditLog.action == "token_rotate")
    )).scalars().all()
    dumped = " ".join(str(r0.detail) for r0 in rows)
    assert "eyJ" not in dumped, "le jeton ne doit JAMAIS être recopié dans le journal"
