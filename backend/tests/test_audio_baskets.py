"""Tests Audio Baskets (§XIX) — Sprint 2.5 (lot 1 : paniers + items + config player)."""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

async def _make_org(db: AsyncSession, prefix: str) -> CmsOrganization:
    o = CmsOrganization(org_name=f"{prefix}Org", org_slug=f"{prefix}-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


async def _make_user_with_audio_perms(db: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    """Utilisateur avec audio_baskets:read/control/configure + players:read."""
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"audio-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    role_key = f"CMS_AUDIO_TEST_{uid}"
    await db.execute(
        pg_insert(CmsRole)
        .values(role_key=role_key, label="Audio Test Role", is_system=False, is_active=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()

    for module, op in [
        ("audio_baskets", "read"),
        ("audio_baskets", "control"),
        ("audio_baskets", "configure"),
        ("players", "read"),
    ]:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=op)
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == op
            )
        )).scalar_one()
        await db.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing()
        )

    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)

    token = create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"}
    )
    return user, token


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session, "audio")


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session, "audiob")


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    return await _make_user_with_audio_perms(db_session, org)


@pytest_asyncio.fixture
async def other_org_token(db_session: AsyncSession, org_b: CmsOrganization) -> tuple[CmsUser, str]:
    return await _make_user_with_audio_perms(db_session, org_b)


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org: CmsOrganization) -> CmsPlayer:
    p = CmsPlayer(id_org=org.id_org, player_name="Audio Player", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def audio_media(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    media = CmsMedia(
        id_org=org.id_org,
        media_name=f"track-{uuid.uuid4().hex[:8]}.mp3",
        media_type="audio",
        mime_type="audio/mpeg",
        storage_key=f"audio/{uuid.uuid4().hex}.mp3",
        checksum_sha256=uuid.uuid4().hex,
        duration_ms=180000,
        source="upload",
        transcode_status="done",
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)
    return media


# ── Helper ─────────────────────────────────────────────────────────────────────

def _basket_payload(**overrides) -> dict:
    base = {
        "basket_name": "Musique Pop National",
        "basket_type": "music",
        "basket_scope": "national",
        "ducking_config": {},
    }
    base.update(overrides)
    return base


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_create_and_list_basket(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["basket_name"] == "Musique Pop National"
    assert data["basket_type"] == "music"
    assert data["item_count"] == 0

    resp = await client.get("/api/v1/audio-baskets", headers=headers)
    assert resp.status_code == 200
    assert any(b["id_basket"] == data["id_basket"] for b in resp.json())


async def test_create_message_basket_with_ducking(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    ducking = {"enabled": True, "target_pct": 20, "fade_in_ms": 500, "fade_out_ms": 1500}
    resp = await client.post(
        "/api/v1/audio-baskets",
        json=_basket_payload(basket_name="Messages Promo", basket_type="message", ducking_config=ducking),
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["ducking_config"] == ducking


async def test_update_basket(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]

    resp = await client.put(
        f"/api/v1/audio-baskets/{id_basket}",
        json={"basket_name": "Renamed", "is_active": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["basket_name"] == "Renamed"
    assert resp.json()["is_active"] is False


async def test_delete_basket(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]

    resp = await client.delete(f"/api/v1/audio-baskets/{id_basket}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/audio-baskets/{id_basket}", headers=headers)
    assert resp.status_code == 404


async def test_add_and_list_basket_items(client: AsyncClient, admin_token, audio_media: CmsMedia) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]

    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items",
        json={"id_media": audio_media.id_media, "weight": 2},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["weight"] == 2
    assert item["media_name"] == audio_media.media_name
    assert item["duration_ms"] == 180000

    resp = await client.get(f"/api/v1/audio-baskets/{id_basket}/items", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.get(f"/api/v1/audio-baskets/{id_basket}", headers=headers)
    assert resp.json()["item_count"] == 1
    # Durée totale (vignettes, 2026-08-15) = somme des durées natives des pistes.
    assert resp.json()["total_duration_ms"] == 180000

    resp = await client.get("/api/v1/audio-baskets", headers=headers)
    row = next(b for b in resp.json() if b["id_basket"] == id_basket)
    assert row["item_count"] == 1
    assert row["total_duration_ms"] == 180000


async def test_basket_shuffle_create_and_update(client: AsyncClient, admin_token) -> None:
    """Le flag shuffle est persistant à la création et modifiable."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(shuffle=True), headers=headers,
    )).json()
    assert created["shuffle"] is True
    upd = (await client.put(
        f"/api/v1/audio-baskets/{created['id_basket']}", json={"shuffle": False}, headers=headers,
    )).json()
    assert upd["shuffle"] is False


async def test_basket_item_rule_patch_and_runtime_filter(
    client: AsyncClient, admin_token, audio_media: CmsMedia, db_session: AsyncSession,
) -> None:
    """PATCH pose une règle 18h-19h ; le runtime ne retient l'item que dans sa fenêtre."""
    from datetime import datetime
    from app.api.v1.endpoints.ws import _build_basket_items

    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]
    id_item = (await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items",
        json={"id_media": audio_media.id_media}, headers=headers,
    )).json()["id_item"]

    patched = (await client.patch(
        f"/api/v1/audio-baskets/{id_basket}/items/{id_item}",
        json={"rule_time_start": "18:00:00", "rule_time_end": "19:00:00"}, headers=headers,
    )).json()
    assert patched["rule_time_start"] == "18:00:00"

    # Runtime : hors fenêtre (10h) → exclu ; dans la fenêtre (18h30) → inclus.
    out = await _build_basket_items(db_session, id_basket, datetime(2026, 6, 8, 10, 0))
    assert all(i["id_media"] != audio_media.id_media for i in out)
    inside = await _build_basket_items(db_session, id_basket, datetime(2026, 6, 8, 18, 30))
    assert any(i["id_media"] == audio_media.id_media for i in inside)


async def test_add_item_unknown_media_404(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]

    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items",
        json={"id_media": 999999},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_add_non_audio_item_rejected_422(
    client: AsyncClient, admin_token, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Un média visuel (vidéo/image) ne peut pas entrer dans un panier audio (§XIX)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    video = CmsMedia(
        id_org=org.id_org,
        media_name=f"clip-{uuid.uuid4().hex[:8]}.mp4",
        media_type="video",
        mime_type="video/mp4",
        storage_key=f"video/{uuid.uuid4().hex}.mp4",
        checksum_sha256=uuid.uuid4().hex,
        source="upload",
        transcode_status="done",
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]
    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items",
        json={"id_media": video.id_media},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_set_player_baskets_and_ratio_validation(client: AsyncClient, admin_token, player: CmsPlayer) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    b1 = (await client.post("/api/v1/audio-baskets", json=_basket_payload(basket_name="B1"), headers=headers)).json()["id_basket"]
    b2 = (await client.post("/api/v1/audio-baskets", json=_basket_payload(basket_name="B2"), headers=headers)).json()["id_basket"]

    # Somme > 100 → 422
    resp = await client.put(
        f"/api/v1/players/{player.id_player}/baskets",
        json=[{"id_basket": b1, "mix_ratio": 60}, {"id_basket": b2, "mix_ratio": 60}],
        headers=headers,
    )
    assert resp.status_code == 422

    # Config valide → 200
    resp = await client.put(
        f"/api/v1/players/{player.id_player}/baskets",
        json=[{"id_basket": b1, "mix_ratio": 70}, {"id_basket": b2, "mix_ratio": 30}],
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2

    resp = await client.get(f"/api/v1/players/{player.id_player}/baskets", headers=headers)
    assert resp.status_code == 200
    ratios = {b["id_basket"]: b["mix_ratio"] for b in resp.json()}
    assert ratios == {b1: 70, b2: 30}


async def _make_audio_media(db: AsyncSession, id_org: int) -> CmsMedia:
    media = CmsMedia(
        id_org=id_org,
        media_name=f"track-{uuid.uuid4().hex[:8]}.mp3",
        media_type="audio",
        mime_type="audio/mpeg",
        storage_key=f"audio/{uuid.uuid4().hex}.mp3",
        checksum_sha256=uuid.uuid4().hex,
        duration_ms=120000,
        source="upload",
        transcode_status="done",
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)
    return media


async def test_bulk_add_items_same_eligibility_as_unit(
    client: AsyncClient, admin_token, other_org_token,
    db_session: AsyncSession, org: CmsOrganization, org_b: CmsOrganization,
) -> None:
    """Le lot applique LA MÊME éligibilité que l'ajout unitaire : audio de l'org seulement.

    Les inéligibles (vidéo, autre org, id inconnu) sont ignorés sans faire échouer le
    reste ; l'ordre demandé est conservé ; un doublon déjà présent est sauté.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(), headers=headers,
    )).json()["id_basket"]

    a1 = await _make_audio_media(db_session, org.id_org)
    a2 = await _make_audio_media(db_session, org.id_org)
    foreign = await _make_audio_media(db_session, org_b.id_org)  # autre org → ignoré
    video = CmsMedia(
        id_org=org.id_org, media_name="clip.mp4", media_type="video", mime_type="video/mp4",
        storage_key=f"video/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        source="upload", transcode_status="done",
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items/bulk",
        json={"id_medias": [a2.id_media, foreign.id_media, video.id_media, a1.id_media, 999999]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    added = resp.json()
    assert [it["id_media"] for it in added] == [a2.id_media, a1.id_media]  # ordre conservé
    assert all(it["media_type"] == "audio" for it in added)

    # Rejouer le même lot : tout est déjà présent → aucun ajout, pas d'erreur.
    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items/bulk",
        json={"id_medias": [a1.id_media, a2.id_media]},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json() == []

    resp = await client.get(f"/api/v1/audio-baskets/{id_basket}/items", headers=headers)
    assert len(resp.json()) == 2


async def test_add_item_cross_org_media_404(
    client: AsyncClient, admin_token, db_session: AsyncSession, org_b: CmsOrganization,
) -> None:
    """Unitaire : un média d'une AUTRE org est refusé en 404 (org explicite, pas la seule RLS)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(), headers=headers,
    )).json()["id_basket"]
    foreign = await _make_audio_media(db_session, org_b.id_org)

    resp = await client.post(
        f"/api/v1/audio-baskets/{id_basket}/items",
        json={"id_media": foreign.id_media},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_audio_event_of_another_org_does_not_reach_this_player(
    client: AsyncClient, admin_token, other_org_token, db_session: AsyncSession,
    org: CmsOrganization, org_b: CmsOrganization, player: CmsPlayer, audio_media: CmsMedia,
) -> None:
    """🔴 A1 — un événement audio d'une AUTRE organisation ne doit rien activer ici.

    Le chemin audio de `_resolve_audio_baskets` était le seul à ne pas filtrer `id_org`, et
    `event_target_matches` accepte `target_type='org'` INCONDITIONNELLEMENT : l'événement de
    l'org B activait donc son panier sur les écrans de l'org A. Diffusion inter-tenant.
    """
    from app.api.v1.endpoints.ws import _resolve_audio_baskets
    from app.models.event import CmsEvent

    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    # Panier de l'org B, avec un morceau (sinon il serait écarté faute d'items).
    _, token_b = other_org_token
    hb = {"Authorization": f"Bearer {token_b}"}
    b_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(basket_name="B-Music"), headers=hb,
    )).json()["id_basket"]
    b_media = await _make_audio_media(db_session, org_b.id_org)
    await client.post(f"/api/v1/audio-baskets/{b_basket}/items",
                      json={"id_media": b_media.id_media}, headers=hb)

    # Événement audio ACTIF de l'org B ciblant « toute l'organisation ».
    db_session.add(CmsEvent(
        id_org=org_b.id_org, event_name="B org-wide", event_type="manual",
        event_kind="audio", status="active",
        priority=10, id_basket=b_basket, mix_ratio=80,
        target_config={"target_type": "org", "target_ids": []},
    ))
    await db_session.commit()

    # Le player appartient à l'org A : il ne doit RIEN recevoir de cet événement.
    res = await _resolve_audio_baskets(db_session, player.id_player)
    assert all(b["id_basket"] != b_basket for b in res), res

    # Témoin : le même montage DANS l'org du player fonctionne, lui (sinon le test
    # passerait pour la mauvaise raison — un résolveur qui ne rend jamais rien).
    a_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(basket_name="A-Music"), headers=headers,
    )).json()["id_basket"]
    await client.post(f"/api/v1/audio-baskets/{a_basket}/items",
                      json={"id_media": audio_media.id_media}, headers=headers)
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="A org-wide", event_type="manual",
        event_kind="audio", status="active",
        priority=10, id_basket=a_basket, mix_ratio=80,
        target_config={"target_type": "org", "target_ids": []},
    ))
    await db_session.commit()
    res = await _resolve_audio_baskets(db_session, player.id_player)
    assert any(b["id_basket"] == a_basket for b in res), res


async def test_mandatory_basket_ignores_operator_override(
    client: AsyncClient, admin_token, db_session: AsyncSession, player: CmsPlayer,
    audio_media: CmsMedia,
) -> None:
    """🔴 A2 — un panier OBLIGATOIRE ne se laisse pas couper par l'override opérateur.

    L'écran promet « ratio verrouillé pour les niveaux inférieurs » (3 paniers sur 6 le
    portent en production) et rien ne le vérifiait : l'étage 3 supprimait purement et
    simplement le panier du mix.
    """
    from app.api.v1.endpoints.ws import _resolve_audio_baskets
    from app.models.audio_basket import CmsPlayerBasketConfig
    from app.models.schedule import CmsSchedule, CmsScheduleBasket, CmsScheduleRule, CmsScheduleTarget

    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post(
        "/api/v1/audio-baskets",
        json=_basket_payload(basket_name="Musique imposée", is_mandatory=True),
        headers=headers,
    )).json()["id_basket"]
    await client.post(f"/api/v1/audio-baskets/{id_basket}/items",
                      json={"id_media": audio_media.id_media}, headers=headers)

    sched = CmsSchedule(id_org=player.id_org, schedule_name="Audio", schedule_kind="audio",
                        priority=10, is_active=True)
    db_session.add(sched)
    await db_session.flush()
    db_session.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player.id_player),
        CmsScheduleBasket(id_schedule=sched.id_schedule, id_basket=id_basket, mix_ratio=60),
        # L'opérateur local coupe le panier : ligne d'override antérieure au correctif.
        CmsPlayerBasketConfig(id_player=player.id_player, id_basket=id_basket,
                              mix_ratio=10, is_active=False),
    ])
    await db_session.commit()

    res = await _resolve_audio_baskets(db_session, player.id_player)
    got = [b for b in res if b["id_basket"] == id_basket]
    assert got, "le panier obligatoire a été retiré par l'override"
    assert got[0]["mix_ratio"] == 60, "le ratio du programme doit primer sur l'override"

    # …et l'API refuse d'enregistrer un tel override, en NOMMANT le panier.
    resp = await client.put(
        f"/api/v1/players/{player.id_player}/baskets",
        json=[{"id_basket": id_basket, "mix_ratio": 10, "is_active": False}],
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "Musique imposée" in resp.json()["detail"]


async def test_delete_basket_names_its_uses_and_force_detaches(
    client: AsyncClient, admin_token, db_session: AsyncSession, player: CmsPlayer,
) -> None:
    """🔴 A5 — supprimer un panier diffusé : 409 qui NOMME, puis `?force=true` détache."""
    from app.models.event import CmsEvent
    from app.models.schedule import CmsSchedule, CmsScheduleBasket

    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(basket_name="Panier diffusé"),
        headers=headers,
    )).json()["id_basket"]

    sched = CmsSchedule(id_org=player.id_org, schedule_name="Programme Matin",
                        schedule_kind="audio", priority=5, is_active=True)
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleBasket(id_schedule=sched.id_schedule, id_basket=id_basket,
                                     mix_ratio=50))
    ev = CmsEvent(id_org=player.id_org, event_name="Alerte Test", event_type="manual",
                  event_kind="audio", status="active", priority=1, id_basket=id_basket,
                  target_config={"target_type": "player", "target_ids": [player.id_player]})
    db_session.add(ev)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/audio-baskets/{id_basket}", headers=headers)
    assert resp.status_code == 409, resp.text
    assert "Programme Matin" in resp.json()["detail"]
    assert "Alerte Test" in resp.json()["detail"]

    impact = (await client.get(f"/api/v1/audio-baskets/{id_basket}/deletion-impact",
                               headers=headers)).json()
    assert [s["name"] for s in impact["schedules"]] == ["Programme Matin"]
    assert [e["name"] for e in impact["events"]] == ["Alerte Test"]

    # force=true : détache d'abord (l'événement devient inerte, panier NULL) puis supprime.
    resp = await client.delete(f"/api/v1/audio-baskets/{id_basket}?force=true", headers=headers)
    assert resp.status_code == 204, resp.text
    await db_session.refresh(ev)
    assert ev.id_basket is None
    assert (await db_session.execute(
        select(CmsScheduleBasket).where(CmsScheduleBasket.id_basket == id_basket)
    )).scalar_one_or_none() is None


async def test_basket_mutations_are_audited(
    client: AsyncClient, admin_token, audio_media: CmsMedia, db_session: AsyncSession,
) -> None:
    """🔴 A7 — création, modification, ajout de morceau et suppression laissent une trace.

    Aucune opération CMS sur les paniers n'était journalisée : les seules lignes d'audit
    mesurées venaient du panneau de contrôle local.
    """
    from app.models.audit_log import CmsAuditLog

    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post(
        "/api/v1/audio-baskets", json=_basket_payload(basket_name="Tracé"), headers=headers,
    )).json()["id_basket"]
    await client.put(f"/api/v1/audio-baskets/{id_basket}", json={"shuffle": True}, headers=headers)
    await client.post(f"/api/v1/audio-baskets/{id_basket}/items",
                      json={"id_media": audio_media.id_media}, headers=headers)
    await client.delete(f"/api/v1/audio-baskets/{id_basket}", headers=headers)

    actions = set((await db_session.execute(
        select(CmsAuditLog.action).where(
            CmsAuditLog.resource_type == "audio_basket",
            CmsAuditLog.resource_id == str(id_basket),
        )
    )).scalars().all())
    assert {"create", "update", "add_item", "delete"} <= actions, actions


async def test_basket_permissions_table_is_gone(db_session: AsyncSession) -> None:
    """A3 — la table morte `cms_basket_permissions` ne doit plus exister.

    ⚠️ La base de test est bâtie par `create_all` (sans migrations) : ce test vérifie donc
    que le MODÈLE a disparu, et lit la migration 0116 pour garantir qu'elle la supprime
    aussi côté base — garde anti-dérive, même patron que la 0111.
    """
    import pathlib
    from app.db.base import Base

    assert "cms_basket_permissions" not in Base.metadata.tables
    migration = pathlib.Path(__file__).resolve().parents[1] / (
        "alembic/versions/0116_audio_baskets_audit.py")
    assert "DROP TABLE IF EXISTS cms_basket_permissions" in migration.read_text(encoding="utf-8")


async def test_basket_rls_cross_tenant(client: AsyncClient, admin_token, other_org_token) -> None:
    """Un panier créé par une org n'est pas visible par une autre (RLS → 404)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    id_basket = (await client.post("/api/v1/audio-baskets", json=_basket_payload(), headers=headers)).json()["id_basket"]

    _, other_token = other_org_token
    other_headers = {"Authorization": f"Bearer {other_token}"}
    resp = await client.get(f"/api/v1/audio-baskets/{id_basket}", headers=other_headers)
    assert resp.status_code == 404
