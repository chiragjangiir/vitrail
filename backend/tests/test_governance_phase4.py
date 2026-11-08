"""Gouvernance §XVIII — phase 4 : templates, events et VOD entrent dans la hiérarchie.

Ce que l'audit du 2026-07-27 avait mesuré (N3) : un administrateur de MAGASIN a **modifié le
template partagé 5** (200) et **créé un programme visant le BrightSign** d'un autre périmètre.
Cause de fond : ces objets n'avaient **aucune colonne de gouvernance** (migr 0112).

Trois propriétés vérifiées ici :
  1. **écriture gardée par le nœud** — un local ne modifie ni ne supprime un objet national ;
  2. **lecture filtrée** (D6 + G4) — nœud frère invisible, et pour un porteur de rôle de
     gouvernance le contenu d'organisation disparaît ;
  3. **cibles d'un événement gouverné contraintes au périmètre** — sans quoi le rattachement
     ne serait qu'une étiquette : l'événement continuerait à couper le contenu sur n'importe
     quel écran du parc.
Plus le défaut par défaut : tout ce qui existe reste `NULL` ⇒ **aucun changement** pour les
rôles classiques (vérifié explicitement, c'est ce qui rend la migration déployable).
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
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

_PERMS = [
    ("templates", "create"), ("templates", "read"), ("templates", "edit"),
    ("templates", "delete"),
    ("events", "create"), ("events", "read"), ("events", "trigger"), ("events", "delete"),
    ("events", "edit"),
    ("vod", "create"), ("vod", "read"), ("vod", "edit"), ("vod", "delete"),
    ("vod", "trigger"),
    ("governance", "read"), ("playlists", "read"), ("media", "read"), ("players", "read"),
]

_LAYOUT = {"layout_type": "full", "zones": [{"index": 0, "x": 0, "y": 0, "w": 1920, "h": 1080}]}


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Gov4", org_slug=f"gov4-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization, *system_roles: str) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"p4-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_P4_{uid}", label="P4", is_system=False)
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
    for key in system_roles:
        await db.execute(
            pg_insert(CmsRole)
            .values(id_org=org.id_org, role_key=key, label=key, is_system=True)
            .on_conflict_do_nothing(index_elements=["role_key"])
        )
        await db.flush()
        sysrole = (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=sysrole.id_role))
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
    """national → store / sibling. Un écran par magasin, assigné à son nœud."""
    site = CmsSite(id_org=org.id_org, site_name="Mag")
    db_session.add(site)
    await db_session.flush()
    p_store = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="P-store")
    p_sib = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="P-sibling")
    db_session.add_all([p_store, p_sib])
    await db_session.flush()

    national = await _mk_node(db_session, org, "National")
    store = await _mk_node(db_session, org, "Store", parent=national)
    sibling = await _mk_node(db_session, org, "Sibling", parent=national)
    db_session.add_all([
        CmsGovernanceAssignment(id_node=store.id_node, target_type="player",
                                target_id=p_store.id_player),
        CmsGovernanceAssignment(id_node=sibling.id_node, target_type="player",
                                target_id=p_sib.id_player),
    ])

    boss = await _mk_user(db_session, org)
    local = await _mk_user(db_session, org)
    classic = await _mk_user(db_session, org)  # aucun nœud, aucun rôle de gouvernance
    scoped = await _mk_user(db_session, org, "CMS_SITE_PROGRAMMER")  # rôle scopé G4
    db_session.add_all([
        CmsGovernanceNodeAdmin(id_node=national.id_node, id_user=boss.id_user),
        CmsGovernanceNodeAdmin(id_node=store.id_node, id_user=local.id_user),
        CmsGovernanceNodeAdmin(id_node=store.id_node, id_user=scoped.id_user),
    ])
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db_session.add(pl)
    await db_session.commit()
    for obj in (national, store, sibling, p_store, p_sib, pl):
        await db_session.refresh(obj)
    return {
        "org": org, "national": national, "store": store, "sibling": sibling,
        "p_store": p_store, "p_sib": p_sib, "pl": pl,
        "boss": boss, "local": local, "classic": classic, "scoped": scoped,
    }


# ── Templates (le défaut N3 mesuré : template partagé modifié par un magasin) ──

@pytest.mark.asyncio
async def test_template_write_gate_and_read_filter(client: AsyncClient, scene) -> None:
    nat, store, sib = scene["national"], scene["store"], scene["sibling"]

    nat_t = (await client.post("/api/v1/templates", json={
        "template_name": "National", "layout": _LAYOUT,
        "id_governance_node": nat.id_node}, headers=_h(scene["boss"]))).json()
    sib_t = (await client.post("/api/v1/templates", json={
        "template_name": "Sibling", "layout": _LAYOUT,
        "id_governance_node": sib.id_node}, headers=_h(scene["boss"]))).json()
    free_t = (await client.post("/api/v1/templates", json={
        "template_name": "Org", "layout": _LAYOUT}, headers=_h(scene["boss"]))).json()

    # Le local crée sous SON nœud, pas sous le national.
    r = await client.post("/api/v1/templates", json={
        "template_name": "Local", "layout": _LAYOUT,
        "id_governance_node": store.id_node}, headers=_h(scene["local"]))
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/templates", json={
        "template_name": "Pirate", "layout": _LAYOUT,
        "id_governance_node": nat.id_node}, headers=_h(scene["local"]))
    assert r.status_code == 403, r.text

    # N3 : il ne modifie NI ne supprime le template national (mesuré à 200 avant la 0112).
    r = await client.put(f"/api/v1/templates/{nat_t['id_template']}",
                         json={"template_name": "hack"}, headers=_h(scene["local"]))
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/templates/{nat_t['id_template']}",
                            headers=_h(scene["local"]))
    assert r.status_code == 403, r.text

    # D6 : il voit le national (ancêtre, lecture) mais PAS le nœud frère (404).
    assert (await client.get(f"/api/v1/templates/{nat_t['id_template']}",
                             headers=_h(scene["local"]))).status_code == 200
    assert (await client.get(f"/api/v1/templates/{sib_t['id_template']}",
                             headers=_h(scene["local"]))).status_code == 404

    names = {t["template_name"] for t in
             (await client.get("/api/v1/templates", headers=_h(scene["local"]))).json()}
    assert "Sibling" not in names and "National" in names and "Org" in names

    # G4 : pour un porteur de rôle de gouvernance, le template d'ORGANISATION disparaît.
    names = {t["template_name"] for t in
             (await client.get("/api/v1/templates", headers=_h(scene["scoped"]))).json()}
    assert "Org" not in names and "Local" in names
    assert (await client.get(f"/api/v1/templates/{free_t['id_template']}",
                             headers=_h(scene["scoped"]))).status_code == 404

    # ⚠️ Non-régression du contenu NON gouverné : un rôle classique garde le template d'org
    # et peut l'éditer. Les templates GOUVERNÉS, eux, ne lui sont pas visibles — c'est la
    # règle D6 déjà en vigueur pour playlists et médias (qui n'administre aucun nœud ne voit
    # que l'organisation), et c'est précisément ce qu'on vient d'étendre aux templates.
    names = {t["template_name"] for t in
             (await client.get("/api/v1/templates", headers=_h(scene["classic"]))).json()}
    assert names == {"Org"}
    r = await client.put(f"/api/v1/templates/{free_t['id_template']}",
                         json={"description": "ok"}, headers=_h(scene["classic"]))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_template_detach_requires_parent(client: AsyncClient, scene) -> None:
    t = (await client.post("/api/v1/templates", json={
        "template_name": "Local", "layout": _LAYOUT,
        "id_governance_node": scene["store"].id_node}, headers=_h(scene["local"]))).json()
    # N2 : le local ne sort pas son template de la gouvernance…
    r = await client.put(f"/api/v1/templates/{t['id_template']}",
                         json={"id_governance_node": None}, headers=_h(scene["local"]))
    assert r.status_code == 403, r.text
    # …l'admin du nœud parent, si.
    r = await client.put(f"/api/v1/templates/{t['id_template']}",
                         json={"id_governance_node": None}, headers=_h(scene["boss"]))
    assert r.status_code == 200, r.text
    assert r.json()["id_governance_node"] is None


# ── Events : cibles contraintes au périmètre du nœud ─────────────────────────

def _event_body(scene, target_ids, node=None, name="Ev"):
    body = {
        "event_name": name, "event_type": "manual", "event_kind": "content",
        "id_playlist": scene["pl"].id_playlist, "priority": 70,
        "target_config": {"target_type": "player", "target_ids": target_ids},
    }
    if node is not None:
        body["id_governance_node"] = node
    return body


@pytest.mark.asyncio
async def test_event_targets_must_stay_in_node_scope(client: AsyncClient, scene) -> None:
    store, local = scene["store"], scene["local"]

    # L'écran du magasin : accepté.
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [scene["p_store"].id_player], store.id_node),
                          headers=_h(local))
    assert r.status_code == 201, r.text
    ev = r.json()["id_event"]

    # L'écran du magasin VOISIN : refusé en le NOMMANT (sinon l'événement couperait le
    # contenu d'un périmètre qui n'est pas le sien).
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [scene["p_sib"].id_player], store.id_node,
                                           name="Ev2"),
                          headers=_h(local))
    assert r.status_code == 422, r.text
    assert "P-sibling" in r.json()["detail"]

    # « Toute l'organisation » n'a pas de sens sur un événement gouverné.
    body = _event_body(scene, [], store.id_node, name="Ev3")
    body["target_config"] = {"target_type": "org", "target_ids": []}
    r = await client.post("/api/v1/events", json=body, headers=_h(local))
    assert r.status_code == 422, r.text

    # Même règle à la MISE À JOUR (sinon on contournerait la garde en deux temps).
    r = await client.put(f"/api/v1/events/{ev}", json={
        "target_config": {"target_type": "player",
                          "target_ids": [scene["p_sib"].id_player]}},
        headers=_h(local))
    assert r.status_code == 422, r.text

    # Un événement NON gouverné garde son ciblage libre (non-régression).
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [scene["p_sib"].id_player], None, name="Libre"),
                          headers=_h(scene["classic"]))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_event_hetero_targets_stay_in_node_scope(client: AsyncClient, scene) -> None:
    """Forme HÉTÉROGÈNE (2026-07-30) : chaque entrée est contrainte au périmètre du nœud.

    C'est exactement la zone où une omission ne se voit pas — une 2ᵉ entrée hors périmètre
    acceptée parce que la garde ne lisait que la forme héritée aurait rouvert N3.
    """
    store, local = scene["store"], scene["local"]

    # Entrée saine + entrée hors périmètre → 422 qui NOMME l'écran voisin.
    body = _event_body(scene, [], store.id_node, name="Ev-mix")
    body["target_config"] = {"targets": [
        {"target_type": "player", "target_ids": [scene["p_store"].id_player]},
        {"target_type": "player", "target_ids": [scene["p_sib"].id_player]},
    ]}
    r = await client.post("/api/v1/events", json=body, headers=_h(local))
    assert r.status_code == 422, r.text
    assert "P-sibling" in r.json()["detail"]

    # `org` glissé dans un mélange : refusé dès le schéma (org = forme héritée seule).
    body["target_config"] = {"targets": [
        {"target_type": "player", "target_ids": [scene["p_store"].id_player]},
        {"target_type": "org", "target_ids": []},
    ]}
    r = await client.post("/api/v1/events", json=body, headers=_h(local))
    assert r.status_code == 422, r.text

    # Mélange entièrement DANS le périmètre : accepté.
    body["target_config"] = {"targets": [
        {"target_type": "player", "target_ids": [scene["p_store"].id_player]},
    ]}
    r = await client.post("/api/v1/events", json=body, headers=_h(local))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_event_write_gate_and_read_filter(client: AsyncClient, scene) -> None:
    nat_ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_store"].id_player], scene["national"].id_node,
                         name="EvNat"),
        headers=_h(scene["boss"]))).json()["id_event"]

    # Le local ne touche pas l'événement national.
    r = await client.put(f"/api/v1/events/{nat_ev}", json={"event_name": "hack"},
                         headers=_h(scene["local"]))
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/events/{nat_ev}", headers=_h(scene["local"]))
    assert r.status_code == 403, r.text

    # G4 : un événement d'organisation est invisible au porteur de rôle scopé.
    await client.post("/api/v1/events",
                      json=_event_body(scene, [scene["p_sib"].id_player], None, name="EvOrg"),
                      headers=_h(scene["classic"]))
    names = {e["event_name"] for e in
             (await client.get("/api/v1/events", headers=_h(scene["scoped"]))).json()}
    assert "EvOrg" not in names
    # Rôle classique : son propre événement d'organisation reste visible ; l'événement
    # GOUVERNÉ ne l'est pas (règle D6 : qui n'administre aucun nœud ne voit que l'org).
    names = {e["event_name"] for e in
             (await client.get("/api/v1/events", headers=_h(scene["classic"]))).json()}
    assert "EvOrg" in names and "EvNat" not in names


# ── VOD ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vod_write_gate_and_read_filter(client: AsyncClient, scene) -> None:
    nat_vod = (await client.post("/api/v1/vod", json={
        "vod_name": "VodNat", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_store"].id_player],
        "id_governance_node": scene["national"].id_node},
        headers=_h(scene["boss"])))
    assert nat_vod.status_code == 201, nat_vod.text
    nat_id = nat_vod.json()["id_vod"]

    # Le local ne modifie ni ne supprime la VOD nationale.
    r = await client.put(f"/api/v1/vod/{nat_id}", json={"vod_name": "hack"},
                         headers=_h(scene["local"]))
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/vod/{nat_id}", headers=_h(scene["local"]))
    assert r.status_code == 403, r.text

    # G4 : une config d'organisation est invisible au porteur de rôle scopé.
    r = await client.post("/api/v1/vod", json={
        "vod_name": "VodOrg", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_sib"].id_player]}, headers=_h(scene["classic"]))
    assert r.status_code == 201, r.text
    names = {v["vod_name"] for v in
             (await client.get("/api/v1/vod", headers=_h(scene["scoped"]))).json()}
    assert "VodOrg" not in names
    # Rôle classique : sa config d'organisation reste visible, la config gouvernée non (D6).
    names = {v["vod_name"] for v in
             (await client.get("/api/v1/vod", headers=_h(scene["classic"]))).json()}
    assert "VodOrg" in names and "VodNat" not in names


# ── Audit du 2026-07-29 : les trous restés ouverts après la phase 4 ──────────

@pytest.mark.asyncio
async def test_vod_targets_must_stay_in_node_scope(client: AsyncClient, scene) -> None:
    """🔴 La phase 4 avait contraint les cibles des ÉVÉNEMENTS, pas celles de la VOD.

    Rattacher une config VOD à un nœud n'était donc qu'une étiquette : elle continuait à
    pré-charger et à déclencher un plein écran sur n'importe quel écran de l'organisation.
    C'est N3, laissé ouvert d'un seul côté.
    """
    store, local = scene["store"], scene["local"]

    # L'écran du magasin : accepté (témoin — sinon le test passerait pour la mauvaise raison).
    r = await client.post("/api/v1/vod", json={
        "vod_name": "VodStore", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_store"].id_player],
        "id_governance_node": store.id_node}, headers=_h(local))
    assert r.status_code == 201, r.text
    vid = r.json()["id_vod"]

    # L'écran du magasin VOISIN : refusé en le NOMMANT.
    r = await client.post("/api/v1/vod", json={
        "vod_name": "VodHack", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_sib"].id_player],
        "id_governance_node": store.id_node}, headers=_h(local))
    assert r.status_code == 422, r.text
    assert "P-sibling" in r.json()["detail"]

    # Même règle à la MISE À JOUR (sinon la garde se contourne en deux temps).
    r = await client.put(f"/api/v1/vod/{vid}", json={
        "target_mode": "players", "id_players": [scene["p_sib"].id_player]},
        headers=_h(local))
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_event_transitions_require_node_edit(client: AsyncClient, scene) -> None:
    """🔴 activate / deactivate / cancel n'avaient AUCUNE garde de nœud.

    Créer, modifier et supprimer en avaient une depuis la phase 4 — mais mettre à
    l'ANTENNE, non : `events:trigger` suffisait à couper le programme d'un périmètre
    qu'on n'administre pas.
    """
    nat_ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_store"].id_player], scene["national"].id_node,
                         name="EvNatTrans"),
        headers=_h(scene["boss"]))).json()["id_event"]

    for action in ("activate", "deactivate", "cancel"):
        r = await client.post(f"/api/v1/events/{nat_ev}/{action}", headers=_h(scene["local"]))
        assert r.status_code == 403, f"{action} → {r.status_code} {r.text}"

    # Témoin : l'administrateur du nœud, lui, active bien (la garde ne bloque pas tout).
    r = await client.post(f"/api/v1/events/{nat_ev}/activate", headers=_h(scene["boss"]))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_detail_by_id_does_not_bypass_the_list_filter(client: AsyncClient, scene) -> None:
    """🔴 « La liste filtre, le lien direct ment » — ici avec une mise à l'antenne à la clé.

    ⚠️ Le cas de fuite est le nœud FRÈRE, pas l'ancêtre : par contrat D6 un administrateur
    de magasin LIT le contenu national (en lecture seule). C'est la branche voisine qui doit
    être invisible — et elle restait lisible par identifiant, la config VOD restant même
    DÉCLENCHABLE.
    """
    sib, local = scene["sibling"], scene["local"]

    sib_ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_sib"].id_player], sib.id_node, name="EvSibDetail"),
        headers=_h(scene["boss"]))).json()["id_event"]
    sib_vod = (await client.post("/api/v1/vod", json={
        "vod_name": "VodSibDetail", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_sib"].id_player],
        "id_governance_node": sib.id_node}, headers=_h(scene["boss"]))).json()["id_vod"]

    # L'admin du magasin voisin ne doit rien atteindre de cette branche.
    assert (await client.get(f"/api/v1/events/{sib_ev}", headers=_h(local))).status_code == 404
    assert (await client.get(f"/api/v1/vod/{sib_vod}", headers=_h(local))).status_code == 404
    # ⚠️ `vod:trigger` a dû être ajoutée aux permissions des comptes de test : sans elle
    # on mesurait un simple refus de permission (403) et la garde de VISIBILITÉ n'était
    # jamais atteinte — le test serait passé pour la mauvaise raison.
    r = await client.post(f"/api/v1/vod/{sib_vod}/play", json={"id_media": 1},
                          headers=_h(local))
    assert r.status_code == 404, r.text

    # TÉMOIN : sur SON propre nœud, tout répond normalement (la garde ne ferme pas tout).
    own_ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_store"].id_player], scene["store"].id_node,
                         name="EvOwn"),
        headers=_h(local))).json()["id_event"]
    assert (await client.get(f"/api/v1/events/{own_ev}", headers=_h(local))).status_code == 200

    # `/events/active` ne doit pas être une porte dérobée vers la branche voisine.
    await client.post(f"/api/v1/events/{sib_ev}/activate", headers=_h(scene["boss"]))
    names = {e["event_name"] for e in
             (await client.get("/api/v1/events/active", headers=_h(local))).json()}
    assert "EvSibDetail" not in names


@pytest.mark.asyncio
async def test_event_targets_and_content_must_exist_in_org(
    client: AsyncClient, scene, db_session: AsyncSession
) -> None:
    """🔴 Rien ne vérifiait l'EXISTENCE des cibles ni du contenu d'un événement.

    Seul le *type* de cible était validé, et la garde de périmètre sort d'emblée pour un
    événement NON gouverné — la majorité. On créait donc un événement visant l'écran d'une
    autre organisation ou un identifiant inexistant : 201, compté, jamais diffusé.
    """
    other = CmsOrganization(org_name="Autre", org_slug=f"autre-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsPlayer(id_org=other.id_org, player_name="P-etranger")
    foreign_pl = CmsPlaylist(id_org=other.id_org, playlist_name="PL-etrangere")
    db_session.add_all([foreign, foreign_pl])
    await db_session.commit()
    await db_session.refresh(foreign)
    await db_session.refresh(foreign_pl)

    classic = scene["classic"]

    # Écran d'une AUTRE organisation → refusé en le nommant.
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [foreign.id_player], None, name="EvX"),
                          headers=_h(classic))
    assert r.status_code == 422, r.text
    assert str(foreign.id_player) in r.json()["detail"]

    # Identifiant inexistant → refusé aussi.
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [999999], None, name="EvY"),
                          headers=_h(classic))
    assert r.status_code == 422, r.text

    # Playlist d'une autre organisation → 404.
    body = _event_body(scene, [scene["p_store"].id_player], None, name="EvZ")
    body["id_playlist"] = foreign_pl.id_playlist
    r = await client.post("/api/v1/events", json=body, headers=_h(classic))
    assert r.status_code == 404, r.text

    # TÉMOIN : la même création avec des identifiants légitimes passe.
    r = await client.post("/api/v1/events",
                          json=_event_body(scene, [scene["p_store"].id_player], None,
                                           name="EvOk"),
                          headers=_h(classic))
    assert r.status_code == 201, r.text
    ok_id = r.json()["id_event"]

    # La MISE À JOUR ne doit pas être la porte d'entrée de ce que la création refuse.
    r = await client.put(f"/api/v1/events/{ok_id}", json={
        "target_config": {"target_type": "player", "target_ids": [foreign.id_player]}},
        headers=_h(classic))
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_site_target_resolves_players_for_force_sync(
    client: AsyncClient, scene, db_session: AsyncSession
) -> None:
    """🔴 La cible `site` était absente du résolveur de force_sync : ensemble VIDE.

    L'événement finissait par diffuser (le matcher player-centrique connaît `site`), mais
    seulement à la resynchronisation suivante : activer une ALERTE ne prévenait personne.
    On teste le résolveur directement — c'est lui qui décide qui est notifié.
    """
    from app.api.v1.endpoints.events import _resolve_player_ids

    id_site = scene["p_store"].id_site
    ids = await _resolve_player_ids(
        db_session, scene["org"].id_org,
        {"target_type": "site", "target_ids": [id_site]},
    )
    assert scene["p_store"].id_player in ids, "un événement ciblant un site ne notifiait personne"

    # TÉMOIN : les autres types continuent de résoudre (non-régression).
    ids = await _resolve_player_ids(
        db_session, scene["org"].id_org,
        {"target_type": "player", "target_ids": [scene["p_store"].id_player]},
    )
    assert ids == {scene["p_store"].id_player}

    # Et un écran d'une AUTRE organisation ne doit jamais sortir du résolveur (on
    # publierait une commande sur son canal Redis).
    other = CmsOrganization(org_name="Autre2", org_slug=f"autre2-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsPlayer(id_org=other.id_org, player_name="P-etranger2")
    db_session.add(foreign)
    await db_session.commit()
    await db_session.refresh(foreign)
    ids = await _resolve_player_ids(
        db_session, scene["org"].id_org,
        {"target_type": "player", "target_ids": [foreign.id_player]},
    )
    assert ids == set()


@pytest.mark.asyncio
async def test_events_edit_permission_exists_and_guards_put(
    client: AsyncClient, scene, db_session: AsyncSession
) -> None:
    """🔴 `PUT /events/{id}` était gardé par `events:trigger`, une permission de DÉCLENCHEMENT.

    Elle réécrit pourtant le contenu diffusé, les cibles, la priorité et l'embargo. La
    permission `events:edit` n'existait pas au catalogue (0 ligne mesurée en production) et
    la migration 0099 croyait à tort l'accorder — un no-op silencieux.

    ⚠️ Garde ANTI-DÉRIVE : la base de test est bâtie par `create_all`, SANS migrations. On
    lit donc la migration 0117 pour vérifier qu'elle crée bien la permission côté base, et
    on vérifie séparément que la route la réclame côté code. Sans ce couple, un test qui
    crée lui-même la permission ne verrait rien — c'est exactement ce qui a masqué le trou.
    """
    import pathlib
    from app.api.v1.endpoints import events as events_module

    migration = (pathlib.Path(events_module.__file__).resolve().parents[4]
                 / "alembic/versions/0117_events_edit_permission.py").read_text(encoding="utf-8")
    assert "'events', 'edit'" in migration

    src = pathlib.Path(events_module.__file__).read_text(encoding="utf-8")
    assert 'require_permission("events", "edit")' in src, "PUT n'exige pas events:edit"

    # Comportement : un compte qui détient `edit` édite bien (les comptes de test l'ont via
    # _PERMS) — la bascule ne casse pas le geste nominal.
    ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_store"].id_player], None, name="EvPerm"),
        headers=_h(scene["classic"]))).json()["id_event"]
    r = await client.put(f"/api/v1/events/{ev}", json={"event_name": "Renomme"},
                         headers=_h(scene["classic"]))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_event_and_vod_mutations_are_audited(
    client: AsyncClient, scene, db_session: AsyncSession
) -> None:
    """🔴 AUCUNE trace : 0 ligne d'audit pour un événement, sur 859 mesurées en production.

    Ni la création, ni la modification, ni la suppression, ni surtout la MISE À L'ANTENNE.
    Côté VOD, seul le déclenchement était journalisé, jamais le CRUD — basculer une config
    sur un SITE ENTIER était donc invisible après coup.
    """
    from app.models.audit_log import CmsAuditLog

    boss = scene["boss"]
    ev = (await client.post(
        "/api/v1/events",
        json=_event_body(scene, [scene["p_store"].id_player], None, name="EvAudit"),
        headers=_h(boss))).json()["id_event"]
    await client.put(f"/api/v1/events/{ev}", json={"event_name": "EvAudit2"}, headers=_h(boss))
    await client.post(f"/api/v1/events/{ev}/activate", headers=_h(boss))
    await client.post(f"/api/v1/events/{ev}/deactivate", headers=_h(boss))
    await client.post(f"/api/v1/events/{ev}/cancel", headers=_h(boss))
    await client.delete(f"/api/v1/events/{ev}", headers=_h(boss))

    actions = set((await db_session.execute(
        select(CmsAuditLog.action).where(
            CmsAuditLog.resource_type == "event", CmsAuditLog.resource_id == str(ev)
        )
    )).scalars().all())
    assert {"create", "update", "activate", "deactivate", "cancel", "delete"} <= actions, actions

    vid = (await client.post("/api/v1/vod", json={
        "vod_name": "VodAudit", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_store"].id_player]}, headers=_h(boss))).json()["id_vod"]
    await client.put(f"/api/v1/vod/{vid}", json={"vod_name": "VodAudit2"}, headers=_h(boss))
    await client.delete(f"/api/v1/vod/{vid}", headers=_h(boss))
    actions = set((await db_session.execute(
        select(CmsAuditLog.action).where(
            CmsAuditLog.resource_type == "vod_config", CmsAuditLog.resource_id == str(vid)
        )
    )).scalars().all())
    assert {"create", "update", "delete"} <= actions, actions


@pytest.mark.asyncio
async def test_vod_updated_at_moves_on_update(client: AsyncClient, scene) -> None:
    """🔴 `updated_at` d'une config VOD ne bougeait JAMAIS (0 sur 4 mesurées en production).

    `update_vod_config` ne l'écrivait pas et le modèle n'avait pas d'`onupdate` — alors que
    le champ est exposé dans la réponse. Même défaut que les playlists (0/20) et les
    templates (0/8), même correctif : au MODÈLE.
    """
    boss = scene["boss"]
    created = (await client.post("/api/v1/vod", json={
        "vod_name": "VodDate", "id_medias": [], "target_mode": "players",
        "id_players": [scene["p_store"].id_player]}, headers=_h(boss))).json()
    updated = (await client.put(f"/api/v1/vod/{created['id_vod']}",
                                json={"vod_name": "VodDate2"}, headers=_h(boss))).json()
    assert updated["updated_at"] > created["updated_at"], (
        created["updated_at"], updated["updated_at"])
