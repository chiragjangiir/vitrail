"""Gouvernance §XVIII — périmètre des ÉCRANS par utilisateur (N8 / G1 / G2, audit 2026-07-27).

Décisions d'Ed (validées le 2026-07-27) :
  · **G1** — le périmètre d'un admin de nœud = l'union de ses SOUS-ARBRES (les affectations
    vivent sur les nœuds bas, la remontée est automatique). Aucun admin de nœud ne voit un
    écran hors gouvernance, ni un écran d'une autre racine. Constat N8 : les 3 comptes de
    l'audit voyaient les 8 écrans de l'org pour un périmètre réel de 4.
  · **G2** — l'admin d'un nœud RACINE voit EN PLUS les écrans ORPHELINS (rattachés à aucun
    nœud), uniquement sur le sélecteur de l'écran Gouvernance, à seule fin de les rattacher.
    Jamais dans /players.
  · Un utilisateur SANS nœud administré (rôles classiques) n'est PAS filtré — la sémantique
    de périmètre portée par le rôle, c'est G4 (Phase 3).
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
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.governance_scope import orphan_players, user_player_scope

_PERMS = [
    ("players", "read"),
    ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    # `reports:read` ouvre le NOC et la carte du parc — les 2 surfaces du Dashboard qui
    # ignoraient le périmètre jusqu'à l'audit du 2026-07-28. Cette permission est portée
    # par 5 rôles système (dont CMS_VIEWER) : un responsable de nœud à qui on ajoute
    # « Report Viewer » lisait l'inventaire COMPLET du parc.
    ("reports", "read"),
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovP", org_slug=f"govp-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization, *, org_admin: bool = False) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"p-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_P_{uid}", label="P", is_system=False)
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
    await db.flush()
    return n


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org):
    """Arbre A : national → dpt → site. Arbre B : racine2 (autre enseigne).

    Players : p_dpt (assigné au dpt), p_site (assigné au site), p_other (assigné à
    racine2), p_orphan (aucun nœud). nat/dpt/site_admin administrent leur nœud.
    """
    site_row = CmsSite(id_org=org.id_org, site_name="Mag")
    db_session.add(site_row)
    await db_session.flush()

    def _player(name: str) -> CmsPlayer:
        p = CmsPlayer(id_org=org.id_org, id_site=site_row.id_site, player_name=name)
        db_session.add(p)
        return p

    p_dpt, p_site, p_other, p_orphan = (
        _player("P-dpt"), _player("P-site"), _player("P-other"), _player("P-orphan"))
    await db_session.flush()

    national = await _mk_node(db_session, org, "National")
    dpt = await _mk_node(db_session, org, "Dpt", parent=national)
    site = await _mk_node(db_session, org, "Site", parent=dpt)
    root2 = await _mk_node(db_session, org, "Racine2")
    for node, player in ((dpt, p_dpt), (site, p_site), (root2, p_other)):
        db_session.add(CmsGovernanceAssignment(
            id_node=node.id_node, target_type="player", target_id=player.id_player))

    nat_admin = await _mk_user(db_session, org)
    dpt_admin = await _mk_user(db_session, org)
    site_admin = await _mk_user(db_session, org)
    classic = await _mk_user(db_session, org)          # players:read, AUCUN nœud
    org_admin = await _mk_user(db_session, org, org_admin=True)
    for node, user in ((national, nat_admin), (dpt, dpt_admin), (site, site_admin)):
        db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=user.id_user))
    await db_session.commit()

    return {
        "org": org, "national": national, "dpt": dpt, "site": site, "root2": root2,
        "p_dpt": p_dpt, "p_site": p_site, "p_other": p_other, "p_orphan": p_orphan,
        "nat_admin": nat_admin, "dpt_admin": dpt_admin, "site_admin": site_admin,
        "classic": classic, "org_admin": org_admin,
    }


# ── Service ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_scope_and_orphans(db_session: AsyncSession, scene) -> None:
    ids = {k: scene[k].id_player for k in ("p_dpt", "p_site", "p_other", "p_orphan")}

    # G1 : union du sous-arbre, jamais les orphelins ni l'autre racine.
    assert await user_player_scope(db_session, scene["nat_admin"]) == {ids["p_dpt"], ids["p_site"]}
    assert await user_player_scope(db_session, scene["dpt_admin"]) == {ids["p_dpt"], ids["p_site"]}
    assert await user_player_scope(db_session, scene["site_admin"]) == {ids["p_site"]}
    # Rôle classique (aucun nœud) et org-admin : pas de restriction.
    assert await user_player_scope(db_session, scene["classic"]) is None
    assert await user_player_scope(db_session, scene["org_admin"]) is None
    # G2 : l'orphelin est bien détecté comme tel.
    assert await orphan_players(db_session, scene["org"].id_org) == {ids["p_orphan"]}


# ── /players ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_players_list_is_scoped_for_node_admins(client: AsyncClient, scene) -> None:
    async def _names(user) -> set[str]:
        r = await client.get("/api/v1/players/", headers=_h(user))
        assert r.status_code == 200, r.text
        return {p["player_name"] for p in r.json()}

    # N8 rejoué : avant le correctif, chacun voyait les 4 écrans de l'org.
    assert await _names(scene["nat_admin"]) == {"P-dpt", "P-site"}
    assert await _names(scene["site_admin"]) == {"P-site"}
    # Rôles classiques et org-admin : inchangés.
    assert await _names(scene["classic"]) == {"P-dpt", "P-site", "P-other", "P-orphan"}
    assert await _names(scene["org_admin"]) == {"P-dpt", "P-site", "P-other", "P-orphan"}


@pytest.mark.asyncio
async def test_player_detail_out_of_scope_is_404(client: AsyncClient, scene) -> None:
    r = await client.get(f"/api/v1/players/{scene['p_dpt'].id_player}",
                         headers=_h(scene["site_admin"]))
    assert r.status_code == 404, r.text  # comme un cross-tenant : il n'existe pas pour lui
    r = await client.get(f"/api/v1/players/{scene['p_site'].id_player}",
                         headers=_h(scene["site_admin"]))
    assert r.status_code == 200, r.text
    # L'aperçu compilé (colonne 3 de l'écran Gouvernance) suit la même règle.
    r = await client.get(f"/api/v1/players/{scene['p_orphan'].id_player}/compiled-schedule",
                         headers=_h(scene["site_admin"]))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_search_players_scoped(client: AsyncClient, scene) -> None:
    r = await client.get("/api/v1/search", params={"q": "P-dpt"},
                         headers=_h(scene["site_admin"]))
    assert r.status_code == 200, r.text
    hits = [i["label"] for g in r.json()["groups"] if g["kind"] == "player" for i in g["items"]]
    assert hits == []  # hors périmètre : la barre globale ne le révèle pas


@pytest.mark.asyncio
async def test_player_groups_scoped_to_perimeter(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """Les groupes (cibles de programmes) ne doivent pas faire fuir le parc entier."""
    from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember

    org = scene["org"]
    g_in = CmsPlayerGroup(id_org=org.id_org, group_name=f"G-in-{uuid.uuid4().hex[:6]}",
                          group_type="content")
    g_out = CmsPlayerGroup(id_org=org.id_org, group_name=f"G-out-{uuid.uuid4().hex[:6]}",
                           group_type="content")
    db_session.add_all([g_in, g_out])
    await db_session.flush()
    # g_in mélange un écran du périmètre du site_admin et un écran d'ailleurs.
    db_session.add_all([
        CmsPlayerGroupMember(id_group=g_in.id_group, id_player=scene["p_site"].id_player),
        CmsPlayerGroupMember(id_group=g_in.id_group, id_player=scene["p_other"].id_player),
        CmsPlayerGroupMember(id_group=g_out.id_group, id_player=scene["p_other"].id_player),
    ])
    await db_session.commit()

    r = await client.get("/api/v1/player-groups/", headers=_h(scene["site_admin"]))
    assert r.status_code == 200, r.text
    by_name = {g["group_name"]: g for g in r.json()}
    # Le groupe étranger disparaît ; le groupe mixte ne montre que le membre du périmètre.
    assert g_out.group_name not in by_name
    assert by_name[g_in.group_name]["player_ids"] == [scene["p_site"].id_player]

    r = await client.get(f"/api/v1/player-groups/{g_in.id_group}/players",
                         headers=_h(scene["site_admin"]))
    assert {p["player_name"] for p in r.json()} == {"P-site"}

    # L'org-admin voit tout, inchangé.
    r = await client.get("/api/v1/player-groups/", headers=_h(scene["org_admin"]))
    by_name = {g["group_name"]: g for g in r.json()}
    assert set(by_name[g_in.group_name]["player_ids"]) == {
        scene["p_site"].id_player, scene["p_other"].id_player}


# ── Porte de rattachement (G2) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_attachable_players_any_node_admin_sees_orphans(client: AsyncClient, scene) -> None:
    """G3 RÉVISÉE (Ed, 2026-07-27 2ᵉ passe) : la porte n'est plus réservée à la racine.

    Un responsable de magasin installe un écran neuf et le rattache sur place ; réserver
    ce geste au siège transformait chaque installation en demande. L'écran gouverné
    AILLEURS, lui, reste invisible — c'est le périmètre qui protège, pas le niveau.

    La liste vient de `/governance/targets/search` (R4) : une seule source pour la
    sélection, qui étiquette au passage les écrans encore hors gouvernance.
    """
    async def _fetch(user):
        r = await client.get("/api/v1/governance/targets/search",
                             params={"q": "P-", "types": "player"}, headers=_h(user))
        assert r.status_code == 200, r.text
        return {p["name"]: p["orphan"] for p in r.json()}

    expected = {"P-dpt": False, "P-site": False, "P-orphan": True}
    assert await _fetch(scene["nat_admin"]) == expected
    assert await _fetch(scene["dpt_admin"]) == expected
    # Le magasin ne voit QUE son écran + les orphelins (pas celui du département voisin).
    assert await _fetch(scene["site_admin"]) == {"P-site": False, "P-orphan": True}
    # Org-admin : tout le parc, orphelins étiquetés.
    assert await _fetch(scene["org_admin"]) == {
        "P-dpt": False, "P-site": False, "P-other": False, "P-orphan": True}


@pytest.mark.asyncio
async def test_assignment_targets_stay_inside_user_scope(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """Rattacher élargit un périmètre : la cible doit rester dans la portée de l'auteur."""
    # G3 révisée : un admin de nœud INTERMÉDIAIRE rattache un écran neuf lui-même → 201.
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['dpt'].id_node}/assignments",
        json={"target_type": "player", "target_id": scene["p_orphan"].id_player},
        headers=_h(scene["dpt_admin"]),
    )
    assert r.status_code == 201, r.text
    # …et l'écran cesse aussitôt d'être orphelin (il ne se re-rattache plus ailleurs).
    r = await client.get("/api/v1/governance/targets/search",
                         params={"q": "P-", "types": "player"}, headers=_h(scene["site_admin"]))
    assert "P-orphan" not in {p["name"] for p in r.json()}

    # Un écran gouverné dans une AUTRE racine reste hors de portée, même pour la racine.
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['dpt'].id_node}/assignments",
        json={"target_type": "player", "target_id": scene["p_other"].id_player},
        headers=_h(scene["nat_admin"]),
    )
    assert r.status_code == 422, r.text
    assert "P-other" in r.json()["detail"]

    # L'org-admin, lui, n'est pas contraint (c'est lui qui recompose les périmètres).
    r = await client.post(
        f"/api/v1/governance/nodes/{scene['root2'].id_node}/assignments",
        json={"target_type": "player", "target_id": scene["p_site"].id_player},
        headers=_h(scene["org_admin"]),
    )
    assert r.status_code == 201, r.text


# ── Dashboard : NOC + carte du parc (audit du 2026-07-28) ────────────────────
#
# Ces deux surfaces sont gatées `reports:read` et NON `players:read` : elles avaient donc
# échappé au correctif N8 de la Phase 2, qui n'avait couvert que `/players/`. Mesuré sur la
# production : un admin de nœud au périmètre de 5 écrans en recevait 8 par `/analytics/noc`
# (nom, OS, version, site, disque) et les 2 sites — coordonnées GPS comprises — par
# `/analytics/geo`, pendant que `/players/` répondait correctement 5.

@pytest.mark.asyncio
async def test_noc_dashboard_is_scoped_for_node_admins(client: AsyncClient, scene) -> None:
    async def _noc(user) -> tuple[set[str], int]:
        r = await client.get("/api/v1/analytics/noc", headers=_h(user))
        assert r.status_code == 200, r.text
        body = r.json()
        return {row["player_name"] for row in body["rows"]}, body["total"]

    # Le compteur doit suivre le périmètre, pas seulement la liste : afficher « 4 écrans »
    # au-dessus d'une table qui n'en montre qu'un serait un autre mensonge.
    assert await _noc(scene["site_admin"]) == ({"P-site"}, 1)
    assert await _noc(scene["nat_admin"]) == ({"P-dpt", "P-site"}, 2)
    # Rôles classiques et org-admin : inchangés (aucun nœud administré → aucune restriction).
    assert await _noc(scene["classic"]) == ({"P-dpt", "P-site", "P-other", "P-orphan"}, 4)
    assert await _noc(scene["org_admin"]) == ({"P-dpt", "P-site", "P-other", "P-orphan"}, 4)


@pytest.mark.asyncio
async def test_geo_map_hides_sites_outside_perimeter(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """Décision d'Ed : hors périmètre, il ne voit RIEN — le site DISPARAÎT de la carte.

    Pas « à 0 écran » : un site affiché à zéro révélerait quand même son existence, son nom
    et ses coordonnées. Les compteurs d'un site visible ne portent que sur SES écrans.
    """
    org = scene["org"]
    # Le site historique reçoit des coordonnées ; un 2e site accueille l'écran de l'autre racine.
    mag = (await db_session.execute(
        select(CmsSite).where(CmsSite.id_org == org.id_org, CmsSite.site_name == "Mag")
    )).scalar_one()
    mag.latitude, mag.longitude = 48.85, 2.35
    ailleurs = CmsSite(id_org=org.id_org, site_name="Ailleurs", latitude=44.84, longitude=-0.57)
    db_session.add(ailleurs)
    await db_session.flush()
    scene["p_other"].id_site = ailleurs.id_site
    await db_session.commit()

    async def _geo(user) -> dict:
        r = await client.get("/api/v1/analytics/geo", headers=_h(user))
        assert r.status_code == 200, r.text
        return {s["site_name"]: s["players_total"] for s in r.json()["sites"]}

    # L'admin du site ne voit que son propre magasin, avec le seul écran qui lui revient
    # (« Mag » héberge aussi P-dpt, P-orphan… qui ne sont pas dans son périmètre).
    assert await _geo(scene["site_admin"]) == {"Mag": 1}
    # « Ailleurs » n'existe pour personne d'autre que l'org-admin et les rôles classiques.
    assert "Ailleurs" not in await _geo(scene["nat_admin"])
    assert await _geo(scene["org_admin"]) == {"Mag": 3, "Ailleurs": 1}
    assert await _geo(scene["classic"]) == {"Mag": 3, "Ailleurs": 1}


@pytest.mark.asyncio
async def test_noc_row_cap_is_announced_and_counters_stay_exact(
    client: AsyncClient, scene, monkeypatch
) -> None:
    """Le plafond de lignes ne doit JAMAIS fausser un compteur, et doit se signaler.

    Avant : `total = len(rows)` APRÈS un `LIMIT 2000` — au-delà, le nombre d'écrans annoncé
    était faux, sans le moindre signal. On abaisse le plafond pour le prouver sans monter
    un parc de 2000 écrans.
    """
    from app.api.v1.endpoints import analytics as analytics_ep

    monkeypatch.setattr(analytics_ep, "_NOC_ROW_CAP", 2)
    r = await client.get("/api/v1/analytics/noc", headers=_h(scene["org_admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 2          # la charge utile est bien plafonnée…
    assert body["total"] == 4              # …mais le parc réel est annoncé juste…
    assert body["online"] + body["offline"] + body["warning"] + body["maintenance"] == 4
    assert body["rows_truncated"] is True  # …et la troncature est DITE.
