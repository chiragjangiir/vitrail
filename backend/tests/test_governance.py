"""
Tests Lot 4b — Gouvernance hiérarchique §XVIII (fondation CRUD).

Couvre : arbre (create/list/detail/path/level), update, delete (blocages),
assignations (player + résolution names + players hérités), règles (CRUD + 422).
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
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


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovOrg", org_slug=f"gov-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"gov-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_GOV_{uid}", label="Gov", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation
            )
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Password1!"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_headers(db_session: AsyncSession, org: CmsOrganization) -> dict:
    """Org-admin forgé — N1 (2026-07-27) : créer un nœud RACINE et nommer le PREMIER admin
    d'un nœud sont des actes d'org-admin ; le gestionnaire de gouvernance n'agit ensuite
    que dans son sous-arbre. ⚠️ `require_permission` ne bypasse que le super-admin → on
    donne aussi les permissions governance via un rôle custom (comme le seed en prod)."""
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"gadm-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_GADM_{uid}", label="GAdm", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation
            )
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    oa = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=oa.id_role))
    await db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


async def test_node_tree_crud(client: AsyncClient, admin_headers: dict) -> None:
    headers = admin_headers

    # Racine
    root = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "National", "node_type": "national"}, headers=headers,
    )).json()
    assert root["node_level"] == 0
    assert root["path"] == str(root["id_node"])

    # Enfant
    child = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Région Nord", "parent_id": root["id_node"], "node_type": "regional"},
        headers=headers,
    )).json()
    assert child["node_level"] == 1
    assert child["path"] == f"{root['id_node']}.{child['id_node']}"

    # Liste = 2 nœuds, racine a 1 enfant
    nodes = (await client.get("/api/v1/governance/nodes", headers=headers)).json()
    assert len(nodes) == 2
    assert next(n for n in nodes if n["id_node"] == root["id_node"])["child_count"] == 1

    # Détail racine inclut l'enfant
    detail = (await client.get(f"/api/v1/governance/nodes/{root['id_node']}", headers=headers)).json()
    assert len(detail["children"]) == 1
    assert detail["children"][0]["id_node"] == child["id_node"]

    # Update
    upd = (await client.put(
        f"/api/v1/governance/nodes/{child['id_node']}",
        json={"node_name": "Nord-Ouest"}, headers=headers,
    )).json()
    assert upd["node_name"] == "Nord-Ouest"

    # Delete racine bloqué (a un enfant)
    blocked = await client.delete(f"/api/v1/governance/nodes/{root['id_node']}", headers=headers)
    assert blocked.status_code == 409

    # Delete enfant OK, puis racine OK
    assert (await client.delete(f"/api/v1/governance/nodes/{child['id_node']}", headers=headers)).status_code == 204
    assert (await client.delete(f"/api/v1/governance/nodes/{root['id_node']}", headers=headers)).status_code == 204
    assert len((await client.get("/api/v1/governance/nodes", headers=headers)).json()) == 0


async def test_assignments_and_inherited_players(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = admin_headers

    p1 = CmsPlayer(id_org=org.id_org, player_name="P1")
    p2 = CmsPlayer(id_org=org.id_org, player_name="P2")
    group = CmsPlayerGroup(id_org=org.id_org, group_name=f"G-{uuid.uuid4().hex[:6]}", group_type="content")
    db_session.add_all([p1, p2, group])
    await db_session.flush()
    db_session.add(CmsPlayerGroupMember(id_group=group.id_group, id_player=p2.id_player))
    await db_session.commit()

    root = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Root"}, headers=headers,
    )).json()
    child = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Child", "parent_id": root["id_node"]},
        headers=headers,
    )).json()

    # Player direct sur la racine, groupe sur l'enfant
    a = (await client.post(
        f"/api/v1/governance/nodes/{root['id_node']}/assignments",
        json={"target_type": "player", "target_id": p1.id_player}, headers=headers,
    )).json()
    assert a["target_name"] == "P1"
    await client.post(
        f"/api/v1/governance/nodes/{child['id_node']}/assignments",
        json={"target_type": "group", "target_id": group.id_group}, headers=headers,
    )

    # players hérités de la racine = p1 (direct) + p2 (via groupe de l'enfant)
    players = (await client.get(f"/api/v1/governance/nodes/{root['id_node']}/players", headers=headers)).json()
    assert sorted(players) == sorted([p1.id_player, p2.id_player])

    # Cible cross-tenant inexistante → 404
    bad = await client.post(
        f"/api/v1/governance/nodes/{root['id_node']}/assignments",
        json={"target_type": "player", "target_id": 999999}, headers=headers,
    )
    assert bad.status_code == 404

    # Détachement
    rm = await client.request(
        "DELETE", f"/api/v1/governance/nodes/{root['id_node']}/assignments",
        json={"target_type": "player", "target_id": p1.id_player}, headers=headers,
    )
    assert rm.status_code == 204
    detail = (await client.get(f"/api/v1/governance/nodes/{root['id_node']}", headers=headers)).json()
    assert detail["assignments"] == []


_RULE_FAMILIES = ("item_count", "time_budget", "time_window", "preemptive")


async def _set_rules_lock(db: AsyncSession, id_node: int, locked: bool) -> None:
    """Pose (ou lève) les restrictions d'écriture des règles d'un nœud, toutes familles.

    En production une restriction ne se LÈVE que depuis un ancêtre STRICT ou l'org-admin —
    c'est tout l'intérêt du modèle : un nœud ne s'auto-délègue pas.
    """
    from app.models.governance import CmsGovernanceNode
    node = (await db.execute(
        select(CmsGovernanceNode).where(CmsGovernanceNode.id_node == id_node)
    )).scalar_one()
    node.rules_locked = {f: locked for f in _RULE_FAMILIES}
    await db.commit()


async def _grant_rules_delegation(db: AsyncSession, id_node: int) -> None:
    await _set_rules_lock(db, id_node, False)


async def test_delegation_rules(
    client: AsyncClient, auth_token: str, admin_headers: dict, db_session: AsyncSession
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    # N1 : racine + première nomination = org-admin (le gestionnaire agit ensuite dessus).
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Budgeted"}, headers=admin_headers,
    )).json()

    # D-d (2026-07-26) : éditer une règle exige d'ADMINISTRER le nœud, comme le contenu (D6) et
    # les programmes. `governance:delegate` seul ne suffit plus — sinon un responsable de
    # département réécrirait les règles du national, et le plafond hérité serait décoratif.
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    admin = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/admins",
        json={"id_user": me["id_user"]}, headers=admin_headers,
    )
    assert admin.status_code in (200, 201), admin.text
    # …et la DÉLÉGATION doit être accordée : par défaut, l'admin d'un nœud ne touche pas à
    # ses propres règles (décision Ed 2026-07-26). Seul un ancêtre strict — ou l'org-admin —
    # coche la case ; ici le nœud est racine, on la pose donc directement en base.
    await _grant_rules_delegation(db_session, node["id_node"])

    # Type invalide → 422
    bad = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "nope", "params": {}}, headers=headers,
    )
    assert bad.status_code == 422

    # D3 : type retiré → 422 (n'est plus dans _VALID_RULE_TYPES)
    removed = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "priority_band", "params": {"min": 0, "max": 9}}, headers=headers,
    )
    assert removed.status_code == 422

    rule = (await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "time_budget", "params": {"sec_per_cycle": 600}, "soft_cut": False},
        headers=headers,
    )).json()
    assert rule["rule_type"] == "time_budget"

    # D5 : une 2e règle du MÊME type sur le nœud → 409
    dup = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "time_budget", "params": {"sec_per_cycle": 300}}, headers=headers,
    )
    assert dup.status_code == 409
    assert rule["params"]["sec_per_cycle"] == 600
    assert rule["soft_cut"] is False

    upd = (await client.put(
        f"/api/v1/governance/rules/{rule['id_rule']}",
        json={"params": {"sec_per_cycle": 300}, "is_active": False}, headers=headers,
    )).json()
    assert upd["params"]["sec_per_cycle"] == 300
    assert upd["is_active"] is False

    rules = (await client.get(f"/api/v1/governance/nodes/{node['id_node']}/rules", headers=headers)).json()
    assert len(rules) == 1

    assert (await client.delete(f"/api/v1/governance/rules/{rule['id_rule']}", headers=headers)).status_code == 204
    assert len((await client.get(f"/api/v1/governance/nodes/{node['id_node']}/rules", headers=headers)).json()) == 0


# ── Plafond hérité + scoping des règles (décisions D-c / D-d, Ed 2026-07-26) ──
# « Le département peut monter jusqu'à 4 » suppose deux choses : que le national puisse
# poser un plafond, et que le département ne puisse pas le relever lui-même. Sans le
# scoping (D-d), la seconde tombe : `governance:delegate` est une permission d'ORGANISATION,
# donc n'importe quel gestionnaire pouvait réécrire les règles du nœud national.

async def test_inherited_cap_limits_descendant_rule(
    client: AsyncClient, auth_token: str, admin_headers: dict, db_session: AsyncSession
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "National"}, headers=admin_headers)).json()
    dept = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Departement", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    for n in (national, dept):
        await client.post(f"/api/v1/governance/nodes/{n['id_node']}/admins",
                          json={"id_user": me["id_user"]}, headers=admin_headers)
    # Racine : son propre admin n'écrit ses règles que si la délégation est accordée.
    # Pour le département, l'utilisateur passe par son statut d'admin d'un ancêtre strict.
    await _grant_rules_delegation(db_session, national["id_node"])

    # Le national diffuse 1 contenu par tour…
    r = await client.post(
        f"/api/v1/governance/nodes/{national['id_node']}/rules",
        json={"rule_type": "item_count", "params": {"max_per_cycle": 1}},
        headers=headers)
    assert r.status_code == 201, r.text
    # …et plafonne ses descendants à 4. Depuis la migr 0110 le plafond vit sur le NŒUD :
    # poser un plafond n'oblige plus à créer une règle de diffusion dont on n'a pas besoin.
    cap = await client.put(
        f"/api/v1/governance/nodes/{national['id_node']}",
        json={"max_for_children": 4}, headers=headers)
    assert cap.status_code == 200, cap.text

    # Le département peut choisir 2, 3 ou 4…
    ok = await client.post(
        f"/api/v1/governance/nodes/{dept['id_node']}/rules",
        json={"rule_type": "item_count", "params": {"max_per_cycle": 4}}, headers=headers)
    assert ok.status_code == 201, ok.text

    # …mais pas 5 : refus FRANC (un plafond qu'on peut dépasser n'est pas un plafond).
    ko = await client.put(
        f"/api/v1/governance/rules/{ok.json()['id_rule']}",
        json={"params": {"max_per_cycle": 5}}, headers=headers)
    assert ko.status_code == 422, ko.text
    assert "4" in ko.json()["detail"]

    # La valeur en base n'a pas bougé.
    rules = (await client.get(
        f"/api/v1/governance/nodes/{dept['id_node']}/rules", headers=headers)).json()
    assert rules[0]["params"]["max_per_cycle"] == 4


async def test_rule_write_requires_node_admin(
    client: AsyncClient, auth_token: str, admin_headers: dict
) -> None:
    """Détenir `governance:delegate` ne suffit plus : il faut administrer le nœud visé."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Hors perimetre"},
        headers=admin_headers)).json()

    # Aucun rattachement d'admin sur ce nœud → écriture refusée.
    r = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "item_count", "params": {"max_per_cycle": 3}}, headers=headers)
    assert r.status_code == 403, r.text


# ── Délégation des règles : monotone vers le bas (décision Ed 2026-07-26) ─────
# « L'arborescence des nœuds et donc leurs règles sont créées au niveau national ; un admin
# inférieur hiérarchiquement ne modifie pas les paramètres, il modifie les contenus. »
# Et surtout : « si la case est décochée à un niveau, tous les nœuds inférieurs ne peuvent
# plus la rouvrir » — sans cette monotonie, le nœud contraint lèverait sa propre contrainte.

async def test_rules_delegation_is_monotone_downwards(
    client: AsyncClient, auth_token: str, admin_headers: dict, db_session: AsyncSession
) -> None:
    from app.models.governance import CmsGovernanceNode

    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat"}, headers=admin_headers)).json()
    dept = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Dept", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    site = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Site", "parent_id": dept["id_node"]},
        headers=admin_headers)).json()

    # L'utilisateur n'administre QUE le site (responsable local type).
    await client.post(f"/api/v1/governance/nodes/{site['id_node']}/admins",
                      json={"id_user": me["id_user"]}, headers=admin_headers)

    rule = {"rule_type": "item_count", "params": {"max_per_cycle": 3}}
    url = f"/api/v1/governance/nodes/{site['id_node']}/rules"

    # 1. Par défaut : aucune délégation → le responsable local ne touche pas aux paramètres.
    assert (await client.post(url, json=rule, headers=headers)).status_code == 403

    # 2. Délégation cochée sur TOUTE la chaîne → il peut.
    for n in (national, dept, site):
        await _grant_rules_delegation(db_session, n["id_node"])
    created = await client.post(url, json=rule, headers=headers)
    assert created.status_code == 201, created.text

    # 3. Le national la retire : le site est verrouillé, MÊME si sa propre case reste cochée.
    await _set_rules_lock(db_session, national["id_node"], True)

    site_row = (await db_session.execute(
        select(CmsGovernanceNode).where(CmsGovernanceNode.id_node == site["id_node"])
    )).scalar_one()
    assert site_row.rules_locked == {f: False for f in _RULE_FAMILIES}  # sa case n'a pas bougé…
    blocked = await client.put(
        f"/api/v1/governance/rules/{created.json()['id_rule']}",
        json={"params": {"max_per_cycle": 2}}, headers=headers)
    assert blocked.status_code == 403, blocked.text   # …mais la chaîne est coupée au-dessus

    # 4. Et il ne peut pas non plus SUPPRIMER la règle pour s'en affranchir.
    assert (await client.delete(
        f"/api/v1/governance/rules/{created.json()['id_rule']}",
        headers=headers)).status_code == 403


async def _set_family_lock(
    db: AsyncSession, id_node: int, family: str, locked: bool
) -> None:
    from app.models.governance import CmsGovernanceNode
    node = (await db.execute(
        select(CmsGovernanceNode).where(CmsGovernanceNode.id_node == id_node)
    )).scalar_one()
    node.rules_locked = {**(node.rules_locked or {}), family: locked}
    await db.commit()


# ── migr 0110 : une restriction PAR FAMILLE ──────────────────────────────────
# Décision Ed du 2026-07-26 : « déléguer le nombre de contenus par tour » et « déléguer la
# préemption » sont deux décisions distinctes — la seconde donne le droit de faire TAIRE les
# niveaux inférieurs. Le booléen unique de la 0109 les confondait.

async def test_rules_lock_is_per_family(
    client: AsyncClient, auth_token: str, admin_headers: dict, db_session: AsyncSession
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat-fam"}, headers=admin_headers)).json()
    site = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Site-fam", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    await client.post(f"/api/v1/governance/nodes/{site['id_node']}/admins",
                      json={"id_user": me["id_user"]}, headers=admin_headers)

    # Le national n'ouvre QUE le nombre de contenus par tour, sur toute la chaîne.
    for n in (national, site):
        await _set_family_lock(db_session, n["id_node"], "item_count", False)

    ok = await client.post(
        f"/api/v1/governance/nodes/{site['id_node']}/rules",
        json={"rule_type": "item_count", "params": {"max_per_cycle": 2}}, headers=headers)
    assert ok.status_code == 201, ok.text

    # …la préemption, elle, reste au national : le site ne peut pas se l'accorder.
    ko = await client.post(
        f"/api/v1/governance/nodes/{site['id_node']}/rules",
        json={"rule_type": "preemptive", "params": {}}, headers=headers)
    assert ko.status_code == 403, ko.text

    detail = (await client.get(
        f"/api/v1/governance/nodes/{site['id_node']}", headers=headers)).json()
    assert detail["rules_locked_effective"] == {
        "item_count": False, "time_budget": True, "time_window": True, "preemptive": True,
    }
    # L'écran doit pouvoir distinguer « verrouillé ici » de « verrouillé au-dessus » :
    # sans ça il afficherait une case décochée sur un paramètre pourtant inaccessible.
    assert detail["rules_locked_above"]["time_budget"] is True
    assert detail["can_edit_rule_types"] == {
        "item_count": True, "time_budget": False, "time_window": False, "preemptive": False,
    }


async def test_a_node_cannot_lift_its_own_restriction(
    client: AsyncClient, auth_token: str, admin_headers: dict
) -> None:
    """Un nœud qui lèverait sa propre restriction la viderait de son sens.

    Symétrie voulue avec `requires_approval` : DURCIR est permis à l'éditeur du nœud,
    LEVER exige un ancêtre strict.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat-self"}, headers=admin_headers)).json()
    site = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Site-self", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    await client.post(f"/api/v1/governance/nodes/{site['id_node']}/admins",
                      json={"id_user": me["id_user"]}, headers=admin_headers)

    lift = await client.put(f"/api/v1/governance/nodes/{site['id_node']}",
                            json={"rules_locked": {"item_count": False}}, headers=headers)
    assert lift.status_code == 403, lift.text

    # Durcir reste permis (et sans effet ici : la famille est déjà restreinte par défaut).
    harden = await client.put(f"/api/v1/governance/nodes/{site['id_node']}",
                              json={"rules_locked": {"item_count": True}}, headers=headers)
    assert harden.status_code == 200, harden.text


# ── migr 0110 : les plafonds vivent sur le NŒUD, pas dans une règle ──────────

async def test_cap_lives_on_the_node_without_any_rule(
    client: AsyncClient, auth_token: str, admin_headers: dict
) -> None:
    """Poser un plafond ne doit plus obliger à créer une règle de diffusion inutile.

    Avant la 0110, `max_for_children` était rangé dans les `params` d'une règle `item_count` :
    pour plafonner ses descendants, le national devait s'inventer une règle de diffusion.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat-cap"}, headers=admin_headers)).json()
    dept = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Dept-cap", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    for n in (national, dept):
        await client.post(f"/api/v1/governance/nodes/{n['id_node']}/admins",
                          json={"id_user": me["id_user"]}, headers=admin_headers)

    # Aucune règle sur le national — seulement un plafond.
    cap = await client.put(f"/api/v1/governance/nodes/{national['id_node']}",
                           json={"max_for_children": 2}, headers=headers)
    assert cap.status_code == 200, cap.text
    assert (await client.get(
        f"/api/v1/governance/nodes/{national['id_node']}/rules", headers=headers)).json() == []

    detail = (await client.get(
        f"/api/v1/governance/nodes/{dept['id_node']}", headers=headers)).json()
    assert detail["inherited_max_per_turn"] == 2

    ko = await client.post(
        f"/api/v1/governance/nodes/{dept['id_node']}/rules",
        json={"rule_type": "item_count", "params": {"max_per_cycle": 3}}, headers=headers)
    assert ko.status_code == 422, ko.text
    assert "2" in ko.json()["detail"]

    # Et le département ne peut pas rouvrir à SES sites ce que le national lui a fermé.
    relax = await client.put(f"/api/v1/governance/nodes/{dept['id_node']}",
                             json={"max_for_children": 5}, headers=headers)
    assert relax.status_code == 422, relax.text


async def test_node_max_item_sec_reaches_the_engine(
    client: AsyncClient, auth_token: str, admin_headers: dict, db_session: AsyncSession
) -> None:
    """La durée max par contenu doit contraindre le nœud LUI-MÊME, sans règle de diffusion.

    C'est la garde qui écarte « la compil de 3 h en un seul fichier » (attaque décrite par Ed) :
    si elle ne descendait pas jusqu'aux contraintes compilées, elle ne protégerait rien.
    """
    import app.api.v1.endpoints.governance as gov
    from app.models.governance import CmsGovernanceNode

    headers = {"Authorization": f"Bearer {auth_token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat-sec"}, headers=admin_headers)).json()
    site = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Site-sec", "parent_id": national["id_node"]},
        headers=admin_headers)).json()
    await client.post(f"/api/v1/governance/nodes/{national['id_node']}/admins",
                      json={"id_user": me["id_user"]}, headers=admin_headers)

    assert (await client.put(f"/api/v1/governance/nodes/{national['id_node']}",
                             json={"max_item_sec": 90}, headers=headers)).status_code == 200

    row = (await db_session.execute(
        select(CmsGovernanceNode).where(CmsGovernanceNode.id_node == site["id_node"])
    )).scalar_one()
    constraints = await gov._node_constraints(db_session, row.id_node, row)
    assert constraints.max_item_sec == 90   # hérité, alors que le site n'a AUCUNE règle


# ── P1 : un GROUPE DE SITES peut ancrer un nœud (2026-07-26) ─────────────────
# Manque releve lors de la revue guidee du 23/07 : les affectations acceptaient players,
# groupes de players et sites, mais pas groupes de sites — alors que la selection de
# perimetre sur carte produit precisement des ensembles de sites reutilisables.
#
# Le test verifie les DEUX SENS. Le sens inverse (player -> noeuds) est celui qui compte :
# une cible acceptee a l'ecriture mais absente du chemin player-centrique serait enregistree,
# comptee dans l'apercu... et jamais diffusee. C'est exactement le defaut trouve le 18/07 sur
# la cible `site`.

async def test_site_group_assignment_reaches_the_player(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession, org: CmsOrganization
) -> None:
    from app.api.v1.endpoints.governance import _anchor_nodes_for_player
    from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember

    headers = admin_headers

    site = CmsSite(id_org=org.id_org, site_name=f"S-{uuid.uuid4().hex[:6]}")
    db_session.add(site)
    await db_session.flush()
    player = CmsPlayer(id_org=org.id_org, player_name="P-sg", id_site=site.id_site)
    grp = CmsSiteGroup(id_org=org.id_org, group_name=f"Region-{uuid.uuid4().hex[:6]}")
    db_session.add_all([player, grp])
    await db_session.flush()
    db_session.add(CmsSiteGroupMember(
        id_site_group=grp.id_site_group, id_site=site.id_site, id_org=org.id_org))
    await db_session.commit()

    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Nat-sg"}, headers=headers)).json()

    added = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/assignments",
        json={"target_type": "site_group", "target_id": grp.id_site_group}, headers=headers)
    assert added.status_code == 201, added.text
    # Le nom du groupe est resolu (sinon l'ecran afficherait « #12 »).
    assert added.json()["target_name"] == grp.group_name

    # Sens direct : le noeud atteint le player du site membre.
    players = (await client.get(
        f"/api/v1/governance/nodes/{node['id_node']}/players", headers=headers)).json()
    assert players == [player.id_player]

    # Sens INVERSE : le player retrouve le noeud (c'est ce chemin qui compile son programme).
    anchors = await _anchor_nodes_for_player(db_session, org.id_org, player.id_player)
    assert node["id_node"] in anchors

    # Cross-tenant : un groupe d'une autre org reste introuvable (404, jamais 403).
    other = CmsOrganization(org_name="Other", org_slug=f"oth-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsSiteGroup(id_org=other.id_org, group_name=f"Foreign-{uuid.uuid4().hex[:6]}")
    db_session.add(foreign)
    await db_session.commit()
    ko = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/assignments",
        json={"target_type": "site_group", "target_id": foreign.id_site_group}, headers=headers)
    assert ko.status_code == 404, ko.text
