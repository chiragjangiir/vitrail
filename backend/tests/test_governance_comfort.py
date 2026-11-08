"""Gouvernance §XVIII — items de CONFORT de la revue du 2026-07-23 (P3, R4).

  · **P3** — un nœud ne pouvait pas être déplacé : `PUT /nodes/{id}` ne touchait que le nom
    et le type. La forme de l'arbre se décidait donc à la CRÉATION, et se corriger imposait
    de détacher les programmes et de tout recréer.
  · **R4** — la sélection de cibles était inutilisable à l'échelle : les listes chargeaient
    TOUT le parc à chaque ouverture d'un nœud (2000 `<option>` natives à 2000 écrans) et
    n'ajoutaient qu'une cible à la fois (« 40 écrans = 40 allers-retours »).

Ce qui compte dans P3 n'est pas le champ mais le **recalcul de `path` et `node_level` sur
tout le sous-arbre** : ce sont eux qui portent l'ordre national→local de la compilation,
l'héritage des restrictions et la garde d'édition. Les laisser périmés ferait mentir tout
le module — d'où les assertions sur les descendants, pas seulement sur le nœud déplacé.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.governance import (
    CmsGovernanceAssignment,
    CmsGovernanceNode,
    CmsGovernanceNodeAdmin,
)
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

_PERMS = [("governance", "read"), ("governance", "edit"), ("governance", "delegate")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovCf", org_slug=f"govcf-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization, *, org_admin: bool = False) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"cf-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_CF_{uid}", label="CF", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in _PERMS:
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
            .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="OA", is_system=True)
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


async def _mk_node(db: AsyncSession, org, name, parent=None):
    n = CmsGovernanceNode(
        id_org=org.id_org, parent_id=parent.id_node if parent else None,
        node_name=name, node_level=(parent.node_level + 1) if parent else 0,
        node_type="store" if parent else "national", requires_approval=False, path="",
    )
    db.add(n)
    await db.flush()
    n.path = f"{parent.path}.{n.id_node}" if parent else str(n.id_node)
    await db.flush()
    return n


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org):
    """national → (dpt_a → site) et dpt_b. Un écran assigné au site."""
    site_row = CmsSite(id_org=org.id_org, site_name="Mag")
    db_session.add(site_row)
    await db_session.flush()
    player = CmsPlayer(id_org=org.id_org, id_site=site_row.id_site, player_name="Ecran 1")
    orphan = CmsPlayer(id_org=org.id_org, id_site=site_row.id_site, player_name="Ecran neuf")
    group = CmsPlayerGroup(id_org=org.id_org, group_name=f"G-{uuid.uuid4().hex[:5]}",
                           group_type="content")
    db_session.add_all([player, orphan, group])
    await db_session.flush()
    db_session.add(CmsPlayerGroupMember(id_group=group.id_group, id_player=player.id_player))

    national = await _mk_node(db_session, org, "National")
    dpt_a = await _mk_node(db_session, org, "Dpt-A", parent=national)
    dpt_b = await _mk_node(db_session, org, "Dpt-B", parent=national)
    site_node = await _mk_node(db_session, org, "Site", parent=dpt_a)
    db_session.add(CmsGovernanceAssignment(
        id_node=site_node.id_node, target_type="player", target_id=player.id_player))

    boss = await _mk_user(db_session, org)
    local = await _mk_user(db_session, org)
    org_admin = await _mk_user(db_session, org, org_admin=True)
    db_session.add_all([
        CmsGovernanceNodeAdmin(id_node=national.id_node, id_user=boss.id_user),
        CmsGovernanceNodeAdmin(id_node=dpt_a.id_node, id_user=local.id_user),
    ])
    await db_session.commit()
    for n in (national, dpt_a, dpt_b, site_node):
        await db_session.refresh(n)
    return {
        "org": org, "national": national, "dpt_a": dpt_a, "dpt_b": dpt_b, "site": site_node,
        "player": player, "orphan": orphan, "group": group, "site_row": site_row,
        "boss": boss, "local": local, "org_admin": org_admin,
    }


# ── P3 : re-parentage ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p3_reparent_recomputes_path_and_levels(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    dpt_a, dpt_b, site = scene["dpt_a"], scene["dpt_b"], scene["site"]

    r = await client.put(f"/api/v1/governance/nodes/{dpt_a.id_node}",
                         json={"parent_id": dpt_b.id_node}, headers=_h(scene["boss"]))
    assert r.status_code == 200, r.text
    assert r.json()["node_level"] == 2

    # ⚠️ On relit les COLONNES, pas les objets ORM : la session de test est partagée avec
    # l'application, ses instances sont déjà chargées et un `expire_all()` déclencherait un
    # rechargement paresseux hors contexte greenlet (MissingGreenlet).
    rows = dict((await db_session.execute(
        select(CmsGovernanceNode.id_node, CmsGovernanceNode.path)
        .where(CmsGovernanceNode.id_node.in_([dpt_a.id_node, site.id_node]))
    )).all())
    levels = dict((await db_session.execute(
        select(CmsGovernanceNode.id_node, CmsGovernanceNode.node_level)
        .where(CmsGovernanceNode.id_node.in_([dpt_a.id_node, site.id_node]))
    )).all())

    # Le nœud déplacé ET son descendant portent le nouveau chemin et le bon niveau : c'est
    # ce qui fixe l'ordre de compilation et l'héritage — pas le seul `parent_id`.
    expected = f"{scene['national'].id_node}.{dpt_b.id_node}.{dpt_a.id_node}"
    assert rows[dpt_a.id_node] == expected
    assert rows[site.id_node] == f"{expected}.{site.id_node}"
    assert (levels[dpt_a.id_node], levels[site.id_node]) == (2, 3)


@pytest.mark.asyncio
async def test_p3_reparent_refuses_cycles_and_foreign_grafts(
    client: AsyncClient, scene
) -> None:
    nat, dpt_a, site = scene["national"], scene["dpt_a"], scene["site"]

    # Sous son propre descendant → 422 (sinon la branche se détache de l'arbre EN SILENCE).
    r = await client.put(f"/api/v1/governance/nodes/{dpt_a.id_node}",
                         json={"parent_id": site.id_node}, headers=_h(scene["boss"]))
    assert r.status_code == 422, r.text
    # Sur lui-même → 422.
    r = await client.put(f"/api/v1/governance/nodes/{dpt_a.id_node}",
                         json={"parent_id": dpt_a.id_node}, headers=_h(scene["boss"]))
    assert r.status_code == 422, r.text

    # Greffer sous un nœud qu'on n'administre pas → 403 (l'admin de Dpt-A n'a rien à faire
    # sous le national).
    r = await client.put(f"/api/v1/governance/nodes/{site.id_node}",
                         json={"parent_id": nat.id_node}, headers=_h(scene["local"]))
    assert r.status_code == 403, r.text

    # En faire une RACINE = org-admin seul (même règle que la création, N1).
    r = await client.put(f"/api/v1/governance/nodes/{dpt_a.id_node}",
                         json={"parent_id": None}, headers=_h(scene["boss"]))
    assert r.status_code == 403, r.text
    r = await client.put(f"/api/v1/governance/nodes/{dpt_a.id_node}",
                         json={"parent_id": None}, headers=_h(scene["org_admin"]))
    assert r.status_code == 200, r.text
    assert r.json()["node_level"] == 0


# ── R4 : recherche de cibles + ajout par lot ─────────────────────────────────

@pytest.mark.asyncio
async def test_r4_target_search_is_uniform_and_counts_screens(
    client: AsyncClient, scene
) -> None:
    r = await client.get("/api/v1/governance/targets/search",
                         params={"q": "Ecran"}, headers=_h(scene["org_admin"]))
    assert r.status_code == 200, r.text
    by_name = {x["name"]: x for x in r.json()}
    assert by_name["Ecran 1"]["target_type"] == "player"
    assert by_name["Ecran 1"]["subtitle"] == "Mag"       # le site désambiguïse deux homonymes
    assert by_name["Ecran 1"]["player_count"] == 1

    # Un site rend le NOMBRE D'ÉCRANS résolus : dès qu'on mêle sites et groupes, on ne sait
    # plus ce qu'on vient de sélectionner.
    r = await client.get("/api/v1/governance/targets/search",
                         params={"q": "Mag", "types": "site"}, headers=_h(scene["org_admin"]))
    site_hit = r.json()[0]
    assert (site_hit["target_type"], site_hit["player_count"]) == ("site", 2)

    # Le filtre `types` est respecté (le drawer a des pastilles par type).
    r = await client.get("/api/v1/governance/targets/search",
                         params={"q": "", "types": "site_group"}, headers=_h(scene["org_admin"]))
    assert all(x["target_type"] == "site_group" for x in r.json())


@pytest.mark.asyncio
async def test_r4_search_respects_the_write_perimeter(client: AsyncClient, scene) -> None:
    """Une cible proposée doit être ACCEPTÉE à l'écriture — sinon on offre un 422.

    L'admin de Dpt-A voit son écran et l'écran encore non rattaché (porte G2), pas plus.
    """
    r = await client.get("/api/v1/governance/targets/search",
                         params={"q": "Ecran"}, headers=_h(scene["local"]))
    names = {x["name"] for x in r.json()}
    assert names == {"Ecran 1", "Ecran neuf"}

    # Et ce qu'il voit passe réellement à l'écriture.
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['dpt_a'].id_node}/assignments",
        json={"target_type": "player", "target_id": scene["orphan"].id_player},
        headers=_h(scene["local"]))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_r4_batch_add_is_all_or_nothing_and_idempotent(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    node = scene["dpt_b"].id_node
    payload = [
        {"target_type": "player", "target_id": scene["player"].id_player},
        {"target_type": "group", "target_id": scene["group"].id_group},
    ]
    r = await client.post(f"/api/v1/governance/nodes/{node}/assignments/batch",
                          json=payload, headers=_h(scene["org_admin"]))
    assert r.status_code == 201, r.text
    assert len(r.json()) == 2

    # Rejouer le même lot ne duplique rien (re-sélectionner une cible déjà posée n'est pas
    # une erreur — c'est le geste naturel dans un drawer multi-sélection).
    r = await client.post(f"/api/v1/governance/nodes/{node}/assignments/batch",
                          json=payload, headers=_h(scene["org_admin"]))
    assert r.status_code == 201 and len(r.json()) == 2

    # TOUT OU RIEN : une seule cible invalide (cross-tenant) et RIEN n'est écrit — une
    # sélection à moitié appliquée serait pire que refusée.
    other = CmsOrganization(org_name="Autre", org_slug=f"oth-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsPlayer(id_org=other.id_org, player_name="Etranger")
    db_session.add(foreign)
    await db_session.commit()

    before = len((await client.get(f"/api/v1/governance/nodes/{node}",
                                   headers=_h(scene["org_admin"]))).json()["assignments"])
    r = await client.post(f"/api/v1/governance/nodes/{node}/assignments/batch", json=[
        {"target_type": "player", "target_id": scene["orphan"].id_player},
        {"target_type": "player", "target_id": foreign.id_player},
    ], headers=_h(scene["org_admin"]))
    assert r.status_code == 404, r.text
    after = (await client.get(f"/api/v1/governance/nodes/{node}",
                              headers=_h(scene["org_admin"]))).json()["assignments"]
    assert len(after) == before   # l'écran valide du lot n'a PAS été ajouté
