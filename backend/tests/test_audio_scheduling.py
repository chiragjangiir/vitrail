"""Tests Audio Scheduling (§XIX) — résolution set-based depuis les schedules audio.

Couvre :
  - 2 schedules audio 'always' → 2 paniers simultanés (set-based)
  - règle date_range hors fenêtre → panier absent
  - override opérateur (cms_player_basket_config is_active=False) → panier retiré
  - clamp : somme des ratios > 100 → drop du panier de plus basse priorité
  - endpoint POST /schedules kind=audio
"""

import uuid
from datetime import date, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _resolve_audio_baskets
from app.core.security import create_access_token, hash_password
from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem, CmsPlayerBasketConfig
from app.models.media import CmsMedia
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.event import CmsEvent
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget, CmsScheduleBasket
from app.models.user import CmsUser


async def _make_org(db: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="AS Org", org_slug=f"as-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


async def _make_user(db: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"as-{uid}@t.com", password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    role_key = f"CMS_AS_{uid}"
    await db.execute(pg_insert(CmsRole).values(role_key=role_key, label="AS", is_system=False, is_active=True)
                     .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    for module, op in [("schedules", "create"), ("schedules", "read"), ("audio_baskets", "read")]:
        await db.execute(pg_insert(CmsPermission).values(module=module, operation=op)
                         .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(CmsPermission.module == module, CmsPermission.operation == op))).scalar_one()
        await db.execute(pg_insert(CmsRolePermission).values(id_role=role.id_role, id_permission=perm.id_permission).on_conflict_do_nothing())
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"})
    return user, token


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session)


@pytest_asyncio.fixture
async def admin_token(db_session, org):
    return await _make_user(db_session, org)


@pytest_asyncio.fixture
async def player(db_session, org) -> CmsPlayer:
    p = CmsPlayer(id_org=org.id_org, player_name="AS Player", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _basket_with_item(db, org, name="B", btype="music") -> int:
    media = CmsMedia(
        id_org=org.id_org, media_name=f"{name}.ogg", media_type="audio", mime_type="audio/ogg",
        storage_key=f"audio/{uuid.uuid4().hex}.ogg", checksum_sha256=uuid.uuid4().hex,
        duration_ms=120000, source="upload", transcode_status="done",
    )
    db.add(media)
    b = CmsAudioBasket(id_org=org.id_org, basket_name=name, basket_type=btype)
    db.add(b)
    await db.flush()
    db.add(CmsAudioBasketItem(id_basket=b.id_basket, id_media=media.id_media, weight=1))
    await db.commit()
    await db.refresh(b)
    return b.id_basket


async def _audio_schedule(db, org, player, id_basket, ratio, rule_type="always", priority=0, **rule_kw) -> int:
    """Crée un schedule audio (programme) avec un seul panier (helper de test)."""
    s = CmsSchedule(id_org=org.id_org, schedule_name=f"sch-{id_basket}", schedule_kind="audio",
                    priority=priority)
    db.add(s)
    await db.flush()
    db.add(CmsScheduleBasket(id_schedule=s.id_schedule, id_basket=id_basket, mix_ratio=ratio))
    db.add(CmsScheduleRule(id_schedule=s.id_schedule, rule_type=rule_type, **rule_kw))
    db.add(CmsScheduleTarget(id_schedule=s.id_schedule, target_type="player", target_id=player.id_player))
    await db.commit()
    return s.id_schedule


# ── Tests résolution ────────────────────────────────────────────────────────────

async def test_two_always_schedules_resolve_both(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Music", "music")
    b2 = await _basket_with_item(db_session, org, "Promo", "message")
    await _audio_schedule(db_session, org, player, b1, 60)
    await _audio_schedule(db_session, org, player, b2, 30)

    res = await _resolve_audio_baskets(db_session, player.id_player)
    ratios = {b["id_basket"]: b["mix_ratio"] for b in res}
    assert ratios == {b1: 60, b2: 30}


async def test_daterange_out_of_window_absent(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Music")
    b2 = await _basket_with_item(db_session, org, "Xmas", "ambiance")
    await _audio_schedule(db_session, org, player, b1, 50)
    # fenêtre passée → b2 ne doit pas jouer
    await _audio_schedule(db_session, org, player, b2, 40, rule_type="date_range",
                          date_from=date.today() - timedelta(days=10),
                          date_to=date.today() - timedelta(days=5))
    res = await _resolve_audio_baskets(db_session, player.id_player)
    ids = {b["id_basket"] for b in res}
    assert ids == {b1}


async def test_schedule_validity_envelope_excludes_out_of_window(db_session, org, player) -> None:
    """L'enveloppe de dates du programme (valid_from/until) prime sur une règle 'always'."""
    b1 = await _basket_with_item(db_session, org, "Music")
    b2 = await _basket_with_item(db_session, org, "PastProgram", "ambiance")
    await _audio_schedule(db_session, org, player, b1, 50)  # perpétuel
    # Programme 'always' mais fenêtre de validité passée → exclu malgré la règle.
    sid = await _audio_schedule(db_session, org, player, b2, 40)
    sched = (await db_session.execute(
        select(CmsSchedule).where(CmsSchedule.id_schedule == sid)
    )).scalar_one()
    sched.valid_from = date.today() - timedelta(days=10)
    sched.valid_until = date.today() - timedelta(days=5)
    await db_session.commit()

    res = await _resolve_audio_baskets(db_session, player.id_player)
    assert {b["id_basket"] for b in res} == {b1}

    # On élargit la fenêtre pour inclure aujourd'hui → le programme rejoint le mix.
    sched.valid_until = date.today() + timedelta(days=5)
    await db_session.commit()
    res = await _resolve_audio_baskets(db_session, player.id_player)
    assert {b["id_basket"] for b in res} == {b1, b2}


async def test_operator_override_removes_basket(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Music")
    await _audio_schedule(db_session, org, player, b1, 50)
    # override opérateur : panier coupé
    db_session.add(CmsPlayerBasketConfig(id_player=player.id_player, id_basket=b1, mix_ratio=50, is_active=False))
    await db_session.commit()
    res = await _resolve_audio_baskets(db_session, player.id_player)
    assert res == []


async def test_ratio_clamp_drops_lowest_priority(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Hi")
    b2 = await _basket_with_item(db_session, org, "Lo")
    await _audio_schedule(db_session, org, player, b1, 70, priority=10)
    await _audio_schedule(db_session, org, player, b2, 50, priority=1)  # 70+50>100 → b2 droppé
    res = await _resolve_audio_baskets(db_session, player.id_player)
    ids = {b["id_basket"] for b in res}
    assert ids == {b1}


async def test_music_and_ambiance_have_independent_budgets(db_session, org, player) -> None:
    """Music et ambiance = 2 familles aux budgets ≤100 SÉPARÉS (couches simultanées).

    Ancien comportement (budget partagé) : music 70 + ambiance 70 = 140 → une des deux
    droppée. Nouveau : chaque famille a son budget → les deux gardées. Et dans la famille
    ambiance, 70+50 dépasse 100 → l'ambiance la plus basse priorité est droppée.
    """
    music = await _basket_with_item(db_session, org, "Music", "music")
    amb_hi = await _basket_with_item(db_session, org, "AmbHi", "ambiance")
    amb_lo = await _basket_with_item(db_session, org, "AmbLo", "ambiance")
    await _audio_schedule(db_session, org, player, music, 70, priority=10)
    await _audio_schedule(db_session, org, player, amb_hi, 70, priority=10)
    await _audio_schedule(db_session, org, player, amb_lo, 50, priority=1)  # 70+50>100 ambiance → droppé

    res = await _resolve_audio_baskets(db_session, player.id_player)
    ids = {b["id_basket"] for b in res}
    # music gardé MALGRÉ un total cross-familles de 140 ; amb_hi gardé ; amb_lo droppé.
    assert ids == {music, amb_hi}


async def test_trigger_basket_excluded_from_mix_budget(db_session, org, player) -> None:
    """Un panier emergency ne consomme pas le budget ≤100 et n'est jamais droppé."""
    music = await _basket_with_item(db_session, org, "Music", "music")
    alert = await _basket_with_item(db_session, org, "Alert", "emergency")
    await _audio_schedule(db_session, org, player, music, 80, priority=10)
    await _audio_schedule(db_session, org, player, alert, 50, priority=1)  # 80+50>100 mais emergency exempt
    res = await _resolve_audio_baskets(db_session, player.id_player)
    ids = {b["id_basket"] for b in res}
    assert ids == {music, alert}  # les deux présents (emergency hors budget)


async def _active_audio_event(db, org, player, id_basket, ratio, priority=70):
    ev = CmsEvent(
        id_org=org.id_org, event_name=f"ev-{id_basket}", event_type="manual",
        event_kind="audio", id_basket=id_basket, mix_ratio=ratio, priority=priority,
        status="active", target_config={"target_type": "player", "target_ids": [player.id_player]},
    )
    db.add(ev)
    await db.commit()
    return ev


async def test_audio_event_adds_basket(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Promo", "message")
    await _active_audio_event(db_session, org, player, b1, 25)
    res = await _resolve_audio_baskets(db_session, player.id_player)
    ratios = {b["id_basket"]: b["mix_ratio"] for b in res}
    assert ratios == {b1: 25}


async def test_audio_event_overrides_schedule_ratio(db_session, org, player) -> None:
    b1 = await _basket_with_item(db_session, org, "Music")
    await _audio_schedule(db_session, org, player, b1, 80, priority=5)
    await _active_audio_event(db_session, org, player, b1, 40, priority=90)
    res = await _resolve_audio_baskets(db_session, player.id_player)
    # L'event prime → ratio 40 (pas 80)
    assert {b["id_basket"]: b["mix_ratio"] for b in res} == {b1: 40}


# ── Gating par rôle dans le player:sync (§XIX) ──────────────────────────────────

async def test_sync_baskets_gated_by_player_role(db_session, org, player) -> None:
    """Le sync ne diffuse les paniers QUE pour les rôles 'audio'/'mixed'.

    Un player 'content' reçoit audio_baskets=[] même si un programme audio le cible
    → setBaskets([]) coupe le fond audio. Un changement de rôle déclenche un force_sync
    (endpoints/players.py) → l'ambiance s'arrête à chaud. Retour terrain Ed 2026-06-20.
    """
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    b1 = await _basket_with_item(db_session, org, "Music")
    await _audio_schedule(db_session, org, player, b1, 60)

    # 'mixed' / 'audio' → paniers diffusés
    for role in ("mixed", "audio"):
        player.player_role = role
        await db_session.commit()
        payload = await _resolve_sync_payload(db_session, player.id_player)
        assert {b["id_basket"] for b in payload["audio_baskets"]} == {b1}, role

    # 'content' → AUCUN panier (fond audio coupé)
    player.player_role = "content"
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["audio_baskets"] == []


async def _content_schedule_with_item(db, org, player) -> None:
    """Programme CONTENU (playlist 1 item) ciblant le player (helper de test)."""
    media = CmsMedia(
        id_org=org.id_org, media_name="clip.mp4", media_type="video",
        storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        width=1920, height=1080, duration_ms=5000, source="upload", transcode_status="done",
    )
    db.add(media)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                           sort_order=0, duration_ms=5000))
    s = CmsSchedule(id_org=org.id_org, schedule_name="content-sch", schedule_kind="content",
                    id_playlist=pl.id_playlist)
    db.add(s)
    await db.flush()
    db.add(CmsScheduleRule(id_schedule=s.id_schedule, rule_type="always"))
    db.add(CmsScheduleTarget(id_schedule=s.id_schedule, target_type="player", target_id=player.id_player))
    await db.commit()


async def test_audio_role_suppresses_content(db_session, org, player) -> None:
    """Rôle 'Audio seul' (§XIX) : le player ne diffuse AUCUNE playlist de contenu.

    Même avec un programme contenu actif qui le cible, le sync renvoie un payload idle
    (items=[], id_playlist=None) → seul le fond audio joue. Les rôles content/mixed
    continuent de diffuser le contenu. Retour terrain Ed 2026-06-20.
    """
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    await _content_schedule_with_item(db_session, org, player)

    # content / mixed → le contenu est diffusé
    for role in ("content", "mixed"):
        player.player_role = role
        await db_session.commit()
        payload = await _resolve_sync_payload(db_session, player.id_player)
        assert payload["items"], role
        assert payload["id_playlist"] is not None, role

    # audio seul → AUCUN contenu visuel (payload idle)
    player.player_role = "audio"
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["items"] == []
    assert payload["id_playlist"] is None


# ── Endpoint ──────────────────────────────────────────────────────────────────

async def test_simulate_day_audio_applies_mix_clamp(client: AsyncClient, admin_token, org, player, db_session) -> None:
    """La sim journée audio applique le clamp 100 % comme le runtime (panier le plus bas droppé)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    hi = await _basket_with_item(db_session, org, "Hi", "music")
    lo = await _basket_with_item(db_session, org, "Lo", "music")
    await _audio_schedule(db_session, org, player, hi, 70, priority=10)
    await _audio_schedule(db_session, org, player, lo, 50, priority=1)  # 70+50>100 → lo droppé

    resp = await client.post(f"/api/v1/players/{player.id_player}/simulate-day",
                             json={"date": "2026-06-08"}, headers=headers)
    assert resp.status_code == 200, resp.text
    audio = resp.json()["audio"]
    assert audio, "au moins un segment audio attendu"
    ids = {b["id_basket"] for seg in audio for b in seg["baskets"]}
    assert ids == {hi}  # le panier de plus basse priorité est droppé par le clamp


async def test_simulate_day_audio_independent_family_budgets(client: AsyncClient, admin_token, org, player, db_session) -> None:
    """La sim journée applique le budget ≤100 PAR FAMILLE (music 70 + ambiance 70 = les deux)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    music = await _basket_with_item(db_session, org, "Music", "music")
    amb = await _basket_with_item(db_session, org, "Amb", "ambiance")
    await _audio_schedule(db_session, org, player, music, 70, priority=10)
    await _audio_schedule(db_session, org, player, amb, 70, priority=10)  # 140 cross-famille mais 2 budgets

    resp = await client.post(f"/api/v1/players/{player.id_player}/simulate-day",
                             json={"date": "2026-06-08"}, headers=headers)
    assert resp.status_code == 200, resp.text
    audio = resp.json()["audio"]
    ids = {b["id_basket"] for seg in audio for b in seg["baskets"]}
    assert ids == {music, amb}  # budgets séparés → les deux gardés


async def test_simulate_day_audio_excludes_triggers_keeps_jingle(client: AsyncClient, admin_token, org, player, db_session) -> None:
    """La sim audio retire message/emergency (déclenchés sur site) et garde les jingles
    avec leur cadence (trigger_mode/trigger_value)."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    music = await _basket_with_item(db_session, org, "Music", "music")
    jingle = await _basket_with_item(db_session, org, "Jingle", "jingle")
    message = await _basket_with_item(db_session, org, "Promo", "message")
    jb = (await db_session.execute(select(CmsAudioBasket).where(CmsAudioBasket.id_basket == jingle))).scalar_one()
    jb.trigger_mode, jb.trigger_value = "minutes", 15
    await db_session.commit()
    await _audio_schedule(db_session, org, player, music, 60, priority=10)
    await _audio_schedule(db_session, org, player, jingle, 0, priority=5)
    await _audio_schedule(db_session, org, player, message, 0, priority=5)

    resp = await client.post(f"/api/v1/players/{player.id_player}/simulate-day",
                             json={"date": "2026-06-08"}, headers=headers)
    assert resp.status_code == 200, resp.text
    by_id = {b["id_basket"]: b for seg in resp.json()["audio"] for b in seg["baskets"]}
    assert music in by_id and jingle in by_id   # couche continue + jingle présents
    assert message not in by_id                  # message exclu (déclenché sur site)
    assert by_id[jingle]["trigger_mode"] == "minutes" and by_id[jingle]["trigger_value"] == 15


async def test_create_audio_schedule_endpoint(client: AsyncClient, admin_token, org, player, db_session) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    b1 = await _basket_with_item(db_session, org, "EndpointBasket")
    resp = await client.post("/api/v1/schedules", json={
        "schedule_name": "Audio program",
        "schedule_kind": "audio",
        "baskets": [{"id_basket": b1, "mix_ratio": 80}],
        "rules": [{"rule_type": "always"}],
        "targets": [{"target_type": "player", "target_id": player.id_player}],
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["schedule_kind"] == "audio"
    assert len(data["baskets"]) == 1
    assert data["baskets"][0]["id_basket"] == b1
    assert data["baskets"][0]["mix_ratio"] == 80


async def test_create_audio_schedule_requires_basket(client: AsyncClient, admin_token) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/v1/schedules", json={
        "schedule_name": "bad", "schedule_kind": "audio",
        "baskets": [], "rules": [], "targets": [],
    }, headers=headers)
    assert resp.status_code == 422
