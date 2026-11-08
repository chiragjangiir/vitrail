"""Page « Serveur » — `GET /meta/server`.

La garde est le point sensible : la capacité d'encodage et la file sont des propriétés de
la MACHINE, pas d'une organisation. Sur un serveur d'intégrateur, un org-admin de marque ne
doit pas y lire l'activité de ses voisins.
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
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def srv_org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SrvOrg", org_slug=f"srv-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


async def _user_with_role(db: AsyncSession, org: CmsOrganization, role_key: str | None) -> CmsUser:
    u = CmsUser(
        id_org=org.id_org, email=f"{uuid.uuid4().hex[:8]}@srv.test",
        password_hash=hash_password("pass"), full_name="Srv User", is_active=True,
    )
    db.add(u)
    await db.flush()
    if role_key:
        # role_key porte une contrainte UNIQUE globale : on insère ou on récupère.
        await db.execute(
            pg_insert(CmsRole)
            .values(id_org=org.id_org, role_key=role_key, label=role_key, is_system=True)
            .on_conflict_do_nothing(index_elements=["role_key"])
        )
        rid = (await db.execute(select(CmsRole.id_role).where(CmsRole.role_key == role_key))).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=rid))
    await db.commit()
    await db.refresh(u)
    return u


def _headers(u: CmsUser, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + create_access_token(
        u.id_user, {"org": u.id_org, "roles": roles, "locale": "fr"})}


@pytest.mark.asyncio
async def test_le_porteur_voit_la_signaletique_du_serveur(
    client: AsyncClient, db_session: AsyncSession, srv_org: CmsOrganization,
) -> None:
    u = await _user_with_role(db_session, srv_org, "CMS_SUPER_ADMIN")
    r = await client.get("/api/v1/meta/server", headers=_headers(u, ["CMS_SUPER_ADMIN"]))
    assert r.status_code == 200
    d = r.json()
    for key in ("version", "workers", "queue", "throughput", "media", "encode_bands"):
        assert key in d
    # Les bandes affichées viennent du SERVEUR : les dupliquer côté front garantirait
    # qu'elles divergent un jour de ce que le worker applique réellement.
    from app.workers.media_worker import ENCODE_BAND_AUTO_S, ENCODE_BAND_REFUSE_S
    assert d["encode_bands"]["auto_below_s"] == ENCODE_BAND_AUTO_S
    assert d["encode_bands"]["refuse_above_s"] == ENCODE_BAND_REFUSE_S


@pytest.mark.asyncio
async def test_un_compte_ordinaire_est_refuse(
    client: AsyncClient, db_session: AsyncSession, srv_org: CmsOrganization,
) -> None:
    u = await _user_with_role(db_session, srv_org, None)
    r = await client.get("/api/v1/meta/server", headers=_headers(u, ["CMS_VIEWER"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_les_roles_du_JETON_ne_donnent_aucun_droit(
    client: AsyncClient, db_session: AsyncSession, srv_org: CmsOrganization,
) -> None:
    """🔑 Le porteur est déterminé par les rôles EN BASE, jamais par ce que le jeton
    prétend. Un jeton forgé annonçant CMS_SUPER_ADMIN ne doit rien ouvrir."""
    u = await _user_with_role(db_session, srv_org, None)
    r = await client.get("/api/v1/meta/server",
                         headers=_headers(u, ["CMS_SUPER_ADMIN", "CMS_ORG_ADMIN"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_anonyme_refuse(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/meta/server")).status_code in (401, 403)
