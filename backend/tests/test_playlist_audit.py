"""Audit du menu Playlists (2026-07-29) — les défauts mesurés sur la prod.

Chaque test a été prouvé ROUGE sur le code d'origine :

  · `simulate-timeline` rendait la timeline COMPLÈTE (1789 segments, noms des médias
    compris) d'une playlist d'un nœud frère que le détail refusait en 404 ;
  · `GET /items/{id}/rules` répondait 200 sur cette même playlist ;
  · `POST /items {id_child_playlist}` acceptait (201) une sous-playlist invisible — le
    motif « affectation croisée non gardée » (même famille que le défaut trouvé par Ed
    le 27/07 sur les programmes, et que le template refermé le 28/07) ;
  · `POST /items {id_media}` acceptait un média SUPPRIMÉ (l'ajout en LOT, lui, le
    filtrait déjà — l'asymétrie est ce qui a mis sur la piste) ;
  · `updated_at` ne bougeait jamais (0 playlist sur 20 en prod) ;
  · aucune mutation directe n'était tracée dans `cms_audit_log`.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.audit_log import CmsAuditLog
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

_PERMS = [
    ("playlists", "create"), ("playlists", "read"), ("playlists", "edit"),
    ("playlists", "delete"), ("media", "read"),
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PlAudit", org_slug=f"plaudit-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"pa-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_PA_{uid}", label="PA", is_system=False)
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


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org, client):
    """national → store (mine) + sibling (voisin). L'utilisateur n'administre que `store`."""
    national = await _mk_node(db_session, org, "National")
    store = await _mk_node(db_session, org, "Store", parent=national)
    sibling = await _mk_node(db_session, org, "Sibling", parent=national)
    boss = await _mk_user(db_session, org)
    store_admin = await _mk_user(db_session, org)
    db_session.add(CmsGovernanceNodeAdmin(id_node=national.id_node, id_user=boss.id_user))
    db_session.add(CmsGovernanceNodeAdmin(id_node=store.id_node, id_user=store_admin.id_user))
    await db_session.commit()

    boss_tok = await _token(client, boss)
    store_tok = await _token(client, store_admin)

    # Une playlist chez le voisin, avec un média : de quoi produire une vraie timeline.
    media = CmsMedia(
        id_org=org.id_org, media_name="secret-du-voisin.mp4", media_type="video",
        storage_key=f"k-{uuid.uuid4().hex[:8]}", duration_ms=30000, checksum_sha256=uuid.uuid4().hex,
        transcode_status="done", conformance_status="ready",
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)

    sib_pl = (await client.post("/api/v1/playlists",
              json={"playlist_name": "Sibling PL", "id_governance_node": sibling.id_node},
              headers=_h(boss_tok))).json()["id_playlist"]
    await client.post(f"/api/v1/playlists/{sib_pl}/items",
                      json={"id_media": media.id_media, "sort_order": 0},
                      headers=_h(boss_tok))
    await client.post(f"/api/v1/playlists/{sib_pl}/publish", headers=_h(boss_tok))

    mine_pl = (await client.post("/api/v1/playlists",
               json={"playlist_name": "Mine", "id_governance_node": store.id_node},
               headers=_h(store_tok))).json()["id_playlist"]

    return {
        "org": org, "store": store, "sibling": sibling, "national": national,
        "boss_tok": boss_tok, "store_tok": store_tok, "store_admin": store_admin,
        "sib_pl": sib_pl, "mine_pl": mine_pl, "media": media,
    }


@pytest.mark.asyncio
async def test_simulate_timeline_respects_perimeter(client: AsyncClient, scene) -> None:
    """La simulation d'une playlist d'un nœud frère fuyait le contenu du voisin."""
    # Point de départ : le détail est bien refusé.
    r = await client.get(f"/api/v1/playlists/{scene['sib_pl']}", headers=_h(scene["store_tok"]))
    assert r.status_code == 404

    body = {"date": "2026-07-29", "start_time": "09:00"}
    r = await client.post(f"/api/v1/playlists/{scene['sib_pl']}/simulate-timeline",
                          json=body, headers=_h(scene["store_tok"]))
    assert r.status_code == 404, (
        "la simulation rend le déroulé et les NOMS des médias d'une playlist "
        f"invisible : {str(r.json())[:200]}")

    # Le propriétaire, lui, simule normalement (la garde n'a pas cassé l'usage).
    r = await client.post(f"/api/v1/playlists/{scene['sib_pl']}/simulate-timeline",
                          json=body, headers=_h(scene["boss_tok"]))
    assert r.status_code == 200
    assert len(r.json()["segments"]) > 0


@pytest.mark.asyncio
async def test_item_rules_respect_perimeter(client: AsyncClient, scene) -> None:
    """Les règles d'un item d'une playlist invisible se lisaient en 200.

    ⚠️ Le test doit viser un item RÉEL du voisin : avec un id_item inventé, la route
    répondait déjà 404 « Item introuvable » et le test passait sur le code d'origine —
    vacant, donc ne prouvant rien.
    """
    real_item = (await client.get(f"/api/v1/playlists/{scene['sib_pl']}",
                                  headers=_h(scene["boss_tok"]))).json()["items"][0]["id_item"]

    r = await client.get(f"/api/v1/playlists/{scene['sib_pl']}/items/{real_item}/rules",
                         headers=_h(scene["store_tok"]))
    assert r.status_code == 404, f"règles d'un item du voisin lisibles : {r.text[:150]}"

    # Le propriétaire les lit toujours.
    r = await client.get(f"/api/v1/playlists/{scene['sib_pl']}/items/{real_item}/rules",
                         headers=_h(scene["boss_tok"]))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_cannot_nest_invisible_sub_playlist(client: AsyncClient, scene) -> None:
    """Imbriquer une sous-playlist qu'on reçoit en 404 : accepté (201) avant correctif.

    Conséquence concrète : le contenu du voisin diffusait sur MES écrans, et toute
    modification faite chez lui partait chez moi sans que je puisse ni la voir ni la lire.
    """
    r = await client.post(f"/api/v1/playlists/{scene['mine_pl']}/items",
                          json={"id_child_playlist": scene["sib_pl"], "sort_order": 0},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 404, f"sous-playlist invisible imbriquée : {r.text[:200]}"

    # Le brouillon est resté vide : rien n'a été écrit au passage.
    detail = (await client.get(f"/api/v1/playlists/{scene['mine_pl']}",
                               headers=_h(scene["store_tok"]))).json()
    assert detail["items"] == []


@pytest.mark.asyncio
async def test_cannot_add_deleted_media(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """Un média supprimé était accepté à l'unité (201) alors que l'ajout en lot le filtrait."""
    dead = CmsMedia(
        id_org=scene["org"].id_org, media_name="dead.mp4", media_type="video",
        storage_key=f"k-{uuid.uuid4().hex[:8]}", duration_ms=1000, checksum_sha256=uuid.uuid4().hex,
        transcode_status="done", is_deleted=True,
    )
    db_session.add(dead)
    await db_session.commit()
    await db_session.refresh(dead)

    r = await client.post(f"/api/v1/playlists/{scene['mine_pl']}/items",
                          json={"id_media": dead.id_media, "sort_order": 0},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 404, f"média supprimé ajouté à une playlist : {r.text[:200]}"

    # Parité avec l'ajout en lot, qui l'ignorait déjà silencieusement.
    r = await client.post(f"/api/v1/playlists/{scene['mine_pl']}/items/bulk",
                          json={"id_medias": [dead.id_media]}, headers=_h(scene["store_tok"]))
    assert r.status_code == 201
    assert r.json() == []


@pytest.mark.asyncio
async def test_updated_at_moves_on_mutation(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """`updated_at` restait figé à la création — mesuré 0 playlist sur 20 en prod."""
    pid = scene["mine_pl"]
    media_id = scene["media"].id_media   # capturé AVANT tout expire (objet détaché sinon)

    async def _stamp() -> object:
        # `expire_all` seul ne suffit pas : la session garde le résultat en cache de
        # transaction tant qu'elle n'a pas rouvert la sienne.
        await db_session.rollback()
        return (await db_session.execute(
            select(CmsPlaylist.updated_at).where(CmsPlaylist.id_playlist == pid)
        )).scalar_one()

    before = await _stamp()

    r = await client.put(f"/api/v1/playlists/{pid}", json={"description": "touched"},
                         headers=_h(scene["store_tok"]))
    assert r.status_code == 200
    after = await _stamp()
    assert after > before, "updated_at figé après une mutation"

    # Une mutation qui ne passe PAS par PUT (ajout d'item au brouillon) l'entretient aussi :
    # c'est tout l'intérêt de l'avoir posé au modèle plutôt qu'endpoint par endpoint.
    r = await client.post(f"/api/v1/playlists/{pid}/items",
                          json={"id_media": media_id, "sort_order": 0},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 201
    assert await _stamp() > after


@pytest.mark.asyncio
async def test_mutations_are_audited(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    """Créer / renommer / publier / supprimer ne laissait AUCUNE trace."""
    tok = scene["store_tok"]
    pid = (await client.post("/api/v1/playlists",
           json={"playlist_name": "Tracée", "id_governance_node": scene["store"].id_node},
           headers=_h(tok))).json()["id_playlist"]

    await client.put(f"/api/v1/playlists/{pid}", json={"playlist_name": "Renommée"},
                     headers=_h(tok))
    await client.post(f"/api/v1/playlists/{pid}/items",
                      json={"id_media": scene["media"].id_media, "sort_order": 0},
                      headers=_h(tok))
    await client.post(f"/api/v1/playlists/{pid}/publish", headers=_h(tok))
    await client.delete(f"/api/v1/playlists/{pid}", headers=_h(tok))

    rows = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.resource_type == "playlist",
            CmsAuditLog.resource_id == str(pid),
        )
    )).scalars().all()
    actions = {r.action for r in rows}
    assert {"create", "update", "publish", "delete"} <= actions, actions

    # Le journal survit à la ligne : la playlist est supprimée, la trace nomme l'auteur.
    delete_row = next(r for r in rows if r.action == "delete")
    assert delete_row.id_user == scene["store_admin"].id_user
    assert delete_row.detail["playlist_name"] == "Renommée"
    # Le renommage retient l'ANCIEN nom — c'est celui qu'on cherche après coup.
    update_row = next(r for r in rows if r.action == "update")
    assert update_row.detail["renamed_from"] == "Tracée"


async def test_list_search_is_resolved_server_side(client: AsyncClient, scene) -> None:
    """`q` cherche par NOM côté SERVEUR (ajouté le 2026-07-29, audit Événements/VOD).

    🔴 L'écran des événements alimentait son menu déroulant de playlists par un appel SANS
    paramètre — donc au plafond par défaut de **50** — et **sans recherche** : au-delà, une
    playlist était invisible ET introuvable. Chercher doit se faire là où sont les données.

    ⚠️ Le filtre s'AJOUTE à celui de la gouvernance, il ne le remplace pas : chercher le nom
    d'une playlist d'un nœud FRÈRE ne doit rien rendre, sinon la recherche serait une porte
    dérobée sur du contenu qu'on ne peut pas voir.
    """
    boss, store = scene["boss_tok"], scene["store_tok"]

    # Témoin : sans `q`, l'admin national voit bien les deux playlists.
    names = {p["playlist_name"] for p in
             (await client.get("/api/v1/playlists/", headers=_h(boss))).json()}
    assert {"Mine", "Sibling PL"} <= names

    found = (await client.get("/api/v1/playlists/?q=sibl", headers=_h(boss))).json()
    assert [p["playlist_name"] for p in found] == ["Sibling PL"]

    # Recherche insensible à la casse, et qui ne rend rien pour un nom inexistant.
    assert (await client.get("/api/v1/playlists/?q=MINE", headers=_h(boss))).json()
    assert (await client.get("/api/v1/playlists/?q=zzz", headers=_h(boss))).json() == []

    # 🔑 La gouvernance prime : l'admin du magasin ne trouve PAS la playlist du nœud frère,
    # même en la nommant exactement.
    assert (await client.get("/api/v1/playlists/?q=Sibling", headers=_h(store))).json() == []
