"""
Tests Sprint 1.4 — Templates, Playlists & Schedules (§XIII).

Couvre :
  - test_create_and_list_templates
  - test_create_and_list_playlists
  - test_playlist_item_reorder
  - test_schedule_target_player_assignment
  - test_schedule_priority_resolution
"""

import json
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"sched-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="SchedOrg", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def user_with_content_perm(
    db_session: AsyncSession, org: CmsOrganization
) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"content-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    role_key = f"CMS_CONTENT_{uid}"
    role = CmsRole(
        id_org=org.id_org,
        role_key=role_key,
        label="Content Manager",
        is_system=False,
    )
    db_session.add(role)
    await db_session.flush()

    for module, operation in [
        ("templates", "create"),
        ("templates", "read"),
        ("templates", "edit"),
        ("templates", "delete"),
        ("playlists", "create"),
        ("playlists", "read"),
        ("playlists", "edit"),
        ("playlists", "delete"),
        ("schedules", "create"),
        ("schedules", "read"),
        ("schedules", "edit"),
        ("schedules", "delete"),
        ("players", "read"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (
            await db_session.execute(
                select(CmsPermission).where(
                    CmsPermission.module == module, CmsPermission.operation == operation
                )
            )
        ).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))

    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()

    return user, user.email


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, user_with_content_perm) -> str:
    _, email = user_with_content_perm
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password1!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    m = CmsMedia(
        id_org=org.id_org,
        media_name="test-video",
        media_type="video",
        storage_key=f"test/{uuid.uuid4().hex}.mp4",
        checksum_sha256="abc123",
        transcode_status="done",
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


# ── Tests Templates ────────────────────────────────────────────────────────────

async def test_create_and_list_templates(client: AsyncClient, auth_token: str) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    create_resp = await client.post(
        "/api/v1/templates",
        json={
            "template_name": "Full Screen",
            "layout": {
                "layout_type": "full",
                "zones": [{"index": 0, "x": 0, "y": 0, "w": 1920, "h": 1080, "label": "Main"}],
            },
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert data["template_name"] == "Full Screen"
    assert data["layout"]["layout_type"] == "full"

    list_resp = await client.get("/api/v1/templates", headers=headers)
    assert list_resp.status_code == 200
    ids = [t["id_template"] for t in list_resp.json()]
    assert data["id_template"] in ids


# ── Tests Playlists ────────────────────────────────────────────────────────────

async def test_create_and_list_playlists(client: AsyncClient, auth_token: str) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    create_resp = await client.post(
        "/api/v1/playlists",
        json={"playlist_name": "Morning Loop", "description": "Boucle matinale"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    pl = create_resp.json()
    assert pl["playlist_name"] == "Morning Loop"

    list_resp = await client.get("/api/v1/playlists/", headers=headers)
    assert list_resp.status_code == 200
    assert any(p["id_playlist"] == pl["id_playlist"] for p in list_resp.json())


async def test_playlist_item_reorder(
    client: AsyncClient, auth_token: str, media_item: CmsMedia
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    pl_resp = await client.post(
        "/api/v1/playlists",
        json={"playlist_name": "Reorder Test"},
        headers=headers,
    )
    pl_id = pl_resp.json()["id_playlist"]

    item_ids = []
    for i in range(3):
        r = await client.post(
            f"/api/v1/playlists/{pl_id}/items",
            json={"id_media": media_item.id_media, "sort_order": i},
            headers=headers,
        )
        assert r.status_code == 201
        item_ids.append(r.json()["id_item"])

    # Inverse l'ordre
    reorder_payload = {"items": [
        {"id_item": item_ids[0], "sort_order": 2},
        {"id_item": item_ids[1], "sort_order": 1},
        {"id_item": item_ids[2], "sort_order": 0},
    ]}
    reorder_resp = await client.put(
        f"/api/v1/playlists/{pl_id}/items/reorder",
        json=reorder_payload,
        headers=headers,
    )
    assert reorder_resp.status_code == 200
    reordered = reorder_resp.json()
    assert reordered[0]["id_item"] == item_ids[2]
    assert reordered[1]["id_item"] == item_ids[1]
    assert reordered[2]["id_item"] == item_ids[0]


async def test_playlist_rejects_audio_media_422(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Un média audio pur n'a pas de rendu écran → refusé dans une playlist standard (§XIX)."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    audio = CmsMedia(
        id_org=org.id_org,
        media_name="jingle.mp3",
        media_type="audio",
        storage_key=f"test/{uuid.uuid4().hex}.mp3",
        checksum_sha256=uuid.uuid4().hex,
        transcode_status="done",
    )
    db_session.add(audio)
    await db_session.commit()
    await db_session.refresh(audio)

    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "No Audio"}, headers=headers,
    )).json()["id_playlist"]
    resp = await client.post(
        f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": audio.id_media, "sort_order": 0},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_playlist_bulk_add_items(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Ajout multi-sélection : 2 vidéos d'un coup, audio + id introuvable ignorés, ordre conservé."""
    headers = {"Authorization": f"Bearer {auth_token}"}

    def _mk(name, mtype):
        m = CmsMedia(
            id_org=org.id_org, media_name=name, media_type=mtype,
            storage_key=f"test/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
            transcode_status="done",
        )
        db_session.add(m)
        return m

    v1, v2, audio = _mk("a.mp4", "video"), _mk("b.mp4", "video"), _mk("j.mp3", "audio")
    db_session.add_all([v1, v2, audio])
    await db_session.commit()
    for m in (v1, v2, audio):
        await db_session.refresh(m)

    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Bulk"}, headers=headers,
    )).json()["id_playlist"]

    resp = await client.post(
        f"/api/v1/playlists/{pl_id}/items/bulk",
        json={"id_medias": [v1.id_media, audio.id_media, v2.id_media, 999999]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    items = resp.json()
    # Audio + id introuvable ignorés → seulement les 2 vidéos, dans l'ordre demandé.
    assert [it["id_media"] for it in items] == [v1.id_media, v2.id_media]


async def test_playlist_sync_ready(
    client: AsyncClient, auth_token: str, media_item: CmsMedia
) -> None:
    """sync_ready (#1b LAN Sync Hardening) : wall_clock + tous les items ont une durée résolue."""
    headers = {"Authorization": f"Bearer {auth_token}"}

    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Sync Ready Test"}, headers=headers,
    )).json()["id_playlist"]

    # Playlist vide → pas synchronisable (aucun item).
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    assert detail["sync_ready"] is False
    assert detail["sync_mode"] == "wall_clock"

    # Item avec duration_ms explicite → synchronisable (wall_clock par défaut).
    # Staging : l'ajout va au brouillon ; on publie pour que l'état soit servi/listé.
    await client.post(
        f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 0, "duration_ms": 5000},
        headers=headers,
    )
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=headers)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    assert detail["sync_ready"] is True
    # La liste expose aussi sync_ready (état publié).
    lst = (await client.get("/api/v1/playlists/", headers=headers)).json()
    assert next(p["sync_ready"] for p in lst if p["id_playlist"] == pl_id) is True

    # Mode loop → plus synchronisable.
    await client.put(f"/api/v1/playlists/{pl_id}", json={"sync_mode": "loop"}, headers=headers)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    assert detail["sync_ready"] is False

    # Retour wall_clock + 2ᵉ item SANS durée (média sans duration_ms) → plus synchronisable.
    await client.put(f"/api/v1/playlists/{pl_id}", json={"sync_mode": "wall_clock"}, headers=headers)
    await client.post(
        f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 1},
        headers=headers,
    )
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    assert detail["sync_ready"] is False


async def test_simulate_timeline_honors_item_rules(
    client: AsyncClient, auth_token: str, media_item: CmsMedia
) -> None:
    """La timeline prévisionnelle honore les règles : un item limité à 18h-19h n'apparaît
    pas à 10h mais apparaît à 18h ; l'item perpétuel apparaît tout le temps."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Timeline Test"}, headers=headers,
    )).json()["id_playlist"]

    # Item A perpétuel (dur 5 min) + item B limité 18h-19h (dur 5 min)
    await client.post(f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 0, "duration_ms": 300000}, headers=headers)
    await client.post(f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 1, "duration_ms": 300000}, headers=headers)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    item_b = detail["items"][1]["id_item"]
    await client.put(f"/api/v1/playlists/{pl_id}/items/{item_b}/rules",
        json=[{"rule_type": "weekly", "time_start": "18:00:00", "time_end": "19:00:00", "scope": "default"}],
        headers=headers)
    # Staging : la simulation reflète l'état PUBLIÉ → on publie puis on relit les id_item réels.
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=headers)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    item_b = detail["items"][1]["id_item"]

    # Timeline du jour à partir de 10h : court jusqu'à la fin de journée.
    sim = (await client.post(f"/api/v1/playlists/{pl_id}/simulate-timeline",
        json={"date": "2026-06-08", "start_time": "10:00"}, headers=headers)).json()
    assert sim["sync_mode"] == "wall_clock"
    assert len(sim["segments"]) > 0
    # Avant 18h : B est hors fenêtre → seul A joue.
    early = [s for s in sim["segments"] if s["start"] < "18:00:00"]
    assert early and all(s["id_item"] != item_b for s in early)
    # B apparaît dans sa fenêtre 18h-19h.
    assert any(s["id_item"] == item_b for s in sim["segments"])

    # Timeline démarrée à 18h : B joue dès le départ.
    evening = (await client.post(f"/api/v1/playlists/{pl_id}/simulate-timeline",
        json={"date": "2026-06-08", "start_time": "18:00"}, headers=headers)).json()
    assert any(s["id_item"] == item_b for s in evening["segments"])


async def test_simulate_timeline_is_playlist_only_and_day_sim_resolves_events(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, media_item: CmsMedia,
) -> None:
    """La simulation PLAYLIST est pure (ignore events/programmes) ; la simulation
    JOURNÉE du player résout l'event programmé dans la piste vidéo à son heure."""
    from app.models.event import CmsEvent
    from app.models.player import CmsPlayer

    headers = {"Authorization": f"Bearer {auth_token}"}
    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Event Overlay"}, headers=headers,
    )).json()["id_playlist"]
    await client.post(f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 0, "duration_ms": 300000}, headers=headers)

    player = CmsPlayer(id_org=org.id_org, player_name="Lobby")
    db_session.add(player)
    await db_session.flush()
    event = CmsEvent(
        id_org=org.id_org, event_name="Midi Promo", event_type="scheduled",
        event_kind="content", status="inactive", priority=80, id_playlist=pl_id,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        trigger_config={"logic": "AND", "conditions": [
            {"source": "schedule", "time_start": "12:00", "time_end": "13:00"},
        ]},
    )
    db_session.add(event)
    await db_session.commit()

    # Sim PLAYLIST : aucun segment d'event, même avec le player ciblé (playlist seule).
    sim = (await client.post(f"/api/v1/playlists/{pl_id}/simulate-timeline",
        json={"date": "2026-06-08", "start_time": "00:00", "player_id": player.id_player},
        headers=headers)).json()
    assert all(s.get("kind") != "event" for s in sim["segments"])

    # Sim JOURNÉE du player : l'event résout la piste vidéo dans sa fenêtre 12h-13h.
    day = (await client.post(f"/api/v1/players/{player.id_player}/simulate-day",
        json={"date": "2026-06-08"}, headers=headers)).json()
    ev_segs = [s for s in day["video"] if s["source"] == "event"]
    assert ev_segs, "l'event programmé doit apparaître dans la piste vidéo de la journée"
    assert ev_segs[0]["name"] == "Midi Promo"
    assert ev_segs[0]["start"] == "12:00"
    assert ev_segs[0]["end"] == "13:00"


# ── Tests Schedules ────────────────────────────────────────────────────────────

async def test_schedule_target_player_assignment(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    pl_resp = await client.post(
        "/api/v1/playlists",
        json={"playlist_name": "Target Test PL"},
        headers=headers,
    )
    pl_id = pl_resp.json()["id_playlist"]

    # Player RÉEL : l'ancien test ciblait l'id 42, inexistant — c'est exactement le
    # défaut fermé par l'audit menu ⑧ (cible fantôme acceptée en 201, jamais résolue).
    target_player = CmsPlayer(id_org=org.id_org, player_name="Target-42")
    db_session.add(target_player)
    await db_session.commit()

    sched_resp = await client.post(
        "/api/v1/schedules",
        json={
            "schedule_name": "Target Test Schedule",
            "id_playlist": pl_id,
            "priority": 5,
            "rules": [{"rule_type": "always"}],
            "targets": [{"target_type": "player", "target_id": target_player.id_player}],
        },
        headers=headers,
    )
    assert sched_resp.status_code == 201
    sched = sched_resp.json()
    assert sched["priority"] == 5
    assert len(sched["rules"]) == 1
    assert sched["rules"][0]["rule_type"] == "always"
    assert len(sched["targets"]) == 1
    assert sched["targets"][0]["target_id"] == target_player.id_player


async def test_schedule_assignment_triggers_conformance_advisory(
    client: AsyncClient, auth_token: str, db_session: AsyncSession,
    org: CmsOrganization, monkeypatch,
) -> None:
    """Bug conformité #2 : affecter une playlist 4K PRÉ-CONSTRUITE à une audience FHD via
    create_schedule doit déclencher l'alerte + l'auto-rendition (était câblé qu'à la publish)."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    media = CmsMedia(id_org=org.id_org, media_name="wall4k", media_type="video",
                     storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
                     width=3840, height=2160, source="upload", transcode_status="done")
    player = CmsPlayer(id_org=org.id_org, player_name="fhd-panel", player_os="linux",
                       display_config={"screen_resolution": "1920x1080"})
    db_session.add_all([media, player])
    await db_session.flush()
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Wall PL")
    db_session.add(pl)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    await db_session.commit()

    calls: list[tuple] = []
    monkeypatch.setattr("app.workers.media_worker.generate_rendition.delay",
                        lambda *a, **k: calls.append(a))

    resp = await client.post("/api/v1/schedules", headers=headers, json={
        "schedule_name": "Wall Sched", "id_playlist": pl.id_playlist,
        "rules": [{"rule_type": "always"}],
        "targets": [{"target_type": "player", "target_id": player.id_player}],
    })
    assert resp.status_code == 201
    advisory = json.loads(resp.headers["X-Rendition-Advisory"])
    assert advisory == [{"id_media": media.id_media, "media_height": 2160,
                         "target_height": 1080, "action": "generating"}]
    assert calls == [(media.id_media, "fhd")]


async def test_update_item_duration_in_draft(
    client: AsyncClient, auth_token: str, media_item: CmsMedia
) -> None:
    """PATCH durée d'exposition d'un item du brouillon (image/PDF sans durée native)."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    pl_id = (await client.post("/api/v1/playlists",
                               json={"playlist_name": "Dur"}, headers=headers)).json()["id_playlist"]
    add = await client.post(f"/api/v1/playlists/{pl_id}/items",
                            json={"id_media": media_item.id_media, "sort_order": 0}, headers=headers)
    assert add.status_code in (200, 201)
    id_item = add.json()["id_item"]

    # Régler la durée à 30 s
    r = await client.patch(f"/api/v1/playlists/{pl_id}/items/{id_item}",
                           json={"duration_ms": 30000}, headers=headers)
    assert r.status_code == 200
    assert {i["id_item"]: i for i in r.json()}[id_item]["duration_ms"] == 30000
    # GET (sert le brouillon) reflète la durée
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=headers)).json()
    assert next(i for i in detail["items"] if i["id_item"] == id_item)["duration_ms"] == 30000

    # Vider → null (repli durée par défaut player)
    r2 = await client.patch(f"/api/v1/playlists/{pl_id}/items/{id_item}",
                            json={"duration_ms": None}, headers=headers)
    assert {i["id_item"]: i for i in r2.json()}[id_item]["duration_ms"] is None

    # < 1 s rejeté (422) ; item inexistant → 404
    assert (await client.patch(f"/api/v1/playlists/{pl_id}/items/{id_item}",
                               json={"duration_ms": 500}, headers=headers)).status_code == 422
    assert (await client.patch(f"/api/v1/playlists/{pl_id}/items/999999",
                               json={"duration_ms": 30000}, headers=headers)).status_code == 404


async def test_schedule_priority_resolution(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    pl_lo_resp = await client.post(
        "/api/v1/playlists",
        json={"playlist_name": "Low Priority PL"},
        headers=headers,
    )
    pl_hi_resp = await client.post(
        "/api/v1/playlists",
        json={"playlist_name": "High Priority PL"},
        headers=headers,
    )
    pl_lo_id = pl_lo_resp.json()["id_playlist"]
    pl_hi_id = pl_hi_resp.json()["id_playlist"]

    # Player RÉEL (l'ancien id 99 n'existait pas : cible fantôme + current-schedule
    # désormais gardé par l'org — audit menu ⑧).
    resolved_player = CmsPlayer(id_org=org.id_org, player_name="Resolve-99")
    db_session.add(resolved_player)
    await db_session.commit()
    player_id = resolved_player.id_player

    # Schedule basse priorité — toujours actif
    await client.post(
        "/api/v1/schedules",
        json={
            "schedule_name": "Low Sched",
            "id_playlist": pl_lo_id,
            "priority": 1,
            "rules": [{"rule_type": "always"}],
            "targets": [{"target_type": "player", "target_id": player_id}],
        },
        headers=headers,
    )

    # Schedule haute priorité — toujours actif
    await client.post(
        "/api/v1/schedules",
        json={
            "schedule_name": "High Sched",
            "id_playlist": pl_hi_id,
            "priority": 10,
            "rules": [{"rule_type": "always"}],
            "targets": [{"target_type": "player", "target_id": player_id}],
        },
        headers=headers,
    )

    resolve_resp = await client.get(
        f"/api/v1/players/{player_id}/current-schedule",
        headers=headers,
    )
    assert resolve_resp.status_code == 200
    resolved = resolve_resp.json()
    assert resolved["id_playlist"] == pl_hi_id
    assert resolved["priority"] == 10
    assert resolved["schedule_name"] == "High Sched"


# ── Staging / bouton « Publier » (#1) ─────────────────────────────────────────────

async def test_staging_edits_isolated_until_publish(client, auth_token, media_item):
    """Une édition va au BROUILLON : visible dans le détail (éditeur) mais l'état
    PUBLIÉ (liste/agrégats servis aux players) ne change qu'à « Publier »."""
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Staging"}, headers=h
    )).json()["id_playlist"]

    await client.post(f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 0, "duration_ms": 5000}, headers=h)

    # Détail (éditeur) = brouillon : l'item y est, drapeau de brouillon levé.
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert len(detail["items"]) == 1
    assert detail["has_draft_changes"] is True

    # Liste (publié) : rien encore publié → pas synchronisable, badge brouillon.
    row = next(p for p in (await client.get("/api/v1/playlists/", headers=h)).json()
               if p["id_playlist"] == pl_id)
    assert row["has_draft_changes"] is True
    assert row["sync_ready"] is False  # publié = vide
    assert row["total_duration_ms"] is None

    # Publication → l'item devient publié, le brouillon est effacé.
    await client.post(f"/api/v1/playlists/{pl_id}/publish", headers=h)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert len(detail["items"]) == 1
    assert detail["has_draft_changes"] is False
    row = next(p for p in (await client.get("/api/v1/playlists/", headers=h)).json()
               if p["id_playlist"] == pl_id)
    assert row["has_draft_changes"] is False
    assert row["sync_ready"] is True


async def test_staging_discard_reverts_to_published(client, auth_token, media_item):
    """« Annuler » jette le brouillon et revient à la version publiée."""
    h = {"Authorization": f"Bearer {auth_token}"}
    pl_id = (await client.post(
        "/api/v1/playlists", json={"playlist_name": "Discard"}, headers=h
    )).json()["id_playlist"]
    await client.post(f"/api/v1/playlists/{pl_id}/items",
        json={"id_media": media_item.id_media, "sort_order": 0}, headers=h)
    assert (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()["has_draft_changes"] is True

    await client.post(f"/api/v1/playlists/{pl_id}/discard", headers=h)
    detail = (await client.get(f"/api/v1/playlists/{pl_id}", headers=h)).json()
    assert detail["has_draft_changes"] is False
    assert len(detail["items"]) == 0  # rien n'avait été publié


async def test_hdmi_compat_check(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization,
) -> None:
    """POST /schedules/hdmi-check : playlist avec item hdmi_input + cibles player/groupe →
    liste les players SANS entrée HDMI physique (warning d'affectation, non bloquant)."""
    from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember

    hdmi = CmsMedia(id_org=org.id_org, media_name="HDMI in", media_type="hdmi_input",
                    storage_key="", checksum_sha256="")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL-hdmi")
    bs = CmsPlayer(id_org=org.id_org, player_name="xt", player_os="brightsign",
                   capabilities={"bs_model": "XT1144"})
    nuc = CmsPlayer(id_org=org.id_org, player_name="nuc", player_os="linux")
    grp = CmsPlayerGroup(id_org=org.id_org, group_name="G-hdmi")
    db_session.add_all([hdmi, pl, bs, nuc, grp])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=hdmi.id_media,
                                   sort_order=0, duration_ms=30000))
    db_session.add(CmsPlayerGroupMember(id_group=grp.id_group, id_player=nuc.id_player))
    await db_session.commit()

    # Cible = BS capable (direct) + NUC via groupe → seul le NUC est incompatible.
    r = await client.post("/api/v1/schedules/hdmi-check",
                          headers={"Authorization": f"Bearer {auth_token}"},
                          json={"id_playlist": pl.id_playlist, "targets": [
                              {"target_type": "player", "target_id": bs.id_player},
                              {"target_type": "player_group", "target_id": grp.id_group},
                          ]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["has_hdmi_item"] is True
    assert [p["id_player"] for p in data["incompatible_players"]] == [nuc.id_player]

    # Playlist SANS item hdmi → has_hdmi_item False, pas de liste.
    pl2 = CmsPlaylist(id_org=org.id_org, playlist_name="PL-plain")
    db_session.add(pl2)
    await db_session.commit()
    r = await client.post("/api/v1/schedules/hdmi-check",
                          headers={"Authorization": f"Bearer {auth_token}"},
                          json={"id_playlist": pl2.id_playlist, "targets": [
                              {"target_type": "player", "target_id": nuc.id_player}]})
    assert r.status_code == 200
    assert r.json() == {"has_hdmi_item": False, "incompatible_players": []}
