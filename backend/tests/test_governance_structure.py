"""Gouvernance §XVIII — cloisonnement de la STRUCTURE (N1) et du DÉTACHEMENT (N2).

Audit du 2026-07-27 (3 comptes réels sur la prod) :
  · N1 — les routes de structure (créer/renommer/supprimer un nœud, nommer un admin,
    poser une assignation) n'étaient gardées que par la PERMISSION RBAC : un porteur de
    `governance:delegate` se nommait admin de la RACINE (201) et passait de 403 à 200
    sur le contenu national. Ici : ces routes exigent `user_can_edit_node(nœud visé)`,
    et la création d'un nœud RACINE est réservée à l'org-admin.
  · N2 — `id_governance_node → null` était accepté par l'admin du nœud lui-même
    (`user_can_edit_node(None)` = autorisé par contrat) : une playlist sortait de la
    modération, un programme quittait le nœud EN GARDANT SES CIBLES. Ici : détacher est
    réservé à un admin d'un ancêtre STRICT ou à l'org-admin — playlists, programmes ET
    médias, via le même helper `user_can_detach_from_node`.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.governance import CmsGovernanceNode, CmsGovernanceNodeAdmin
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.governance_access import user_can_detach_from_node

_PERMS = [
    ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    ("playlists", "create"), ("playlists", "read"), ("playlists", "edit"),
    ("schedules", "create"), ("schedules", "read"), ("schedules", "edit"),
    ("media", "read"), ("media", "edit"),
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovS", org_slug=f"govs-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"s-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_S_{uid}", label="S", is_system=False)
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
    await db.commit()
    await db.refresh(user)
    return user


async def _mk_org_admin(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    """Org-admin de test : rôle CMS_ORG_ADMIN (bypass gouvernance) + permissions RBAC.

    ⚠️ `require_permission` ne bypasse QUE le super-admin — en prod l'org-admin porte les
    permissions via le seed ; ici on les lui donne par le même rôle custom que les autres.
    """
    user = await _mk_user(db, org)
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


async def _token(client: AsyncClient, user: CmsUser) -> str:
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _mk_node(db: AsyncSession, org, name, parent=None):
    n = CmsGovernanceNode(
        id_org=org.id_org, parent_id=parent.id_node if parent else None,
        node_name=name, node_level=(parent.node_level + 1) if parent else 0,
        node_type="store" if parent else "national",
        requires_approval=False, path="",
    )
    db.add(n)
    await db.flush()
    n.path = f"{parent.path}.{n.id_node}" if parent else str(n.id_node)
    await db.commit()
    await db.refresh(n)
    return n


async def _admin_of(db: AsyncSession, node, user) -> None:
    db.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=user.id_user))
    await db.commit()


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org, client):
    """national → dpt → site. nat_admin admine la racine ; dpt_admin admine le département."""
    national = await _mk_node(db_session, org, "National")
    dpt = await _mk_node(db_session, org, "Dpt", parent=national)
    site = await _mk_node(db_session, org, "Site", parent=dpt)
    nat_admin = await _mk_user(db_session, org)
    dpt_admin = await _mk_user(db_session, org)
    site_admin = await _mk_user(db_session, org)
    await _admin_of(db_session, national, nat_admin)
    await _admin_of(db_session, dpt, dpt_admin)
    await _admin_of(db_session, site, site_admin)
    org_admin = await _mk_org_admin(db_session, org)
    return {
        "org": org, "national": national, "dpt": dpt, "site": site,
        "nat_admin": nat_admin, "nat_tok": await _token(client, nat_admin),
        "dpt_admin": dpt_admin, "dpt_tok": await _token(client, dpt_admin),
        "site_admin": site_admin, "site_tok": await _token(client, site_admin),
        "org_admin": org_admin,
        "oa_tok": create_access_token(org_admin.id_user),
    }


# ── N1 — escalade par les routes de structure ────────────────────────────────

@pytest.mark.asyncio
async def test_n1_delegate_cannot_seize_ancestor_or_sibling(client: AsyncClient, scene) -> None:
    """Le scénario d'escalade mesuré le 2026-07-27 : le DPT se nomme admin de la RACINE."""
    nat, dpt = scene["national"], scene["dpt"]

    # Se nommer sur la racine → 403 (avant correctif : 201, puis contenu national éditable).
    r = await client.post(
        f"/api/v1/governance/nodes/{nat.id_node}/admins",
        json={"id_user": scene["dpt_admin"].id_user}, headers=_h(scene["dpt_tok"]),
    )
    assert r.status_code == 403, r.text

    # Retirer l'admin de la racine (sabotage vers le haut) → 403 aussi.
    r = await client.request(
        "DELETE", f"/api/v1/governance/nodes/{nat.id_node}/admins",
        json={"id_user": scene["nat_admin"].id_user}, headers=_h(scene["dpt_tok"]),
    )
    assert r.status_code == 403, r.text

    # Le contenu national reste fermé au DPT (la porte n'a pas été franchie).
    r = await client.post("/api/v1/playlists",
                          json={"playlist_name": "Nat PL", "id_governance_node": nat.id_node},
                          headers=_h(scene["nat_tok"]))
    assert r.status_code == 201, r.text
    nat_pl = r.json()["id_playlist"]
    r = await client.put(f"/api/v1/playlists/{nat_pl}",
                         json={"description": "hack"}, headers=_h(scene["dpt_tok"]))
    assert r.status_code == 403

    # Nœud frère du DPT : même refus.
    sibling = await _mk_node_via(client, scene["oa_tok"], "Dpt-02", parent_id=nat.id_node)
    r = await client.post(
        f"/api/v1/governance/nodes/{sibling}/admins",
        json={"id_user": scene["dpt_admin"].id_user}, headers=_h(scene["dpt_tok"]),
    )
    assert r.status_code == 403, r.text
    # ... alors que dans SON sous-arbre la délégation reste ouverte.
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['site'].id_node}/admins",
        json={"id_user": scene["dpt_admin"].id_user}, headers=_h(scene["dpt_tok"]),
    )
    assert r.status_code == 201, r.text


async def _mk_node_via(client: AsyncClient, tok: str, name: str, parent_id: int | None) -> int:
    body = {"node_name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = await client.post("/api/v1/governance/nodes", json=body, headers=_h(tok))
    assert r.status_code == 201, r.text
    return r.json()["id_node"]


@pytest.mark.asyncio
async def test_n1_node_crud_scoped_to_subtree(client: AsyncClient, scene) -> None:
    nat, dpt = scene["national"], scene["dpt"]
    dpt_h = _h(scene["dpt_tok"])

    # Créer sous son nœud → 201 ; sous un ancêtre → 403 ; une racine → 403 (org-admin seul).
    r = await client.post("/api/v1/governance/nodes",
                          json={"node_name": "Site-02", "parent_id": dpt.id_node}, headers=dpt_h)
    assert r.status_code == 201, r.text
    child = r.json()["id_node"]
    r = await client.post("/api/v1/governance/nodes",
                          json={"node_name": "Dpt-X", "parent_id": nat.id_node}, headers=dpt_h)
    assert r.status_code == 403, r.text
    r = await client.post("/api/v1/governance/nodes",
                          json={"node_name": "Racine pirate"}, headers=dpt_h)
    assert r.status_code == 403, r.text
    r = await client.post("/api/v1/governance/nodes",
                          json={"node_name": "Racine légitime"}, headers=_h(scene["oa_tok"]))
    assert r.status_code == 201, r.text

    # Renommer : son sous-arbre → 200 ; l'ancêtre → 403.
    r = await client.put(f"/api/v1/governance/nodes/{child}",
                         json={"node_name": "Site-02 bis"}, headers=dpt_h)
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/v1/governance/nodes/{nat.id_node}",
                         json={"node_name": "Pwn"}, headers=dpt_h)
    assert r.status_code == 403, r.text

    # Supprimer : l'ancêtre → 403 ; son sous-arbre → 204.
    r = await client.delete(f"/api/v1/governance/nodes/{nat.id_node}", headers=dpt_h)
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/governance/nodes/{child}", headers=dpt_h)
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_n1_assignments_scoped_to_subtree(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    from app.models.organization import CmsSite
    from app.models.player import CmsPlayer

    site_row = CmsSite(id_org=scene["org"].id_org, site_name="Mag")
    db_session.add(site_row)
    await db_session.flush()
    # Écran neuf, encore hors gouvernance : tout admin de nœud peut le rattacher (G3
    # révisée). Ce test-ci porte sur le cloisonnement de la ROUTE (N1) ; le périmètre de
    # la CIBLE est couvert par `test_governance_perimeter.py`.
    player = CmsPlayer(
        id_org=scene["org"].id_org, id_site=site_row.id_site, player_name="P1",
    )
    db_session.add(player)
    await db_session.commit()

    dpt_h = _h(scene["dpt_tok"])
    # Poser une assignation sur la RACINE → 403 (avant : 201, le périmètre national bougeait).
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['national'].id_node}/assignments",
        json={"target_type": "player", "target_id": player.id_player}, headers=dpt_h,
    )
    assert r.status_code == 403, r.text
    # Sur SON nœud → 201, puis retrait par lui → 204, par un étranger au sous-arbre → 403.
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['dpt'].id_node}/assignments",
        json={"target_type": "player", "target_id": player.id_player}, headers=dpt_h,
    )
    assert r.status_code == 201, r.text
    r = await client.request(
        "DELETE", f"/api/v1/governance/nodes/{scene['dpt'].id_node}/assignments",
        json={"target_type": "player", "target_id": player.id_player},
        headers=_h(scene["site_tok"]),
    )
    assert r.status_code == 403, r.text
    r = await client.request(
        "DELETE", f"/api/v1/governance/nodes/{scene['dpt'].id_node}/assignments",
        json={"target_type": "player", "target_id": player.id_player}, headers=dpt_h,
    )
    assert r.status_code == 204, r.text


# ── N6 / N7 — fuites de STRUCTURE et d'ANNUAIRE (phase 5) ────────────────────

@pytest.mark.asyncio
async def test_n7_tree_and_node_detail_are_scoped(client: AsyncClient, scene) -> None:
    """D6 protégeait le CONTENU, pas la STRUCTURE : l'arbre rendait tous les nœuds."""
    nat, dpt, site = scene["national"], scene["dpt"], scene["site"]
    sibling = await _mk_node_via(client, scene["oa_tok"], "Dpt-02", parent_id=nat.id_node)

    # Le DPT voit sa branche + ses ancêtres, jamais le département voisin.
    ids = {n["id_node"] for n in
           (await client.get("/api/v1/governance/nodes", headers=_h(scene["dpt_tok"]))).json()}
    assert ids == {nat.id_node, dpt.id_node, site.id_node}
    assert sibling not in ids

    # Le détail d'un nœud étranger : 404 (avant : 200, avec ses règles et ses admins).
    r = await client.get(f"/api/v1/governance/nodes/{sibling}", headers=_h(scene["dpt_tok"]))
    assert r.status_code == 404, r.text
    # …et ses surfaces satellites suivent la même règle.
    for path in ("/players", "/coverage", "/rules", "/admins", "/subtree"):
        r = await client.get(f"/api/v1/governance/nodes/{sibling}{path}",
                             headers=_h(scene["dpt_tok"]))
        assert r.status_code == 404, f"{path} → {r.status_code}"

    # L'ancêtre reste lisible (comprendre ce qui passe au-dessus de soi fait partie du métier).
    assert (await client.get(f"/api/v1/governance/nodes/{nat.id_node}",
                             headers=_h(scene["dpt_tok"]))).status_code == 200
    # L'org-admin voit tout l'arbre.
    ids = {n["id_node"] for n in
           (await client.get("/api/v1/governance/nodes", headers=_h(scene["oa_tok"]))).json()}
    assert sibling in ids


@pytest.mark.asyncio
async def test_n6_admin_candidates_no_longer_leaks_the_directory(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """L'annuaire complet (e-mails, rôles) était rendu à un admin de magasin."""
    r = await client.get("/api/v1/governance/admin-candidates", headers=_h(scene["site_tok"]))
    assert r.status_code == 200, r.text
    emails = {u["email"] for u in r.json()}
    # Il se voit lui-même (il doit pouvoir se déléguer un nœud qu'il crée)…
    assert scene["site_admin"].email in emails
    # …mais PAS le personnel d'une autre branche : c'est la fuite qui comptait.
    assert scene["nat_admin"].email not in emails
    assert scene["dpt_admin"].email not in emails

    # L'org-admin, lui, voit tout l'annuaire : c'est par lui que passe la 1ʳᵉ nomination.
    r = await client.get("/api/v1/governance/admin-candidates", headers=_h(scene["oa_tok"]))
    emails = {u["email"] for u in r.json()}
    assert {scene["nat_admin"].email, scene["site_admin"].email} <= emails

    # Un admin de nœud voit les gens DÉJÀ dans son sous-arbre (pour les retirer/compléter),
    # jamais ceux d'une branche supérieure ou voisine.
    r = await client.get("/api/v1/governance/admin-candidates", headers=_h(scene["dpt_tok"]))
    emails = {u["email"] for u in r.json()}
    assert {scene["dpt_admin"].email, scene["site_admin"].email} <= emails
    assert scene["nat_admin"].email not in emails

    # …et il voit les comptes ENCORE RATTACHÉS À AUCUN nœud : sans eux, il ne pourrait
    # nommer personne de nouveau et la délégation n'aurait plus de sens (pendant humain de
    # la porte de rattachement des écrans orphelins, décision Ed du 2026-07-27).
    newcomer = await _mk_user(db_session, scene["org"])
    await db_session.commit()
    r = await client.get("/api/v1/governance/admin-candidates", headers=_h(scene["dpt_tok"]))
    assert newcomer.email in {u["email"] for u in r.json()}


# ── N2 — détachement (id_governance_node → null) ─────────────────────────────

@pytest.mark.asyncio
async def test_n2_service_detach_rules(db_session: AsyncSession, scene) -> None:
    dpt, site = scene["dpt"], scene["site"]
    # L'admin du nœud lui-même NE détache PAS ; l'ancêtre strict et l'org-admin, si.
    assert await user_can_detach_from_node(db_session, scene["site_admin"], site.id_node) is False
    assert await user_can_detach_from_node(db_session, scene["dpt_admin"], site.id_node) is True
    assert await user_can_detach_from_node(db_session, scene["org_admin"], site.id_node) is True
    # Racine : personne d'autre que l'org-admin.
    assert await user_can_detach_from_node(
        db_session, scene["nat_admin"], scene["national"].id_node) is False
    assert await user_can_detach_from_node(
        db_session, scene["org_admin"], scene["national"].id_node) is True
    # Déjà détaché = no-op autorisé.
    assert await user_can_detach_from_node(db_session, scene["site_admin"], None) is True
    # Sans rapport : dpt_admin ne détache pas du nœud national.
    assert await user_can_detach_from_node(
        db_session, scene["dpt_admin"], scene["national"].id_node) is False


@pytest.mark.asyncio
async def test_n2_playlist_detach_requires_strict_ancestor(client: AsyncClient, scene) -> None:
    site = scene["site"]
    r = await client.post("/api/v1/playlists",
                          json={"playlist_name": "Gov PL", "id_governance_node": site.id_node},
                          headers=_h(scene["site_tok"]))
    assert r.status_code == 201, r.text
    pl = r.json()["id_playlist"]

    # L'admin du nœud sortirait sa playlist de la modération → 403 (avant : 200).
    r = await client.put(f"/api/v1/playlists/{pl}",
                         json={"id_governance_node": None}, headers=_h(scene["site_tok"]))
    assert r.status_code == 403, r.text

    # L'ancêtre strict détache → 200, puis re-rattache (sinon l'état fuit sur les suivants).
    r = await client.put(f"/api/v1/playlists/{pl}",
                         json={"id_governance_node": None}, headers=_h(scene["dpt_tok"]))
    assert r.status_code == 200, r.text
    assert r.json()["id_governance_node"] is None
    r = await client.put(f"/api/v1/playlists/{pl}",
                         json={"id_governance_node": site.id_node}, headers=_h(scene["dpt_tok"]))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_n2_schedule_detach_requires_strict_ancestor(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    site = scene["site"]
    pl = CmsPlaylist(id_org=scene["org"].id_org, playlist_name="Sched PL")
    db_session.add(pl)
    await db_session.commit()

    r = await client.post("/api/v1/schedules", json={
        "schedule_name": "Gov Sched", "schedule_kind": "content",
        "id_playlist": pl.id_playlist, "id_governance_node": site.id_node,
        "rules": [{"rule_type": "always"}], "targets": [],
    }, headers=_h(scene["site_tok"]))
    assert r.status_code == 201, r.text
    sched = r.json()["id_schedule"]

    # Le programme quitterait le nœud EN GARDANT SES CIBLES → 403 (avant : 200).
    r = await client.put(f"/api/v1/schedules/{sched}",
                         json={"id_governance_node": None}, headers=_h(scene["site_tok"]))
    assert r.status_code == 403, r.text

    # Org-admin détache → 200.
    r = await client.put(f"/api/v1/schedules/{sched}",
                         json={"id_governance_node": None}, headers=_h(scene["oa_tok"]))
    assert r.status_code == 200, r.text
    assert r.json()["id_governance_node"] is None


@pytest.mark.asyncio
async def test_n2_media_detach_requires_strict_ancestor(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    site = scene["site"]
    uid = uuid.uuid4().hex[:6]
    m = CmsMedia(
        id_org=scene["org"].id_org, media_name=f"m-{uid}", media_type="image",
        storage_key=f"k/{uid}", checksum_sha256=uid * 4,
        id_governance_node=site.id_node,
    )
    db_session.add(m)
    await db_session.commit()

    r = await client.patch(f"/api/v1/media/{m.id_media}/governance-node",
                           json={"id_governance_node": None}, headers=_h(scene["site_tok"]))
    assert r.status_code == 403, r.text
    r = await client.patch(f"/api/v1/media/{m.id_media}/governance-node",
                           json={"id_governance_node": None}, headers=_h(scene["dpt_tok"]))
    assert r.status_code == 200, r.text
    assert r.json()["id_governance_node"] is None
