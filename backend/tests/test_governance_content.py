"""Gouvernance §XVIII du CONTENU (R14/R15, décisions D6/D7/D8/D9) — playlists gouvernées.

Prouve les gardes du modèle voulu par Ed :
  · D6 lecture filtrée : on voit son nœud + ses ancêtres (lecture seule), pas un nœud frère ;
  · écriture gardée par le nœud : un admin de magasin n'édite pas le contenu national ;
  · D7 modération : nœud sous modération → publication directe refusée, seul submit→approve
    publie ; décocher la modération est réservé à un admin d'ANCÊTRE ;
  · D8 : l'approbation (par l'admin ancêtre) publie le brouillon.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
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
    ("playlists", "delete"),
    ("media", "read"), ("media", "edit"), ("media", "delete"),
    ("schedules", "read"),   # espace de travail du noeud : lister les programmes du noeud
    ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
    ("approvals", "submit"), ("approvals", "approve"), ("approvals", "review"),
    ("approvals", "reject"),
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovC", org_slug=f"govc-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"c-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_C_{uid}", label="C", is_system=False)
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


async def _mk_node(db: AsyncSession, org, name, parent=None, requires_approval=True):
    n = CmsGovernanceNode(
        id_org=org.id_org, parent_id=parent.id_node if parent else None,
        node_name=name, node_level=(parent.node_level + 1) if parent else 0,
        node_type="store" if parent else "national",
        requires_approval=requires_approval, path="",
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


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org, client):
    """national(root) → store, sibling. boss admine national ; store_admin admine store."""
    national = await _mk_node(db_session, org, "National")
    store = await _mk_node(db_session, org, "Store", parent=national)
    sibling = await _mk_node(db_session, org, "Sibling", parent=national)
    boss = await _mk_user(db_session, org)
    store_admin = await _mk_user(db_session, org)
    await _admin_of(db_session, national, boss)          # boss = admin racine → tout le sous-arbre
    await _admin_of(db_session, store, store_admin)      # store_admin = admin du magasin
    return {
        "national": national, "store": store, "sibling": sibling,
        "boss": boss, "boss_tok": await _token(client, boss),
        "store_admin": store_admin, "store_tok": await _token(client, store_admin),
    }


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_write_gate_and_read_filter(client: AsyncClient, scene) -> None:
    st, nat, sib = scene["store"], scene["national"], scene["sibling"]

    # store_admin crée une playlist sous SON nœud → OK.
    r = await client.post("/api/v1/playlists",
                          json={"playlist_name": "Store PL", "id_governance_node": st.id_node},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 201, r.text
    store_pl = r.json()["id_playlist"]

    # store_admin ne peut PAS créer sous le nœud national (il ne l'administre pas).
    r = await client.post("/api/v1/playlists",
                          json={"playlist_name": "Nope", "id_governance_node": nat.id_node},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 403

    # boss crée une playlist nationale + une playlist sous le magasin frère.
    nat_pl = (await client.post("/api/v1/playlists",
              json={"playlist_name": "National PL", "id_governance_node": nat.id_node},
              headers=_h(scene["boss_tok"]))).json()["id_playlist"]
    sib_pl = (await client.post("/api/v1/playlists",
              json={"playlist_name": "Sibling PL", "id_governance_node": sib.id_node},
              headers=_h(scene["boss_tok"]))).json()["id_playlist"]

    # D6 lecture : store_admin voit la nationale en LECTURE SEULE (ancêtre)…
    r = await client.get(f"/api/v1/playlists/{nat_pl}", headers=_h(scene["store_tok"]))
    assert r.status_code == 200
    assert r.json()["governed_readonly"] is True
    # …voit la sienne en édition…
    r = await client.get(f"/api/v1/playlists/{store_pl}", headers=_h(scene["store_tok"]))
    assert r.json()["governed_readonly"] is False
    # …et NE VOIT PAS celle du magasin frère (404 comme un cross-tenant).
    r = await client.get(f"/api/v1/playlists/{sib_pl}", headers=_h(scene["store_tok"]))
    assert r.status_code == 404

    # La liste de store_admin exclut la playlist du frère.
    ids = [p["id_playlist"] for p in
           (await client.get("/api/v1/playlists/", headers=_h(scene["store_tok"]))).json()]
    assert store_pl in ids and nat_pl in ids and sib_pl not in ids

    # store_admin ne peut pas éditer la playlist nationale (403).
    r = await client.put(f"/api/v1/playlists/{nat_pl}",
                         json={"description": "hack"}, headers=_h(scene["store_tok"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_moderation_publish_gate_and_approve_publishes(
    client: AsyncClient, db_session: AsyncSession, scene
) -> None:
    st = scene["store"]
    # store est sous modération (défaut hérité). store_admin crée + ajoute un item au brouillon.
    store_pl = (await client.post("/api/v1/playlists",
                json={"playlist_name": "Moderated", "id_governance_node": st.id_node},
                headers=_h(scene["store_tok"]))).json()["id_playlist"]
    # Un item minimal (sous-playlist non requise) — on ajoute une sous-playlist enfant pour
    # avoir un brouillon non vide sans média. On crée une playlist enfant simple.
    child = (await client.post("/api/v1/playlists",
             json={"playlist_name": "Child", "id_governance_node": st.id_node},
             headers=_h(scene["store_tok"]))).json()["id_playlist"]
    r = await client.post(f"/api/v1/playlists/{store_pl}/items",
                          json={"id_child_playlist": child, "sort_order": 0},
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 201, r.text

    # Publication DIRECTE refusée (nœud sous modération) → 409.
    r = await client.post(f"/api/v1/playlists/{store_pl}/publish", headers=_h(scene["store_tok"]))
    assert r.status_code == 409

    # Soumission à l'approbation → 200.
    r = await client.post(f"/api/v1/playlists/{store_pl}/submit-approval",
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 200, r.text
    id_request = r.json()["id_request"]

    # boss (admin de l'ancêtre) approuve → le brouillon est PUBLIÉ (items appliqués, draft vidé).
    r = await client.post(f"/api/v1/approvals/{id_request}/approve",
                          json={}, headers=_h(scene["boss_tok"]))
    assert r.status_code == 200, r.text

    pl = (await db_session.execute(select(CmsPlaylist).where(
        CmsPlaylist.id_playlist == store_pl))).scalar_one()
    await db_session.refresh(pl)
    assert pl.draft_items is None  # brouillon appliqué puis vidé
    detail = (await client.get(f"/api/v1/playlists/{store_pl}", headers=_h(scene["store_tok"]))).json()
    assert detail["has_draft_changes"] is False
    assert len(detail["items"]) == 1  # l'item sous-playlist a bien été publié


async def _mk_media(db: AsyncSession, org, name, node=None) -> CmsMedia:
    m = CmsMedia(
        id_org=org.id_org, media_name=name, media_type="image",
        storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
        id_governance_node=node.id_node if node else None,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@pytest.mark.asyncio
async def test_media_gate_and_read_filter(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """D9 : un local ne modifie/supprime pas un média national ; filtre lecture."""
    nat_media = await _mk_media(db_session, org, "National.mp4", node=scene["national"])
    store_media = await _mk_media(db_session, org, "Store.mp4", node=scene["store"])
    sib_media = await _mk_media(db_session, org, "Sibling.mp4", node=scene["sibling"])

    # store_admin renomme SON média → OK ; le média NATIONAL → 403 ; le PURGE national → 403.
    r = await client.patch(f"/api/v1/media/{store_media.id_media}/rename",
                           json={"media_name": "Renamed"}, headers=_h(scene["store_tok"]))
    assert r.status_code == 200, r.text
    r = await client.patch(f"/api/v1/media/{nat_media.id_media}/rename",
                           json={"media_name": "Hack"}, headers=_h(scene["store_tok"]))
    assert r.status_code == 403
    r = await client.post(f"/api/v1/media/{nat_media.id_media}/purge",
                          headers=_h(scene["store_tok"]))
    assert r.status_code == 403

    # Lecture D6 : la liste de store_admin exclut le média du magasin frère.
    ids = [m["id_media"] for m in
           (await client.get("/api/v1/media/", headers=_h(scene["store_tok"]))).json()]
    assert store_media.id_media in ids and nat_media.id_media in ids
    assert sib_media.id_media not in ids

    # Le média national est visible mais marqué lecture seule pour le front.
    nat_row = next(m for m in
                   (await client.get("/api/v1/media/", headers=_h(scene["store_tok"]))).json()
                   if m["id_media"] == nat_media.id_media)
    assert nat_row["governed_readonly"] is True


@pytest.mark.asyncio
async def test_only_ancestor_can_disable_moderation(client: AsyncClient, scene) -> None:
    st = scene["store"]
    # store_admin ne peut PAS retirer la modération de son propre nœud (D7).
    r = await client.put(f"/api/v1/governance/nodes/{st.id_node}",
                         json={"requires_approval": False}, headers=_h(scene["store_tok"]))
    assert r.status_code == 403
    # boss (admin de l'ancêtre national) le peut.
    r = await client.put(f"/api/v1/governance/nodes/{st.id_node}",
                         json={"requires_approval": False}, headers=_h(scene["boss_tok"]))
    assert r.status_code == 200
    assert r.json()["requires_approval"] is False

    # …MAIS décocher en bas ne suffit pas : la modération est MONOTONE vers le bas
    # (décision Ed 2026-07-26, symétrique de la délégation des règles). Tant qu'un ANCÊTRE
    # l'exige, le contenu du nœud reste modéré — sinon la modération du national n'aurait
    # tenu que si personne en dessous ne la retirait.
    pl = (await client.post("/api/v1/playlists",
          json={"playlist_name": "Free", "id_governance_node": st.id_node},
          headers=_h(scene["store_tok"]))).json()["id_playlist"]
    r = await client.post(f"/api/v1/playlists/{pl}/publish", headers=_h(scene["store_tok"]))
    assert r.status_code == 409, r.text

    # Et le boss ne peut pas libérer la chaîne en démodérant la RACINE : un nœud racine n'a
    # pas d'ancêtre, donc seul l'org-admin le peut. La modération posée au sommet ne se
    # retire que depuis le sommet.
    r = await client.put(f"/api/v1/governance/nodes/{scene['national'].id_node}",
                         json={"requires_approval": False}, headers=_h(scene["boss_tok"]))
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_frontend_support_fields(client: AsyncClient, scene) -> None:
    """Champs que consomme l'UI (§XVIII contenu) : sélecteur de nœud honnête + état de
    la demande d'approbation.

    Sans eux, le front ne peut ni éviter d'offrir un nœud qui répondra 403, ni dire
    « en cours de validation » après un rechargement de page — il ne resterait que le
    409 « une demande est déjà active » au 2ᵉ clic.
    """
    st, nat, sib = scene["store"], scene["national"], scene["sibling"]

    # can_edit : store_admin édite SON nœud, pas l'ancêtre national.
    nodes = (await client.get("/api/v1/governance/nodes", headers=_h(scene["store_tok"]))).json()
    by_id = {n["id_node"]: n for n in nodes}
    assert by_id[st.id_node]["can_edit"] is True
    assert by_id[nat.id_node]["can_edit"] is False
    # Le nœud FRÈRE a disparu de l'arbre depuis N7 (phase 5, 2026-07-27) : la structure est
    # filtrée comme le contenu. Avant, il était rendu — seulement marqué non éditable.
    assert sib.id_node not in by_id
    # boss administre la racine → tout le sous-arbre est éditable.
    boss_nodes = (await client.get("/api/v1/governance/nodes",
                                   headers=_h(scene["boss_tok"]))).json()
    assert all(n["can_edit"] for n in boss_nodes)

    # can_disable_moderation (D7) : réservé à l'admin d'un ANCÊTRE.
    d = (await client.get(f"/api/v1/governance/nodes/{st.id_node}",
                          headers=_h(scene["store_tok"]))).json()
    assert d["can_disable_moderation"] is False
    d = (await client.get(f"/api/v1/governance/nodes/{st.id_node}",
                          headers=_h(scene["boss_tok"]))).json()
    assert d["can_disable_moderation"] is True

    # approval_status : null tant que rien n'est soumis, puis pending_review.
    pl = (await client.post("/api/v1/playlists",
          json={"playlist_name": "Tracked", "id_governance_node": st.id_node},
          headers=_h(scene["store_tok"]))).json()["id_playlist"]
    child = (await client.post("/api/v1/playlists",
             json={"playlist_name": "Tracked child", "id_governance_node": st.id_node},
             headers=_h(scene["store_tok"]))).json()["id_playlist"]
    await client.post(f"/api/v1/playlists/{pl}/items",
                      json={"id_child_playlist": child, "sort_order": 0},
                      headers=_h(scene["store_tok"]))
    detail = (await client.get(f"/api/v1/playlists/{pl}", headers=_h(scene["store_tok"]))).json()
    assert detail["approval_status"] is None

    r = await client.post(f"/api/v1/playlists/{pl}/submit-approval", headers=_h(scene["store_tok"]))
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/v1/playlists/{pl}", headers=_h(scene["store_tok"]))).json()
    assert detail["approval_status"] == "pending_review"
    assert detail["approval_request_id"] == r.json()["id_request"]


# ── Avertissement « contenu trop long » AU CHARGEMENT de la playlist (Ed, 2026-07-26) ──
# Avant : on ne découvrait le contenu écarté qu'à l'aperçu du programme compilé, une fois la
# playlist déjà construite. Le plafond est HÉRITÉ : il est posé sur le NATIONAL et l'on attend
# l'avertissement sur une playlist rattachée au MAGASIN, qui n'a lui-même aucun plafond.

@pytest.mark.asyncio
async def test_playlist_warns_about_content_too_long(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    from app.models.playlist import CmsPlaylistItem

    nat, st = scene["national"], scene["store"]
    cap = await client.put(f"/api/v1/governance/nodes/{nat.id_node}",
                           json={"max_item_sec": 60}, headers=_h(scene["boss_tok"]))
    assert cap.status_code == 200, cap.text

    short = CmsMedia(id_org=org.id_org, media_name="Court", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     duration_ms=30_000)
    long_ = CmsMedia(id_org=org.id_org, media_name="Compil 3h", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     duration_ms=3 * 3600 * 1000)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL-long", id_governance_node=st.id_node)
    db_session.add_all([short, long_, pl])
    await db_session.flush()
    db_session.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=short.id_media, sort_order=0),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=long_.id_media, sort_order=1),
    ])
    await db_session.commit()

    detail = (await client.get(f"/api/v1/playlists/{pl.id_playlist}",
                               headers=_h(scene["store_tok"]))).json()
    assert detail["governance_max_item_sec"] == 60      # hérité du national
    # Le contenu fautif est NOMMÉ : « certains contenus » enverrait chercher au mauvais endroit.
    assert detail["governance_too_long"] == ["Compil 3h"]


# ── Espace de travail du noeud : filtres de lecture par noeud (2026-07-26) ────
# Sans eux, /governance ne pouvait pas AFFICHER ce que le noeud porte — c'est le seul
# manque backend du point 4 d'Ed, le reste etant de l'assemblage d'endpoints existants.
#
# Le test verifie surtout que le filtre s'AJOUTE au filtre de visibilite D6 et ne le
# remplace pas : demander un noeud qu'on n'a pas le droit de voir doit rendre une liste
# vide, jamais ouvrir une porte derobee sur le contenu d'un noeud frere.

@pytest.mark.asyncio
async def test_node_filter_lists_content_without_bypassing_visibility(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    from app.models.schedule import CmsSchedule

    st, sib = scene["store"], scene["sibling"]

    own = CmsPlaylist(id_org=org.id_org, playlist_name="PL du magasin",
                      id_governance_node=st.id_node)
    foreign = CmsPlaylist(id_org=org.id_org, playlist_name="PL du voisin",
                          id_governance_node=sib.id_node)
    db_session.add_all([own, foreign])
    await db_session.flush()
    db_session.add(CmsSchedule(
        id_org=org.id_org, schedule_name="SC du magasin", schedule_kind="content",
        id_playlist=own.id_playlist, id_governance_node=st.id_node,
    ))
    await db_session.commit()

    h = _h(scene["store_tok"])   # admin du MAGASIN seulement

    pls = (await client.get("/api/v1/playlists/",
                            params={"id_governance_node": st.id_node}, headers=h)).json()
    assert [p["playlist_name"] for p in pls] == ["PL du magasin"]

    scs = (await client.get("/api/v1/schedules",
                            params={"id_governance_node": st.id_node}, headers=h)).json()
    assert [s["schedule_name"] for s in scs] == ["SC du magasin"]

    # Noeud FRERE : visible par personne d'autre que ses admins (D6) -> liste vide, pas 200
    # avec le contenu du voisin.
    leak = (await client.get("/api/v1/playlists/",
                             params={"id_governance_node": sib.id_node}, headers=h)).json()
    assert leak == []


# ── Audit du menu Média (2026-07-28) : les mutations qui échappaient à la garde ──
#
# `_get_media_editable` existait et était posée sur renommage, ré-encodage, remplacement,
# quarantaine, purge, renditions… mais CINQ chemins rechargeaient le média à la main et
# passaient donc à côté : suppression, embargo, droits, classement en masse, et le module
# url-display (chemin d'écriture PARALLÈLE sur la même table `cms_media`).

@pytest.mark.asyncio
async def test_destructive_media_routes_are_node_gated(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Un responsable local ne supprime pas, ne met pas sous embargo et ne redéclare pas
    les droits d'un média NATIONAL — alors qu'il peut tout cela sur le sien."""
    nat = await _mk_media(db_session, org, "National.mp4", node=scene["national"])
    mine = await _mk_media(db_session, org, "Store.mp4", node=scene["store"])
    h = _h(scene["store_tok"])

    # DELETE : la route la plus destructive du module (cascade playlists/programmes/events).
    assert (await client.delete(f"/api/v1/media/{nat.id_media}", headers=h)).status_code == 403
    # EMBARGO : éteint la diffusion d'un média — au moins aussi lourd de conséquence.
    r = await client.patch(f"/api/v1/media/{nat.id_media}/embargo",
                           json={"not_before_utc": None, "embargo_event_id": None}, headers=h)
    assert r.status_code == 403, r.text
    # DROITS (ISRC / déclaration SACEM).
    r = await client.patch(f"/api/v1/media/{nat.id_media}/rights",
                           json={"isrc": None, "rights_metadata": {}}, headers=h)
    assert r.status_code == 403, r.text

    # Sur SON propre média, les trois passent : la garde restreint, elle ne bloque pas tout.
    r = await client.patch(f"/api/v1/media/{mine.id_media}/embargo",
                           json={"not_before_utc": None, "embargo_event_id": None}, headers=h)
    assert r.status_code == 200, r.text
    assert (await client.delete(f"/api/v1/media/{mine.id_media}", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_media_detail_is_not_reachable_by_deep_link(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """La LISTE filtre par visibilité ; les routes unitaires rechargeaient par identifiant.
    Un lien direct contournait donc le filtre — c'est le trou que `playlists.py` ferme déjà."""
    sib = await _mk_media(db_session, org, "Sibling.mp4", node=scene["sibling"])
    h = _h(scene["store_tok"])

    # Le média du nœud FRÈRE n'existe pas pour lui : 404, comme un cross-tenant.
    assert (await client.get(f"/api/v1/media/{sib.id_media}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/media/{sib.id_media}/download", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/media/{sib.id_media}/renditions", headers=h)).status_code == 404

    # Son propre média reste lisible, et le drapeau d'édition est calculé ici aussi —
    # sans lui, le tiroir ouvert par lien direct s'affichait éditable puis partait en 403.
    mine = await _mk_media(db_session, org, "Mine.mp4", node=scene["store"])
    r = await client.get(f"/api/v1/media/{mine.id_media}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["governed_readonly"] is False

    nat = await _mk_media(db_session, org, "Nat2.mp4", node=scene["national"])
    r = await client.get(f"/api/v1/media/{nat.id_media}", headers=h)
    assert r.status_code == 200          # un ancêtre reste VISIBLE (D6)…
    assert r.json()["governed_readonly"] is True   # …mais en lecture seule.


@pytest.mark.asyncio
async def test_bulk_move_refuses_the_whole_lot(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Classer est une mutation. Un lot contenant un média interdit est refusé EN ENTIER :
    un déplacement partiel ferait croire à l'utilisateur que tout est classé."""
    nat = await _mk_media(db_session, org, "National.mp4", node=scene["national"])
    mine = await _mk_media(db_session, org, "Store.mp4", node=scene["store"])
    h = _h(scene["store_tok"])
    folder = (await client.post("/api/v1/media/folders",
                                json={"folder_name": "Classement"}, headers=h)).json()

    r = await client.post("/api/v1/media/folders/move-media",
                          json={"id_media": [mine.id_media, nat.id_media],
                                "id_folder": folder["id_folder"]}, headers=h)
    assert r.status_code == 403, r.text
    assert "National.mp4" in r.json()["detail"]  # le média refusé est NOMMÉ

    # Rien n'a bougé, pas même le média autorisé du lot.
    await db_session.refresh(mine)
    assert mine.id_folder is None

    # Le lot propre passe.
    r = await client.post("/api/v1/media/folders/move-media",
                          json={"id_media": [mine.id_media], "id_folder": folder["id_folder"]},
                          headers=h)
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_folder_media_count_follows_visibility(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Un compteur qui décrit du contenu invisible est faux à l'écran ET indiscret."""
    h = _h(scene["store_tok"])
    folder = (await client.post("/api/v1/media/folders",
                                json={"folder_name": "Mixte"}, headers=h)).json()
    for name, node in (("Vu.mp4", scene["store"]), ("PasVu.mp4", scene["sibling"])):
        m = await _mk_media(db_session, org, name, node=node)
        m.id_folder = folder["id_folder"]
    await db_session.commit()

    listed = (await client.get("/api/v1/media/folders", headers=h)).json()
    row = next(f for f in listed if f["id_folder"] == folder["id_folder"])
    listed_media = (await client.get(f"/api/v1/media/?id_folder={folder['id_folder']}",
                                     headers=h)).json()
    rows = listed_media["items"] if isinstance(listed_media, dict) else listed_media
    # Le compteur annonce exactement ce que la liste renvoie — avant, il annonçait 2 pour 1.
    assert row["media_count"] == len(rows) == 1
