"""Dashboard « Mission Control » — gardes et surface exposée (audit du 2026-07-28).

Le menu Dashboard n'avait AUCUN test : c'est une des raisons pour lesquelles les défauts
de l'audit y ont vécu sans être vus. Ce fichier couvre ce que la page consomme vraiment.

Couvre :
  · le gate org-admin des 3 routes `/dashboard/*` (mesuré 403 pour tous les autres profils) ;
  · le fait que le fil d'activité **n'expose plus** le champ `detail` de l'audit — un
    dictionnaire libre alimenté depuis une quarantaine d'endroits du code, qu'aucun écran
    ne lit. Rien de secret n'y a été mesuré en production, mais l'exposer par défaut
    revenait à publier d'avance tout ce qu'un futur `detail={...}` bavard y mettrait.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

_DASHBOARD_ROUTES = [
    "/api/v1/dashboard/summary",
    "/api/v1/dashboard/activity",
    "/api/v1/dashboard/media",
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Dash", org_slug=f"dash-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(
    db: AsyncSession, org: CmsOrganization, *, org_admin: bool, perms: list[tuple[str, str]]
) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"d-{uid}@test.com", full_name=f"User {uid}",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_D_{uid}", label="D", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in perms:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db.flush()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    if org_admin:
        await db.execute(
            pg_insert(CmsRole)
            .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin",
                    is_system=True)
            .on_conflict_do_nothing(index_elements=["role_key"])
        )
        await db.flush()
        oa = (await db.execute(
            select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
        )).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=oa.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest.mark.asyncio
async def test_dashboard_routes_are_org_admin_only(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Mesuré en production : gouvernance, report viewer, viewer et annonceur → 403."""
    admin = await _mk_user(db_session, org, org_admin=True, perms=[])
    # Un porteur de TOUTES les permissions de lecture concernées reste non-admin.
    other = await _mk_user(db_session, org, org_admin=False, perms=[
        ("reports", "read"), ("players", "read"), ("media", "read"), ("campaigns", "read"),
    ])
    for route in _DASHBOARD_ROUTES:
        assert (await client.get(route, headers=_h(admin))).status_code == 200, route
        assert (await client.get(route, headers=_h(other))).status_code == 403, route
        assert (await client.get(route)).status_code in (401, 403), route


@pytest.mark.asyncio
async def test_activity_feed_never_exposes_audit_detail(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Le fil résout le NOM de la ressource, et ne renvoie JAMAIS le `detail` de l'audit.

    Rouge avant le correctif : `detail` figurait dans `ActivityItem`, donc la charge utile
    contenait le dictionnaire brut — ici un faux secret, pour que l'échec soit parlant.
    """
    admin = await _mk_user(db_session, org, org_admin=True, perms=[])
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Boucle Vitrine")
    db_session.add(playlist)
    await db_session.flush()
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="update",
        resource_type="playlist", resource_id=str(playlist.id_playlist),
        detail={"token_bidon": "NE-DOIT-JAMAIS-SORTIR", "from": "a", "to": "b"},
        source="cms",
    ))
    await db_session.commit()

    r = await client.get("/api/v1/dashboard/activity", headers=_h(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    item = next(i for i in body["items"] if i["resource_type"] == "playlist")

    # Ce que le fil DOIT porter : de quoi écrire « Update · Boucle Vitrine ».
    assert item["resource_name"] == "Boucle Vitrine"
    assert item["action"] == "update"
    assert item["user_name"] == admin.full_name

    # Ce qu'il ne doit PAS porter : le dict d'audit, sous aucune forme.
    assert "detail" not in item
    assert "NE-DOIT-JAMAIS-SORTIR" not in r.text


@pytest.mark.asyncio
async def test_activity_feed_names_deleted_resources_from_the_journal(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Une ressource SUPPRIMÉE garde son nom, pris dans le journal (constat d'Ed 2026-07-29).

    Avant : le nom se résolvait uniquement par lookup en base, donc la ligne d'une playlist
    supprimée s'affichait « Delete · playlist #46 » — précisément l'événement pour lequel on
    a le plus besoin de savoir de quoi on parle. C'est tout l'intérêt d'avoir tracé le nom au
    moment de l'action : la ligne disparaît, le journal reste.

    ⚠️ Le nom sort SEUL : `detail` ne doit toujours pas franchir l'API.
    """
    admin = await _mk_user(db_session, org, org_admin=True, perms=[])
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="delete",
        resource_type="playlist", resource_id="999999",   # purgée : plus aucune ligne
        detail={"playlist_name": "Boucle Noël", "secret_bidon": "NE-DOIT-JAMAIS-SORTIR"},
        source="cms",
    ))
    # Convention concurrente mesurée en prod (campagnes, annonceurs, assistant IA) : `name`.
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="delete",
        resource_type="campaign", resource_id="999998",
        detail={"name": "Campagne Été"}, source="cms",
    ))
    await db_session.commit()

    body = (await client.get("/api/v1/dashboard/activity", headers=_h(admin))).json()
    gone = next(i for i in body["items"] if i["resource_id"] == "999999")
    assert gone["resource_name"] == "Boucle Noël"
    assert gone["resource_gone"] is True          # l'écran ne doit pas en faire un lien mort
    assert "NE-DOIT-JAMAIS-SORTIR" not in str(body)

    camp = next(i for i in body["items"] if i["resource_id"] == "999998")
    assert camp["resource_name"] == "Campagne Été"

    # Une ressource VIVANTE garde son nom ACTUEL (un renommage doit se voir), et n'est
    # évidemment pas signalée comme disparue.
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Nom Actuel")
    db_session.add(playlist)
    await db_session.flush()
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="update",
        resource_type="playlist", resource_id=str(playlist.id_playlist),
        detail={"playlist_name": "Nom Périmé", "renamed_from": "Encore Plus Vieux"},
        source="cms",
    ))
    await db_session.commit()

    body = (await client.get("/api/v1/dashboard/activity", headers=_h(admin))).json()
    live = next(i for i in body["items"] if i["resource_id"] == str(playlist.id_playlist))
    assert live["resource_name"] == "Nom Actuel"
    assert live["resource_gone"] is False


@pytest.mark.asyncio
async def test_activity_feed_never_calls_deleted_what_it_could_not_look_up(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """« supprimé depuis » ne s'affiche que si la ressource a été CHERCHÉE et pas trouvée.

    Vu sur le tableau de bord (2026-11-09) : un créatif de campagne et deux annonceurs bien
    vivants étaient marqués « since deleted ». Deux chemins y menaient :
    - un type que le fil ne sait pas résoudre (`campaign_creative`) : aucun nom en base, donc
      repli sur le journal — et le repli était pris pour une preuve de disparition ;
    - un `resource_id` qui n'est pas un identifiant (l'audit des annonceurs y range le NOM).
    """
    admin = await _mk_user(db_session, org, org_admin=True, perms=[])
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="create",
        resource_type="campaign_creative", resource_id="777001",
        detail={"id_media": 1, "media_name": "Offre de saison.jpg"}, source="cms",
    ))
    db_session.add(CmsAuditLog(
        id_org=org.id_org, id_user=admin.id_user, action="create",
        resource_type="advertiser", resource_id="Verger du Val",
        detail={"name": "Verger du Val"}, source="cms",
    ))
    await db_session.commit()

    body = (await client.get("/api/v1/dashboard/activity", headers=_h(admin))).json()
    creative = next(i for i in body["items"] if i["resource_type"] == "campaign_creative")
    assert creative["resource_name"] == "Offre de saison.jpg"
    assert creative["resource_gone"] is False
    adv = next(i for i in body["items"] if i["resource_type"] == "advertiser")
    assert adv["resource_name"] == "Verger du Val"
    assert adv["resource_gone"] is False


@pytest.mark.asyncio
async def test_activity_feed_is_tenant_scoped(
    client: AsyncClient, db_session: AsyncSession, org
) -> None:
    """Une ligne d'audit d'une AUTRE organisation ne traverse jamais le fil."""
    other_org = CmsOrganization(org_name="Autre", org_slug=f"autre-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=other_org.id_org))
    admin = await _mk_user(db_session, org, org_admin=True, perms=[])
    db_session.add(CmsAuditLog(
        id_org=other_org.id_org, id_user=None, action="delete",
        resource_type="playlist", resource_id="999", detail={}, source="cms",
    ))
    await db_session.commit()

    r = await client.get("/api/v1/dashboard/activity", headers=_h(admin))
    assert r.status_code == 200, r.text
    assert all(i["action"] != "delete" for i in r.json()["items"])
