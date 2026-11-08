"""
Gouvernance §XVIII — **D-b** : les cibles d'un programme gouverné FILTRENT le périmètre du nœud.

Le cas d'Ed : un magasin, 5 écrans, deux playlists différentes sur « entrée » et « boucherie »,
les autres ne recevant que l'héritage. Avant D-b, une couche gouvernée s'appliquait à TOUS les
écrans du nœud et les cibles classiques étaient ignorées — d'où le contournement à ~400 nœuds.

Ce que ces tests protègent, au-delà de la règle elle-même : **la COUVERTURE**. Le filtrage doit
valoir sur les TROIS chemins, or deux d'entre eux (`prefetch`, `player_inventory`) re-sélectionnent
les programmes gouvernés en direct sans passer par `gather_layers` — un oubli là ne casse pas la
diffusion, il pré-télécharge et attend du contenu jamais joué (classe de bug de l'audit 2026-07-18).
"""

import uuid
from datetime import datetime

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.governance import (
    CmsGovernanceAssignment,
    CmsGovernanceNode,
    CmsGovernanceNodeAdmin,
)
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser

NOW = datetime(2026, 7, 27, 12, 0)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovScope", org_slug=f"govscope-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    u = CmsUser(id_org=org.id_org, email=f"govscope-{uid}@test.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(u)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_GSCOPE_{uid}", label="GScope",
                   is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("governance", "read"), ("governance", "edit"),
        ("schedules", "read"), ("schedules", "create"), ("schedules", "edit"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, user: CmsUser) -> str:
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── Fabrique du magasin d'Ed : 1 nœud site, 3 écrans, un groupe « Entrées » ───

class Store:
    node: CmsGovernanceNode
    entrance: CmsPlayer
    butcher: CmsPlayer
    other: CmsPlayer
    group_entrance: CmsPlayerGroup
    id_site: int


async def _playlist(db: AsyncSession, id_org: int, dur_ms: int) -> tuple[int, int]:
    """(id_playlist, id_media) — une playlist d'un seul média, durée distinctive."""
    uid = uuid.uuid4().hex[:6]
    m = CmsMedia(id_org=id_org, media_name=f"vid-{uid}", media_type="video",
                 storage_key=f"k/{uid}", checksum_sha256=uid * 4, duration_ms=dur_ms)
    db.add(m)
    await db.flush()
    pl = CmsPlaylist(id_org=id_org, playlist_name=f"pl-{uid}")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media,
                           sort_order=0, duration_ms=dur_ms))
    await db.flush()
    return pl.id_playlist, m.id_media


async def _governed_schedule(
    db: AsyncSession, id_org: int, id_node: int, id_playlist: int,
    targets: list[tuple[str, int]] | None = None, prio: int = 10,
) -> int:
    s = CmsSchedule(id_org=id_org, schedule_name=f"sch-{uuid.uuid4().hex[:6]}",
                    schedule_kind="content", id_playlist=id_playlist,
                    id_governance_node=id_node, priority=prio)
    db.add(s)
    await db.flush()
    db.add(CmsScheduleRule(id_schedule=s.id_schedule, rule_type="always"))
    for ttype, tid in (targets or []):
        db.add(CmsScheduleTarget(id_schedule=s.id_schedule, target_type=ttype, target_id=tid))
    await db.flush()
    return s.id_schedule


@pytest_asyncio.fixture
async def store(db_session: AsyncSession, org: CmsOrganization, user: CmsUser) -> Store:
    site = CmsSite(id_org=org.id_org, site_name=f"Magasin-{uuid.uuid4().hex[:5]}")
    db_session.add(site)
    await db_session.flush()

    st = Store()
    st.id_site = site.id_site
    node = CmsGovernanceNode(id_org=org.id_org, node_name="Site TOTO", node_level=1)
    db_session.add(node)
    await db_session.flush()
    node.path = str(node.id_node)
    st.node = node
    # L'utilisateur administre le nœud (chemin réel : ce n'est pas un org-admin).
    db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=user.id_user))

    players = {}
    for key, name in (("entrance", "Entrée"), ("butcher", "Boucherie"), ("other", "Réserve")):
        p = CmsPlayer(id_org=org.id_org, player_name=f"{name}-{uuid.uuid4().hex[:4]}",
                      id_site=site.id_site)
        db_session.add(p)
        await db_session.flush()
        players[key] = p
    st.entrance, st.butcher, st.other = players["entrance"], players["butcher"], players["other"]

    # Le nœud couvre TOUT le magasin (assignation par site) — c'est le périmètre.
    db_session.add(CmsGovernanceAssignment(
        id_node=node.id_node, target_type="site", target_id=site.id_site))

    # D1 : « les écrans d'entrée » = un GROUPE de players.
    g = CmsPlayerGroup(id_org=org.id_org, group_name=f"Entrées-{uuid.uuid4().hex[:4]}")
    db_session.add(g)
    await db_session.flush()
    db_session.add(CmsPlayerGroupMember(id_group=g.id_group, id_player=st.entrance.id_player))
    st.group_entrance = g

    await db_session.commit()
    return st


async def _layer_schedules(db: AsyncSession, id_org: int, id_player: int) -> set[int]:
    from app.api.v1.endpoints.governance import gather_layers
    layers = await gather_layers(db, id_org, id_player, NOW)
    return {l.id_schedule for l in layers}


# ── Le moteur ────────────────────────────────────────────────────────────────

async def test_targeted_governed_program_reaches_only_its_screens(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """Le cas « entrée + boucherie » : deux programmes du MÊME nœud, deux périmètres."""
    pl_entrance, _ = await _playlist(db_session, org.id_org, 5000)
    pl_butcher, _ = await _playlist(db_session, org.id_org, 7000)
    s_entrance = await _governed_schedule(
        db_session, org.id_org, store.node.id_node, pl_entrance,
        targets=[("player_group", store.group_entrance.id_group)])
    s_butcher = await _governed_schedule(
        db_session, org.id_org, store.node.id_node, pl_butcher,
        targets=[("player", store.butcher.id_player)])
    await db_session.commit()

    assert await _layer_schedules(db_session, org.id_org, store.entrance.id_player) == {s_entrance}
    assert await _layer_schedules(db_session, org.id_org, store.butcher.id_player) == {s_butcher}
    # Le 3e écran du magasin n'est visé par aucun des deux : il ne reçoit rien LOCALEMENT.
    assert await _layer_schedules(db_session, org.id_org, store.other.id_player) == set()


async def test_governed_program_without_target_covers_the_whole_node(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """D0 — sans cible, tout le nœud. C'est le parc existant : toute autre règle l'éteindrait."""
    pl, _ = await _playlist(db_session, org.id_org, 4000)
    s = await _governed_schedule(db_session, org.id_org, store.node.id_node, pl)
    await db_session.commit()

    for p in (store.entrance, store.butcher, store.other):
        assert await _layer_schedules(db_session, org.id_org, p.id_player) == {s}


async def test_inherited_layer_is_never_restricted_by_a_lower_node(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """D2b — le national atteint TOUS les écrans, y compris ceux qu'un programme local cible.

    Sans cette garantie, un magasin se soustrairait à la communication nationale — et en
    Retail Media une diffusion vendue au national ne serait plus certaine.
    """
    national = CmsGovernanceNode(id_org=org.id_org, node_name="National", node_level=0)
    db_session.add(national)
    await db_session.flush()
    national.path = str(national.id_node)
    # Le site devient enfant du national (le path porte la hiérarchie).
    store.node.parent_id = national.id_node
    store.node.path = f"{national.id_node}.{store.node.id_node}"
    store.node.node_level = 1

    pl_nat, _ = await _playlist(db_session, org.id_org, 9000)
    pl_loc, _ = await _playlist(db_session, org.id_org, 3000)
    s_nat = await _governed_schedule(db_session, org.id_org, national.id_node, pl_nat, prio=80)
    s_loc = await _governed_schedule(
        db_session, org.id_org, store.node.id_node, pl_loc,
        targets=[("player_group", store.group_entrance.id_group)])
    await db_session.commit()

    assert await _layer_schedules(db_session, org.id_org, store.entrance.id_player) == {s_nat, s_loc}
    assert await _layer_schedules(db_session, org.id_org, store.butcher.id_player) == {s_nat}
    assert await _layer_schedules(db_session, org.id_org, store.other.id_player) == {s_nat}


async def test_site_group_target_keeps_only_the_part_inside_the_node(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """Recouvrement PARTIEL accepté : une cible qui déborde n'apporte que sa part du nœud.

    Le site voisin est ciblé par le même groupe de sites mais n'appartient pas au nœud —
    il ne doit pas recevoir la couche pour autant (les cibles ne peuvent que restreindre).
    """
    from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember

    neighbour_site = CmsSite(id_org=org.id_org, site_name=f"Voisin-{uuid.uuid4().hex[:5]}")
    db_session.add(neighbour_site)
    await db_session.flush()
    neighbour = CmsPlayer(id_org=org.id_org, player_name="Voisin-1", id_site=neighbour_site.id_site)
    db_session.add(neighbour)

    sg = CmsSiteGroup(id_org=org.id_org, group_name=f"Région-{uuid.uuid4().hex[:4]}")
    db_session.add(sg)
    await db_session.flush()
    db_session.add(CmsSiteGroupMember(id_site_group=sg.id_site_group, id_site=store.id_site,
                                      id_org=org.id_org))
    db_session.add(CmsSiteGroupMember(id_site_group=sg.id_site_group, id_org=org.id_org,
                                      id_site=neighbour_site.id_site))

    pl, _ = await _playlist(db_session, org.id_org, 6000)
    s = await _governed_schedule(db_session, org.id_org, store.node.id_node, pl,
                                 targets=[("site_group", sg.id_site_group)])
    await db_session.commit()

    assert await _layer_schedules(db_session, org.id_org, store.entrance.id_player) == {s}
    # Le voisin n'est dans AUCUN nœud → aucune couche (le nœud reste la borne supérieure).
    assert await _layer_schedules(db_session, org.id_org, neighbour.id_player) == set()


# ── Les deux consommateurs satellites (le vrai risque) ───────────────────────

async def test_prefetch_and_inventory_follow_the_same_targets(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """`prefetch` et `player_inventory` ne passent PAS par `gather_layers`.

    Oubliés, ils pré-téléchargeraient et compteraient comme attendu du contenu que cet
    écran ne jouera jamais (faux « média manquant »).
    """
    from app.services.player_inventory import expected_media
    from app.services.prefetch import upcoming_media

    pl, id_media = await _playlist(db_session, org.id_org, 5000)
    await _governed_schedule(db_session, org.id_org, store.node.id_node, pl,
                             targets=[("player_group", store.group_entrance.id_group)])
    await db_session.commit()

    entrance = {m["id_media"] for m in await expected_media(db_session, store.entrance.id_player)}
    butcher = {m["id_media"] for m in await expected_media(db_session, store.butcher.id_player)}
    assert id_media in entrance
    assert id_media not in butcher

    assert id_media in await upcoming_media(db_session, store.entrance.id_player, NOW)
    assert id_media not in await upcoming_media(db_session, store.butcher.id_player, NOW)


# ── R10 : nommer la BONNE cause ──────────────────────────────────────────────

async def test_diagnose_names_the_targeting_cause(
    db_session: AsyncSession, org: CmsOrganization, store: Store
) -> None:
    """Un écran non ciblé doit s'entendre dire « hors ciblage », pas « hors fenêtre » —
    sinon on cherche au mauvais endroit (le défaut même que R10 corrigeait)."""
    from app.api.v1.endpoints.governance import diagnose_no_layers

    pl, _ = await _playlist(db_session, org.id_org, 5000)
    await _governed_schedule(db_session, org.id_org, store.node.id_node, pl,
                             targets=[("player_group", store.group_entrance.id_group)])
    await db_session.commit()

    diag = await diagnose_no_layers(db_session, org.id_org, store.butcher.id_player, NOW)
    assert diag["reason"] == "outside_targets"
    assert diag["detail"]  # le programme est NOMMÉ


# ── D3 : refuser au moment du geste, jamais après coup ───────────────────────

async def test_target_outside_perimeter_is_refused_at_write_time(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, store: Store
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    pl, _ = await _playlist(db_session, org.id_org, 5000)

    outsider_site = CmsSite(id_org=org.id_org, site_name=f"Ailleurs-{uuid.uuid4().hex[:5]}")
    db_session.add(outsider_site)
    await db_session.flush()
    outsider = CmsPlayer(id_org=org.id_org, player_name="Écran d'un autre magasin",
                         id_site=outsider_site.id_site)
    db_session.add(outsider)
    await db_session.commit()

    body = {
        "schedule_name": "Entrées", "schedule_kind": "content", "id_playlist": pl,
        "id_governance_node": store.node.id_node, "rules": [{"rule_type": "always"}],
        "targets": [{"target_type": "player", "target_id": outsider.id_player}],
    }
    resp = await client.post("/api/v1/schedules", json=body, headers=headers)
    assert resp.status_code == 422, resp.text
    assert "Écran d'un autre magasin" in resp.json()["detail"]  # la cible est NOMMÉE

    # La même cible, dans le périmètre, passe.
    body["targets"] = [{"target_type": "player_group",
                        "target_id": store.group_entrance.id_group}]
    ok = await client.post("/api/v1/schedules", json=body, headers=headers)
    assert ok.status_code == 201, ok.text
    id_schedule = ok.json()["id_schedule"]

    # Et l'écriture de cibles suit la même règle.
    bad = await client.put(
        f"/api/v1/schedules/{id_schedule}/targets",
        json=[{"target_type": "player", "target_id": outsider.id_player}], headers=headers)
    assert bad.status_code == 422, bad.text

    # ⛔ Aucune ré-invalidation après coup : la cible posée reste en base.
    rows = (await db_session.execute(select(CmsScheduleTarget).where(
        CmsScheduleTarget.id_schedule == id_schedule))).scalars().all()
    assert [(r.target_type, r.target_id) for r in rows] == [
        ("player_group", store.group_entrance.id_group)]


async def test_scope_preview_matches_what_will_be_saved(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, store: Store
) -> None:
    """L'aperçu et la validation partagent le même service : ils ne peuvent pas diverger."""
    headers = {"Authorization": f"Bearer {auth_token}"}

    empty = await client.post("/api/v1/schedules/governance-scope", headers=headers, json={
        "id_governance_node": store.node.id_node, "targets": []})
    assert empty.status_code == 200, empty.text
    assert empty.json()["perimeter_count"] == 3
    assert empty.json()["resolved_count"] == 3  # D0 : sans cible, tout le nœud

    one = await client.post("/api/v1/schedules/governance-scope", headers=headers, json={
        "id_governance_node": store.node.id_node,
        "targets": [{"target_type": "player_group", "target_id": store.group_entrance.id_group}]})
    assert one.json()["resolved_count"] == 1
    assert one.json()["out_of_scope"] == []
    assert [p["id_player"] for p in one.json()["players"]] == [store.entrance.id_player]


async def test_admin_candidates_say_what_a_role_can_actually_do(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, user: CmsUser
) -> None:
    """R8/R9 — nommer un admin de nœud sans `schedules:edit` fabrique un admin SANS POUVOIR.

    « Admin de nœud » ne fait que **restreindre** par-dessus le RBAC : il n'accorde rien.
    Deux nominations sont donc inutiles et rien ne le signalait — celle d'un rôle sans
    `schedules:edit`, et celle d'un org-admin (qui contourne déjà la gouvernance).
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    resp = await client.get("/api/v1/governance/admin-candidates", headers=headers)
    assert resp.status_code == 200, resp.text
    me = next(c for c in resp.json() if c["id_user"] == user.id_user)
    # Le rôle du fixture porte schedules:read/create/edit → il PEUT programmer.
    assert me["can_program"] is True
    assert me["bypasses_governance"] is False
    assert me["roles"], "le rôle doit être exposé — c'est son absence qui a fait douter Ed"

    # Un utilisateur sans aucun rôle : nommable, mais sans le moindre pouvoir.
    inert = CmsUser(id_org=org.id_org, email=f"inert-{uuid.uuid4().hex[:8]}@test.com",
                    password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(inert)
    await db_session.commit()
    resp = await client.get("/api/v1/governance/admin-candidates", headers=headers)
    row = next(c for c in resp.json() if c["id_user"] == inert.id_user)
    assert row["can_program"] is False
    assert row["roles"] == []


async def test_lan_sync_split_is_reported_but_never_blocks(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, store: Store
) -> None:
    """D4 — cibler une partie d'un groupe de synchro LAN est ACCEPTÉ, et signalé.

    Refuser aurait interdit le cas entrée/boucherie dans un magasin déjà câblé en un seul
    groupe — la situation la plus probable. Techniquement rien ne casse (la clé de synchro
    dérive des couches actives), mais devant l'écran personne ne peut le deviner : deux
    dalles côte à côte, synchronisées, qui ne jouent plus la même chose.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    # Les 3 écrans du magasin sont dans le MÊME groupe de synchro LAN.
    for p in (store.entrance, store.butcher, store.other):
        p.display_config = {"lan_sync_enabled": True, "lan_sync_group": "Magasin LAN"}
        db_session.add(p)
    await db_session.commit()

    body = {
        "id_governance_node": store.node.id_node,
        "targets": [{"target_type": "player_group", "target_id": store.group_entrance.id_group}],
    }
    resp = await client.post("/api/v1/schedules/governance-scope", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    split = resp.json()["lan_sync_split"]
    assert len(split) == 1, split
    assert split[0]["group"] == "Magasin LAN"
    assert split[0]["kept"] == [store.entrance.player_name]
    assert sorted(split[0]["excluded"]) == sorted(
        [store.butcher.player_name, store.other.player_name])

    # ⛔ Un avertissement, pas un blocage : le même ciblage s'enregistre sans erreur.
    pl, _ = await _playlist(db_session, org.id_org, 5000)
    ok = await client.post("/api/v1/schedules", headers=headers, json={
        "schedule_name": "Entrées", "schedule_kind": "content", "id_playlist": pl,
        "id_governance_node": store.node.id_node, "rules": [{"rule_type": "always"}],
        "targets": body["targets"],
    })
    assert ok.status_code == 201, ok.text

    # Groupe ENTIÈREMENT retenu (aucune cible = tout le nœud) → rien à signaler.
    whole = await client.post("/api/v1/schedules/governance-scope", headers=headers, json={
        "id_governance_node": store.node.id_node, "targets": []})
    assert whole.json()["lan_sync_split"] == []


async def test_node_coverage_reports_screens_no_local_layer_targets(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, store: Store
) -> None:
    """Contrepartie assumée de D1 : un écran oublié dans son groupe ne reçoit que
    l'héritage **sans que rien ne le signale**. Ce compteur le signale."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    pl, _ = await _playlist(db_session, org.id_org, 5000)
    await _governed_schedule(db_session, org.id_org, store.node.id_node, pl,
                             targets=[("player_group", store.group_entrance.id_group)])
    await db_session.commit()

    resp = await client.get(f"/api/v1/governance/nodes/{store.node.id_node}/coverage",
                            headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["perimeter_count"] == 3
    assert data["schedules"][0]["resolved_count"] == 1
    uncovered = {u["id_player"] for u in data["uncovered"]}
    assert uncovered == {store.butcher.id_player, store.other.id_player}
