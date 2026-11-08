"""Tests Playlist rotation — sous-playlists « N items par tour » (retour beta 2026-07-16).

- Maths pures : rotation_turns, build_turn_selections (séquentiel = exemple d'Ed
  N=5 K=2 → i1i2 · i3i4 · i5i1 · … ; aléatoire = permutations sans remise,
  déterministe par seed, pas de doublon dos à dos aux frontières de re-mélange),
  unroll_slots (déroulé du cycle).
- CRUD : ajout d'item sub_playlist (brouillon → publish), gardes d'imbrication
  (auto-référence, 2 niveaux), suppression bloquée si référencée.
- Payload player (_resolve_sync_payload) : la boucle plate contient les T tours.
"""

import uuid
from collections import Counter

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _resolve_sync_payload
from app.core.security import hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.playlist_rotation import (
    build_turn_selections,
    rotation_seed,
    rotation_turns,
    unroll_slots,
)


# ── Maths pures ────────────────────────────────────────────────────────────────

def test_rotation_turns():
    assert rotation_turns(5, 1) == 5
    assert rotation_turns(5, 2) == 5   # 5/gcd(5,2)
    assert rotation_turns(4, 2) == 2
    assert rotation_turns(6, 3) == 2
    assert rotation_turns(6, 4) == 3   # 6/gcd(6,4)=3
    assert rotation_turns(1, 1) == 1


def test_sequential_selections_ed_example():
    """N=5, K=2 → item1/item2 · item3/item4 · item5/item1 · item2/item3 · item4/item5."""
    sels = build_turn_selections("one_sequential", 5, 2, rotation_turns(5, 2), seed=0)
    assert sels == [[0, 1], [2, 3], [4, 0], [1, 2], [3, 4]]
    # Chaque item diffusé exactement T*K/N = 2 fois par cycle.
    counts = Counter(i for turn in sels for i in turn)
    assert all(c == 2 for c in counts.values())


def test_random_selections_no_repeat_until_exhaustion():
    n, k = 5, 1
    turns = rotation_turns(n, k)
    sels = build_turn_selections("one_random", n, k, turns, seed=1234)
    flat = [i for turn in sels for i in turn]
    # Une permutation complète : chaque item exactement 1 fois avant re-mélange.
    assert sorted(flat) == list(range(n))
    # Déterminisme : même seed → même déroulé (LAN sync).
    assert sels == build_turn_selections("one_random", n, k, turns, seed=1234)
    # Seed différent (contenu changé) → très probablement un autre ordre.
    other = build_turn_selections("one_random", n, k, turns, seed=99)
    assert sorted(i for t in other for i in t) == list(range(n))


def test_random_selections_boundary_no_back_to_back():
    """N=3, K=2 → T=3 : 6 slots = 2 permutations ; pas de doublon dos à dos à la
    frontière de re-mélange, chaque item joué exactement 2 fois par cycle."""
    n, k = 3, 2
    turns = rotation_turns(n, k)
    assert turns == 3
    for seed in range(40):
        sels = build_turn_selections("one_random", n, k, turns, seed=seed)
        flat = [i for turn in sels for i in turn]
        assert len(flat) == 6
        assert all(c == 2 for c in Counter(flat).values())
        for a, b in zip(flat, flat[1:]):
            assert a != b, f"doublon dos à dos (seed={seed}): {flat}"


def test_unroll_slots_pattern():
    base = [
        {"kind": "inline", "items": ["A"]},
        {"kind": "rotation", "items": ["r1", "r2", "r3"], "mode": "one_sequential",
         "k": 1, "seed": 0},
        {"kind": "inline", "items": ["B"]},
    ]
    out = unroll_slots(base)
    assert out == ["A", "r1", "B", "A", "r2", "B", "A", "r3", "B"]
    # Sans rotation : simple aplatissement.
    assert unroll_slots([{"kind": "inline", "items": ["A", "B"]}]) == ["A", "B"]


def test_rotation_seed_stable():
    assert rotation_seed(7, [1, 2, 3]) == rotation_seed(7, [1, 2, 3])
    assert rotation_seed(7, [1, 2, 3]) != rotation_seed(7, [1, 3, 2])


def test_unroll_protected_slot_marks_all_but_first():
    """no_ads_inside : chaque occurrence du bloc marque no_ad_before sur tout sauf
    son 1er item — y compris quand un même item est 1er à un tour et pas au suivant
    (copie, pas mutation)."""
    a, b, c = {"n": "a"}, {"n": "b"}, {"n": "c"}
    # Inline protégé (mode all) : b et c marqués, a non.
    out = unroll_slots([{"kind": "inline", "items": [a, b, c], "protect": True}])
    assert [i.get("no_ad_before") for i in out] == [None, True, True]
    assert "no_ad_before" not in a and "no_ad_before" not in b  # pas de mutation

    # Rotation protégée N=3 K=2 (séquentiel) : T=3 tours [a,b] [c,a] [b,c] —
    # le 2e de chaque tour est marqué, le 1er jamais (même si marqué ailleurs).
    out = unroll_slots([{
        "kind": "rotation", "items": [a, b, c], "mode": "one_sequential",
        "k": 2, "seed": 0, "protect": True,
    }])
    flags = [(i["n"], bool(i.get("no_ad_before"))) for i in out]
    assert flags == [("a", False), ("b", True), ("c", False), ("a", True),
                     ("b", False), ("c", True)]

    # Non protégé : aucun marquage.
    out = unroll_slots([{"kind": "inline", "items": [a, b], "protect": False}])
    assert all(not i.get("no_ad_before") for i in out)


# ── Fixtures API ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RotOrg", org_slug=f"rot-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def headers(client: AsyncClient, db_session: AsyncSession, org) -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"rot-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_ROT_{uid}", label="Rot", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("playlists", "create"), ("playlists", "read"),
        ("playlists", "edit"), ("playlists", "delete"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _mk_media(db: AsyncSession, org, name: str, dur: int = 10_000) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name=name, media_type="video",
                 storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                 transcode_status="done", duration_ms=dur)
    db.add(m)
    await db.flush()
    return m


async def _mk_child(db: AsyncSession, org, names: list[str],
                    mode: str = "one_sequential", k: int = 1) -> CmsPlaylist:
    child = CmsPlaylist(id_org=org.id_org, playlist_name=f"Rot-{uuid.uuid4().hex[:6]}",
                        rotation_mode=mode, items_per_turn=k)
    db.add(child)
    await db.flush()
    for i, name in enumerate(names):
        m = await _mk_media(db, org, name)
        db.add(CmsPlaylistItem(id_playlist=child.id_playlist, id_media=m.id_media,
                               sort_order=i, duration_ms=10_000))
    await db.commit()
    return child


# ── CRUD : ajout, gardes, publish, suppression ────────────────────────────────

@pytest.mark.asyncio
async def test_add_sub_playlist_and_publish(client: AsyncClient, headers, db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent")
    db_session.add(parent)
    await db_session.commit()
    child = await _mk_child(db_session, org, ["v1", "v2", "v3"])

    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/items",
                          json={"id_child_playlist": child.id_playlist}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["item_type"] == "sub_playlist"
    assert body["id_child_playlist"] == child.id_playlist
    assert body["child_name"] == child.playlist_name
    assert body["child_item_count"] == 3
    assert body["child_rotation_mode"] == "one_sequential"

    # Publish : le brouillon se matérialise en item publié sub_playlist.
    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/publish", headers=headers)
    assert r.status_code == 200, r.text
    rows = (await db_session.execute(
        select(CmsPlaylistItem).where(CmsPlaylistItem.id_playlist == parent.id_playlist)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].item_type == "sub_playlist"
    assert rows[0].id_child_playlist == child.id_playlist
    assert rows[0].id_media is None

    # used_as_child sur la liste.
    r = await client.get("/api/v1/playlists/", headers=headers)
    by_id = {p["id_playlist"]: p for p in r.json()}
    assert by_id[child.id_playlist]["used_as_child"] is True
    assert by_id[parent.id_playlist]["used_as_child"] is False


@pytest.mark.asyncio
async def test_nesting_guards(client: AsyncClient, headers, db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="P1")
    db_session.add(parent)
    await db_session.commit()

    # Auto-référence.
    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/items",
                          json={"id_child_playlist": parent.id_playlist}, headers=headers)
    assert r.status_code == 422

    # id_media ET id_child_playlist ensemble → 422 (schéma).
    m = await _mk_media(db_session, org, "solo")
    await db_session.commit()
    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/items",
                          json={"id_media": m.id_media, "id_child_playlist": 999},
                          headers=headers)
    assert r.status_code == 422

    # Parent → child publié ; ajouter une sous-playlist À child = 2 niveaux → 422.
    child = await _mk_child(db_session, org, ["a", "b"])
    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/items",
                          json={"id_child_playlist": child.id_playlist}, headers=headers)
    assert r.status_code == 201
    r = await client.post(f"/api/v1/playlists/{parent.id_playlist}/publish", headers=headers)
    assert r.status_code == 200
    other = await _mk_child(db_session, org, ["c"])
    r = await client.post(f"/api/v1/playlists/{child.id_playlist}/items",
                          json={"id_child_playlist": other.id_playlist}, headers=headers)
    assert r.status_code == 422

    # Une playlist qui CONTIENT une sous-playlist ne peut pas s'imbriquer ailleurs.
    grand = CmsPlaylist(id_org=org.id_org, playlist_name="Grand")
    db_session.add(grand)
    await db_session.commit()
    r = await client.post(f"/api/v1/playlists/{grand.id_playlist}/items",
                          json={"id_child_playlist": parent.id_playlist}, headers=headers)
    assert r.status_code == 422

    # Suppression de child bloquée tant que référencée.
    r = await client.delete(f"/api/v1/playlists/{child.id_playlist}", headers=headers)
    assert r.status_code == 409


# ── Payload player : déroulé du cycle ─────────────────────────────────────────

async def _scene(db: AsyncSession, org, parent: CmsPlaylist) -> CmsPlayer:
    player = CmsPlayer(id_org=org.id_org, player_name="P", player_os="linux")
    db.add(player)
    await db.flush()
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=parent.id_playlist, is_active=True)
    db.add(sched)
    await db.flush()
    db.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player.id_player),
    ])
    await db.commit()
    return player


@pytest.mark.asyncio
async def test_sync_payload_unrolls_sequential(db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Loop", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    home = await _mk_media(db_session, org, "home", 30_000)
    child = await _mk_child(db_session, org, ["r1", "r2", "r3"])
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    names = [i["media"]["media_name"] for i in payload["items"]]
    # T=3 tours : home r1 · home r2 · home r3.
    assert names == ["home", "r1", "home", "r2", "home", "r3"]
    # Wall-clock calculé sur la liste déroulée.
    assert payload["start_index"] is not None
    assert 0 <= payload["start_index"] < len(names)


@pytest.mark.asyncio
async def test_sync_payload_random_two_per_turn(db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Loop2", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    home = await _mk_media(db_session, org, "home", 30_000)
    child = await _mk_child(db_session, org, ["r1", "r2", "r3", "r4", "r5"],
                            mode="one_random", k=2)
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    names = [i["media"]["media_name"] for i in payload["items"]]
    # T = 5 tours × (1 home + 2 rotation) = 15 items ; chaque rX joué exactement 2×.
    assert len(names) == 15
    assert names.count("home") == 5
    rot_counts = Counter(n for n in names if n.startswith("r"))
    assert all(c == 2 for c in rot_counts.values()) and len(rot_counts) == 5
    # Déterminisme : un second resolve produit exactement le même déroulé (LAN sync).
    payload2 = await _resolve_sync_payload(db_session, player.id_player)
    assert [i["media"]["media_name"] for i in payload2["items"]] == names


@pytest.mark.asyncio
async def test_sync_payload_no_ads_inside_marks_block(db_session, org):
    """Sous-playlist no_ads_inside : dans le payload, tout le bloc sauf son 1er item
    porte no_ad_before → splice_ad_items n'insérera jamais de pub dedans."""
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="NoAds", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    home = await _mk_media(db_session, org, "home", 30_000)
    child = await _mk_child(db_session, org, ["b1", "b2", "b3"], mode="all")
    child.no_ads_inside = True
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    flags = [(i["media"]["media_name"], bool(i.get("no_ad_before")))
             for i in payload["items"]]
    assert flags == [("home", False), ("b1", False), ("b2", True), ("b3", True)]

    # Feasibility : le bloc protégé = 1 frontière (2 au total avec home),
    # durée totale complète (30 + 3×10 s).
    from app.services.campaign_feasibility import _playlist_loop
    loop = await _playlist_loop(db_session, parent.id_playlist, {})
    assert loop == (2, 60_000)


@pytest.mark.asyncio
async def test_feasibility_counts_unprotected_child(db_session, org):
    """Sans no_ads_inside, la sous-playlist apporte ses frontières (trou historique
    corrigé : la feasibility ignorait les sous-playlists)."""
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Feas", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    home = await _mk_media(db_session, org, "home", 30_000)
    child = await _mk_child(db_session, org, ["c1", "c2", "c3", "c4"],
                            mode="one_sequential", k=2)
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()

    from app.services.campaign_feasibility import _playlist_loop
    # Rotation K=2 : contribution par tour = 2 items / 2×10 s → B=1+2, H=30+20 s.
    assert await _playlist_loop(db_session, parent.id_playlist, {}) == (3, 50_000)


@pytest.mark.asyncio
async def test_sync_payload_mode_all_inlines(db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Loop3", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    home = await _mk_media(db_session, org, "home", 30_000)
    child = await _mk_child(db_session, org, ["r1", "r2"], mode="all")
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    names = [i["media"]["media_name"] for i in payload["items"]]
    assert names == ["home", "r1", "r2"]


# ── Rotation via le BROUILLON (décision Ed 2026-07-25 ④) ──────────────────────
# Avant : rotation_mode/items_per_turn/no_ads_inside étaient écrits DIRECTEMENT dans les
# colonnes de la playlist et poussés aux players (force_sync), alors que le moindre
# changement d'item attend « Publier ». Deux réglages voisins, deux comportements.
# Désormais ils transitent par draft_settings et n'atteignent l'écran qu'à la publication.

@pytest.mark.asyncio
async def test_rotation_settings_go_through_draft(client: AsyncClient, headers, db_session, org):
    child = await _mk_child(db_session, org, ["v1", "v2", "v3"], mode="all", k=1)

    r = await client.put(f"/api/v1/playlists/{child.id_playlist}",
                         json={"rotation_mode": "one_random", "items_per_turn": 2},
                         headers=headers)
    assert r.status_code == 200, r.text

    # 1. Les colonnes PUBLIÉES (ce que lisent les players via ws.py) n'ont pas bougé.
    await db_session.refresh(child)
    assert child.rotation_mode == "all"
    assert child.items_per_turn == 1
    assert child.draft_settings == {"rotation_mode": "one_random", "items_per_turn": 2}

    # 2. L'ÉDITEUR, lui, montre le brouillon + signale qu'il reste à publier.
    detail = (await client.get(f"/api/v1/playlists/{child.id_playlist}", headers=headers)).json()
    assert detail["rotation_mode"] == "one_random"
    assert detail["items_per_turn"] == 2
    assert detail["has_draft_changes"] is True

    # 3. La LISTE reflète l'état publié (= ce qui est à l'écran) + le badge.
    row = {p["id_playlist"]: p for p in
           (await client.get("/api/v1/playlists/", headers=headers)).json()}[child.id_playlist]
    assert row["rotation_mode"] == "all"
    assert row["has_draft_changes"] is True

    # 4. Publication → les colonnes basculent, le brouillon est soldé.
    r = await client.post(f"/api/v1/playlists/{child.id_playlist}/publish", headers=headers)
    assert r.status_code == 200, r.text
    await db_session.refresh(child)
    assert child.rotation_mode == "one_random"
    assert child.items_per_turn == 2
    assert child.draft_settings is None
    assert r.json()["has_draft_changes"] is False


@pytest.mark.asyncio
async def test_rotation_draft_is_discardable_and_self_cancelling(
    client: AsyncClient, headers, db_session, org
):
    child = await _mk_child(db_session, org, ["v1", "v2"], mode="all", k=1)
    url = f"/api/v1/playlists/{child.id_playlist}"

    # Revenir à la valeur publiée ne laisse pas un brouillon fantôme (sinon la playlist
    # resterait « à publier » pour un changement qui n'existe plus).
    await client.put(url, json={"items_per_turn": 3}, headers=headers)
    await client.put(url, json={"items_per_turn": 1}, headers=headers)
    await db_session.refresh(child)
    assert child.draft_settings is None

    # Abandon du brouillon : retour à la version publiée.
    await client.put(url, json={"rotation_mode": "one_sequential"}, headers=headers)
    r = await client.post(f"{url}/discard", headers=headers)
    assert r.status_code == 204, r.text
    await db_session.refresh(child)
    assert child.draft_settings is None
    assert child.rotation_mode == "all"


@pytest.mark.asyncio
async def test_rotation_draft_alone_does_not_reach_players(db_session, org):
    """Le payload player ignore un réglage non publié — c'est tout l'objet de ④."""
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="LoopDraft", sync_mode="wall_clock")
    db_session.add(parent)
    await db_session.flush()
    child = await _mk_child(db_session, org, ["r1", "r2"], mode="all")
    db_session.add(CmsPlaylistItem(
        id_playlist=parent.id_playlist, id_media=None, item_type="sub_playlist",
        id_child_playlist=child.id_playlist, sort_order=0))
    # Rotation « 1 par tour » en attente de publication.
    child.draft_settings = {"rotation_mode": "one_sequential", "items_per_turn": 1}
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    # mode publié = all → les 2 items sont inlinés, la rotation ne s'applique pas encore.
    assert [i["media"]["media_name"] for i in payload["items"]] == ["r1", "r2"]
