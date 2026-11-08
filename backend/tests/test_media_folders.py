"""
Tests dossiers médias (§ retours clients) — CRUD, déplacement (path matérialisé),
anti-cycle, suppression bloquée, move-media + filtrage liste.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="MF", org_slug=f"mf-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"mf-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_MF_{uid}", label="MF", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("media", "create"), ("media", "read"),
                              ("media", "edit"), ("media", "delete")]:
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
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                 storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                 transcode_status="done")
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_tree_paths_and_counts(client, auth_token):
    h = _h(auth_token)
    root = (await client.post("/api/v1/media/folders", json={"folder_name": "Campagnes"}, headers=h)).json()
    assert root["depth"] == 0 and root["path"] == str(root["id_folder"])
    child = (await client.post("/api/v1/media/folders",
                               json={"folder_name": "Ete", "parent_id": root["id_folder"]}, headers=h)).json()
    assert child["depth"] == 1 and child["path"] == f"{root['id_folder']}.{child['id_folder']}"

    listed = (await client.get("/api/v1/media/folders", headers=h)).json()
    root_row = next(f for f in listed if f["id_folder"] == root["id_folder"])
    assert root_row["child_count"] == 1


@pytest.mark.asyncio
async def test_rename_and_move_recomputes_subtree(client, auth_token):
    h = _h(auth_token)
    a = (await client.post("/api/v1/media/folders", json={"folder_name": "A"}, headers=h)).json()
    b = (await client.post("/api/v1/media/folders", json={"folder_name": "B"}, headers=h)).json()
    sub = (await client.post("/api/v1/media/folders",
                             json={"folder_name": "sub", "parent_id": a["id_folder"]}, headers=h)).json()
    leaf = (await client.post("/api/v1/media/folders",
                              json={"folder_name": "leaf", "parent_id": sub["id_folder"]}, headers=h)).json()

    # Déplace 'sub' (et 'leaf') sous B + renomme
    r = await client.put(f"/api/v1/media/folders/{sub['id_folder']}",
                         json={"folder_name": "sub2", "parent_id": b["id_folder"]}, headers=h)
    assert r.status_code == 200
    moved = r.json()
    assert moved["folder_name"] == "sub2"
    assert moved["path"] == f"{b['id_folder']}.{sub['id_folder']}"
    assert moved["depth"] == 1

    listed = {f["id_folder"]: f for f in (await client.get("/api/v1/media/folders", headers=h)).json()}
    # leaf a suivi : path préfixé par le nouveau path de sub, depth+0 (était 2, reste 2)
    assert listed[leaf["id_folder"]]["path"] == f"{b['id_folder']}.{sub['id_folder']}.{leaf['id_folder']}"
    assert listed[leaf["id_folder"]]["depth"] == 2


@pytest.mark.asyncio
async def test_move_into_descendant_rejected(client, auth_token):
    h = _h(auth_token)
    a = (await client.post("/api/v1/media/folders", json={"folder_name": "A"}, headers=h)).json()
    sub = (await client.post("/api/v1/media/folders",
                             json={"folder_name": "sub", "parent_id": a["id_folder"]}, headers=h)).json()
    # déplacer A dans son propre descendant 'sub' → 422
    r = await client.put(f"/api/v1/media/folders/{a['id_folder']}",
                         json={"parent_id": sub["id_folder"]}, headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_blocked_if_children(client, auth_token):
    h = _h(auth_token)
    a = (await client.post("/api/v1/media/folders", json={"folder_name": "A"}, headers=h)).json()
    await client.post("/api/v1/media/folders", json={"folder_name": "sub", "parent_id": a["id_folder"]}, headers=h)
    r = await client.delete(f"/api/v1/media/folders/{a['id_folder']}", headers=h)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_orphans_media_to_root(client, auth_token, media_item):
    h = _h(auth_token)
    f = (await client.post("/api/v1/media/folders", json={"folder_name": "F"}, headers=h)).json()
    await client.post("/api/v1/media/folders/move-media",
                      json={"id_media": [media_item.id_media], "id_folder": f["id_folder"]}, headers=h)
    # le média est dans le dossier
    rows = (await client.get(f"/api/v1/media/?id_folder={f['id_folder']}", headers=h)).json()
    assert any(m["id_media"] == media_item.id_media for m in rows)
    # suppression du dossier → média remonte à la racine (SET NULL)
    r = await client.delete(f"/api/v1/media/folders/{f['id_folder']}", headers=h)
    assert r.status_code == 204
    rows = (await client.get("/api/v1/media/?unfiled=true", headers=h)).json()
    assert any(m["id_media"] == media_item.id_media for m in rows)


@pytest.mark.asyncio
async def test_move_media_and_filter(client, auth_token, media_item):
    h = _h(auth_token)
    f = (await client.post("/api/v1/media/folders", json={"folder_name": "F"}, headers=h)).json()
    # non classé au départ
    unfiled = (await client.get("/api/v1/media/?unfiled=true", headers=h)).json()
    assert any(m["id_media"] == media_item.id_media for m in unfiled)
    # déplacé dans F
    await client.post("/api/v1/media/folders/move-media",
                      json={"id_media": [media_item.id_media], "id_folder": f["id_folder"]}, headers=h)
    in_f = (await client.get(f"/api/v1/media/?id_folder={f['id_folder']}", headers=h)).json()
    assert any(m["id_media"] == media_item.id_media and m["id_folder"] == f["id_folder"] for m in in_f)
    # plus dans les non classés
    unfiled = (await client.get("/api/v1/media/?unfiled=true", headers=h)).json()
    assert not any(m["id_media"] == media_item.id_media for m in unfiled)


@pytest.mark.asyncio
async def test_list_media_subtree_filter(client, auth_token, db_session, org):
    """`subtree=true` inclut les médias des sous-dossiers (picker de créatifs annonceur)."""
    h = _h(auth_token)
    parent = (await client.post("/api/v1/media/folders",
                                json={"folder_name": "Adv"}, headers=h)).json()
    child = (await client.post(
        "/api/v1/media/folders",
        json={"folder_name": "Sub", "parent_id": parent["id_folder"]}, headers=h)).json()
    m_parent = CmsMedia(id_org=org.id_org, media_name="in-parent", media_type="video",
                        storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                        transcode_status="done", id_folder=parent["id_folder"])
    m_child = CmsMedia(id_org=org.id_org, media_name="in-child", media_type="video",
                       storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                       transcode_status="done", id_folder=child["id_folder"])
    db_session.add_all([m_parent, m_child])
    await db_session.commit()

    flat = (await client.get(f"/api/v1/media/?id_folder={parent['id_folder']}",
                             headers=h)).json()
    assert {m["id_media"] for m in flat} == {m_parent.id_media}

    sub = (await client.get(
        f"/api/v1/media/?id_folder={parent['id_folder']}&subtree=true", headers=h)).json()
    assert {m["id_media"] for m in sub} == {m_parent.id_media, m_child.id_media}


# ── Homonymes + ordre hiérarchique (audit du menu Média, 2026-07-28) ──────────
#
# Constat d'Ed : « si j'ai 2 dossiers racines XXX et YYY, que je crée dans chacun d'eux un
# dossier ZZZ, je le vois bien dans l'arborescence à gauche, mais un des deux n'apparaît
# pas quand on veut classer les contenus ». Deux causes mesurées, cumulatives :
#   · le tiroir de classement liste les dossiers À PLAT et n'affichait QUE le nom, donc
#     deux homonymes y donnaient deux lignes strictement identiques ;
#   · `ORDER BY path` s'appuyait sur la collation de la base (`en_US.utf8`), qui IGNORE la
#     ponctuation : « 11 » se comparait à « 1.13 » comme « 11 » à « 113 », d'où un dossier
#     racine intercalé entre un autre parent et ses enfants. Mesuré en production : la
#     racine « Document » et son enfant s'inséraient entre « Video » et ses 8 enfants, qui
#     paraissaient donc lui appartenir — pendant que « Video » paraissait vide.

@pytest.mark.asyncio
async def test_homonym_folders_are_distinguishable(client, auth_token):
    """Le cas exact d'Ed : XXX/ZZZ et YYY/ZZZ. Les deux doivent sortir, et être TELLEMENT
    distincts qu'on puisse choisir — c'est `full_path` qui le permet."""
    h = _h(auth_token)
    xxx = (await client.post("/api/v1/media/folders", json={"folder_name": "XXX"}, headers=h)).json()
    yyy = (await client.post("/api/v1/media/folders", json={"folder_name": "YYY"}, headers=h)).json()
    z1 = (await client.post("/api/v1/media/folders",
                            json={"folder_name": "ZZZ", "parent_id": xxx["id_folder"]}, headers=h)).json()
    z2 = (await client.post("/api/v1/media/folders",
                            json={"folder_name": "ZZZ", "parent_id": yyy["id_folder"]}, headers=h)).json()

    listed = (await client.get("/api/v1/media/folders", headers=h)).json()
    by_id = {f["id_folder"]: f for f in listed}

    # Les deux existent bel et bien dans la charge utile…
    assert z1["id_folder"] in by_id and z2["id_folder"] in by_id
    # …et ne se ressemblent plus : le chemin complet les sépare.
    assert by_id[z1["id_folder"]]["full_path"] == "XXX / ZZZ"
    assert by_id[z2["id_folder"]]["full_path"] == "YYY / ZZZ"
    assert by_id[xxx["id_folder"]]["full_path"] == "XXX"


@pytest.mark.asyncio
async def test_folder_list_is_hierarchically_ordered(client, auth_token):
    """Chaque dossier est immédiatement suivi de ses descendants, frères triés par nom.

    Rouge avant : avec `ORDER BY path` et la collation par défaut, une racine dont
    l'identifiant est un préfixe d'un autre (1 et 11) venait s'intercaler entre un parent
    et ses enfants. On reproduit la forme du défaut sans dépendre des identifiants réels
    en vérifiant la PROPRIÉTÉ qui doit toujours tenir : entre un parent et son dernier
    descendant, on ne croise jamais un dossier d'une autre branche.
    """
    h = _h(auth_token)
    a = (await client.post("/api/v1/media/folders", json={"folder_name": "Alpha"}, headers=h)).json()
    b = (await client.post("/api/v1/media/folders", json={"folder_name": "Beta"}, headers=h)).json()
    for parent, names in ((a, ["a2", "a1"]), (b, ["b1"])):
        for n in names:
            await client.post("/api/v1/media/folders",
                              json={"folder_name": n, "parent_id": parent["id_folder"]}, headers=h)

    listed = (await client.get("/api/v1/media/folders", headers=h)).json()
    names = [f["folder_name"] for f in listed]

    # Frères triés par nom : « a1 » avant « a2 » bien que créé APRÈS (donc id plus grand).
    assert names.index("a1") < names.index("a2")
    # Chaque branche est d'un seul tenant : Alpha, ses 2 enfants, puis Beta et le sien.
    assert names[names.index("Alpha"):names.index("Alpha") + 3] == ["Alpha", "a1", "a2"]
    assert names[names.index("Beta"):names.index("Beta") + 2] == ["Beta", "b1"]

    # Propriété générale : un parent précède toujours ses enfants, et les descendants
    # d'un dossier occupent un segment CONTINU de la liste.
    pos = {f["id_folder"]: i for i, f in enumerate(listed)}
    by_id = {f["id_folder"]: f for f in listed}
    for f in listed:
        if f["parent_id"] is not None:
            assert pos[f["parent_id"]] < pos[f["id_folder"]]
            assert by_id[f["parent_id"]]["depth"] + 1 == f["depth"]


# ── « Où est utilisé ce média » (demande d'Ed, audit du menu Média 2026-07-28) ────

@pytest.mark.asyncio
async def test_media_usage_reports_playlists_schedules_and_screens(
    client, auth_token, db_session, org
) -> None:
    """Un média doit dire dans quelle playlist et quel programme il vit, et surtout sur
    quels ÉCRANS il passe. Le comptage d'écrans passe par le service de ciblage canonique
    (jamais une requête maison) : un programme visant un SITE doit résoudre ses écrans."""
    from app.models.organization import CmsSite
    from app.models.player import CmsPlayer
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem
    from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget

    h = _h(auth_token)
    media = CmsMedia(id_org=org.id_org, media_name="Spot.mp4", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     transcode_status="done")
    site = CmsSite(id_org=org.id_org, site_name="Magasin")
    db_session.add_all([media, site])
    await db_session.flush()
    p1 = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Ecran-1",
                   status="online")
    p2 = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Ecran-2",
                   status="online")
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Boucle Vitrine")
    db_session.add_all([p1, p2, playlist])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=playlist.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="Diffusion Vitrine",
                        id_playlist=playlist.id_playlist, is_active=True, priority=10)
    db_session.add(sched)
    await db_session.flush()
    db_session.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        # Cible SITE : c'est la forme qui avait été acceptée puis jamais diffusée en 07/18 —
        # elle doit résoudre les 2 écrans du magasin.
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="site",
                          target_id=site.id_site),
    ])
    await db_session.commit()

    r = await client.get(f"/api/v1/media/{media.id_media}/usage", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert [p["playlist_name"] for p in body["playlists"]] == ["Boucle Vitrine"]
    assert body["summary"]["playlists"] == 1
    # Les programmes qui DIFFUSENT doivent etre listes, pas seulement ceux qu'une
    # suppression emporterait : sinon l'ecran annonce « N ecrans via programme » au-dessus
    # d'une liste vide (mesure sur les donnees d'Ed apres le 1er deploiement).
    assert [s["schedule_name"] for s in body["schedules"]] == ["Diffusion Vitrine"]
    assert body["summary"]["schedules"] == 1
    # Le point qui compte pour Ed : les écrans, nommés, avec leur statut.
    assert {s["player_name"] for s in body["screens"]} == {"Ecran-1", "Ecran-2"}
    assert body["summary"]["screens"] == 2
    assert all(s["site_name"] == "Magasin" for s in body["screens"])
    assert all("schedule" in s["via"] for s in body["screens"])


@pytest.mark.asyncio
async def test_media_usage_resolves_screens_of_an_event(
    client, auth_token, db_session, org
) -> None:
    """La voie ÉVÉNEMENT doit résoudre ses écrans comme la voie programme.

    🔴 Prouvé rouge avant correctif (2026-07-30) : `_targets_of_events` lisait
    `cfg.get("target_id")` au SINGULIER alors qu'un événement stocke `target_ids` (liste)
    — toute cible non-org donnait donc 0 écran, sans erreur. Le test du 28/07 ne passait
    que par la voie programme, le trou était invisible.
    """
    from app.models.event import CmsEvent
    from app.models.organization import CmsSite
    from app.models.player import CmsPlayer

    h = _h(auth_token)
    media = CmsMedia(id_org=org.id_org, media_name="Alerte.mp4", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     transcode_status="done")
    site = CmsSite(id_org=org.id_org, site_name="Galerie")
    db_session.add_all([media, site])
    await db_session.flush()
    p1 = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Vitrine",
                   status="online")
    db_session.add(p1)
    await db_session.flush()
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Alerte", event_type="manual", event_kind="content",
        status="active", id_media=media.id_media,
        target_config={"target_type": "player", "target_ids": [p1.id_player]},
    ))
    await db_session.commit()

    r = await client.get(f"/api/v1/media/{media.id_media}/usage", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["events"] == 1
    assert {s["player_name"] for s in body["screens"]} == {"Vitrine"}
    assert all("event" in s["via"] for s in body["screens"])


@pytest.mark.asyncio
async def test_media_usage_is_empty_for_an_unused_media(client, auth_token, db_session, org) -> None:
    """Un média non utilisé le dit clairement — plutôt qu'une réponse vide ambiguë."""
    media = CmsMedia(id_org=org.id_org, media_name="Orphelin.mp4", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     transcode_status="done")
    db_session.add(media)
    await db_session.commit()

    r = await client.get(f"/api/v1/media/{media.id_media}/usage", headers=_h(auth_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == {"playlists": 0, "schedules": 0, "events": 0,
                               "screens": 0, "is_live": False}


@pytest.mark.asyncio
async def test_usage_summary_batches_and_is_a_fixed_route(
    client, auth_token, db_session, org
) -> None:
    """Résumé « combien d'écrans » pour un LOT — affiché en permanence sur les vignettes.

    Vérifie AUSSI que `/media/usage-summary` est bien une route FIXE : posée après
    `/media/{id_media}`, elle serait capturée par celle-ci et répondrait 422
    (« usage-summary » n'est pas un entier). C'est le piège documenté au § Backend.
    """
    from app.models.organization import CmsSite
    from app.models.player import CmsPlayer
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem
    from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget

    h = _h(auth_token)
    site = CmsSite(id_org=org.id_org, site_name="Boutique")
    diffuse = CmsMedia(id_org=org.id_org, media_name="Diffuse.mp4", media_type="video",
                       storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                       transcode_status="done")
    orphan = CmsMedia(id_org=org.id_org, media_name="Orphelin.mp4", media_type="video",
                      storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                      transcode_status="done")
    db_session.add_all([site, diffuse, orphan])
    await db_session.flush()
    db_session.add_all([
        CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="E1", status="online"),
        CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="E2", status="online"),
    ])
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Boucle")
    db_session.add(playlist)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=playlist.id_playlist,
                                   id_media=diffuse.id_media, sort_order=0, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="Diff", id_playlist=playlist.id_playlist,
                        is_active=True, priority=10)
    db_session.add(sched)
    await db_session.flush()
    db_session.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="site",
                          target_id=site.id_site),
    ])
    await db_session.commit()

    r = await client.get(
        f"/api/v1/media/usage-summary?ids={diffuse.id_media},{orphan.id_media}", headers=h)
    assert r.status_code == 200, r.text          # 422 ici = la route fixe est mal placée
    body = r.json()
    assert body[str(diffuse.id_media)] == {"playlists": 1, "screens": 2}
    # Un média non diffusé le dit par des zéros, pas par une absence.
    assert body[str(orphan.id_media)] == {"playlists": 0, "screens": 0}
