"""Tests Store Control Panel LAN (§19.3) — Sprint 2.5 lot 3.

Couvre :
  - CRUD profil d'accès local (POST/GET/DELETE) + scope org (RLS hors test → filtre explicite)
  - régénération révoque le profil précédent
  - injection dans player:sync conditionnée par display_config.local_control_enabled
  - handler d'action WS : toggle/ratio/volume, permissions, validation somme ratios, audit source=local_control
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import (
    _apply_local_control_action,
    _resolve_local_control,
    _resolve_sync_payload,
)
from app.core.security import create_access_token, hash_password
from app.models.audio_basket import CmsAudioBasket, CmsPlayerBasketConfig
from app.models.audit_log import CmsAuditLog
from app.models.local_control import CmsLocalControlProfile
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


async def _make_user(db: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"lc-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    role_key = f"CMS_LC_TEST_{uid}"
    await db.execute(
        pg_insert(CmsRole)
        .values(role_key=role_key, label="LC Test Role", is_system=False, is_active=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()

    for module, op in [("audio_baskets", "read"), ("audio_baskets", "configure"), ("players", "read")]:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=op)
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(
            select(CmsPermission).where(CmsPermission.module == module, CmsPermission.operation == op)
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
    return await _make_org(db_session, "lc")


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    return await _make_user(db_session, org)


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org: CmsOrganization) -> CmsPlayer:
    p = CmsPlayer(
        id_org=org.id_org, player_name="LC Player", player_os="linux",
        ip_address="192.168.1.138",
        display_config={"local_control_enabled": True},
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ── CRUD endpoint ────────────────────────────────────────────────────────────

async def test_create_profile_returns_token_and_url(client: AsyncClient, admin_token, player) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"/api/v1/players/{player.id_player}/local-control/profile",
        json={"validity_hours": 4, "can_edit_ratio": True},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["token"]
    assert data["lan_url"] == f"http://192.168.1.138:8765/control?token={data['token']}"
    assert data["can_edit_ratio"] is True
    assert data["role"] == "CMS_STORE_OPERATOR"


async def test_create_permanent_profile(client: AsyncClient, admin_token, player, db_session) -> None:
    """validity_hours=0 → profil permanent (expires_at null), résolu comme actif."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"/api/v1/players/{player.id_player}/local-control/profile",
        json={"validity_hours": 0},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["expires_at"] is None
    # Résolu (jamais expiré) car le serveur est activé sur le player
    res = await _resolve_local_control(db_session, player.id_player, {"local_control_enabled": True})
    assert res is not None and res["expires_at"] is None


async def test_regenerate_revokes_previous(client: AsyncClient, admin_token, player, db_session) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    t1 = (await client.post(f"/api/v1/players/{player.id_player}/local-control/profile", json={}, headers=headers)).json()["token"]
    t2 = (await client.post(f"/api/v1/players/{player.id_player}/local-control/profile", json={}, headers=headers)).json()["token"]
    assert t1 != t2

    # Un seul profil non-révoqué
    active = (await db_session.execute(
        select(CmsLocalControlProfile).where(
            CmsLocalControlProfile.id_player == player.id_player,
            CmsLocalControlProfile.revoked == False,  # noqa: E712
        )
    )).scalars().all()
    assert len(active) == 1
    assert active[0].token == t2


async def test_get_and_revoke_profile(client: AsyncClient, admin_token, player) -> None:
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(f"/api/v1/players/{player.id_player}/local-control/profile", json={}, headers=headers)

    resp = await client.get(f"/api/v1/players/{player.id_player}/local-control/profile", headers=headers)
    assert resp.status_code == 200 and resp.json() is not None

    resp = await client.delete(f"/api/v1/players/{player.id_player}/local-control/profile", headers=headers)
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/players/{player.id_player}/local-control/profile", headers=headers)
    assert resp.status_code == 200 and resp.json() is None


async def test_profile_cross_tenant_404(client: AsyncClient, admin_token, player, db_session) -> None:
    other_org = await _make_org(db_session, "lcb")
    _, other_token = await _make_user(db_session, other_org)
    headers = {"Authorization": f"Bearer {other_token}"}
    resp = await client.post(f"/api/v1/players/{player.id_player}/local-control/profile", json={}, headers=headers)
    assert resp.status_code == 404


# ── Injection dans player:sync ─────────────────────────────────────────────────

async def test_resolve_local_control_gated_by_flag(db_session, player) -> None:
    db_session.add(CmsLocalControlProfile(
        id_org=player.id_org, id_player=player.id_player, token="abc123",
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    ))
    await db_session.commit()

    # Flag activé → profil retourné
    res = await _resolve_local_control(db_session, player.id_player, {"local_control_enabled": True})
    assert res is not None and res["token"] == "abc123"

    # Flag désactivé → None
    assert await _resolve_local_control(db_session, player.id_player, {"local_control_enabled": False}) is None
    assert await _resolve_local_control(db_session, player.id_player, {}) is None


async def test_resolve_local_control_expired(db_session, player) -> None:
    db_session.add(CmsLocalControlProfile(
        id_org=player.id_org, id_player=player.id_player, token="old",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    ))
    await db_session.commit()
    assert await _resolve_local_control(db_session, player.id_player, {"local_control_enabled": True}) is None


async def test_sync_payload_includes_local_control(db_session, player) -> None:
    db_session.add(CmsLocalControlProfile(
        id_org=player.id_org, id_player=player.id_player, token="tok",
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    ))
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert "local_control" in payload
    assert payload["local_control"]["token"] == "tok"
    assert "audio_baskets" in payload   # vérifie aussi le fix payload empty


async def test_sync_payload_mixed_role_mutes_content(db_session, player) -> None:
    """Un player 'mixed' partage sa sortie audio avec les paniers → son contenu forcé muté (§XIX)."""
    player.player_role = "mixed"
    player.display_config = {"local_control_enabled": True, "content_sound": "on"}
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["display_config"]["content_sound"] == "muted"


async def test_sync_payload_content_role_keeps_sound(db_session, player) -> None:
    """Un player 'content' garde son réglage content_sound tel quel (pas de mute forcé)."""
    player.player_role = "content"
    player.display_config = {"content_sound": "on"}
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["display_config"]["content_sound"] == "on"


# ── Handler d'action WS ─────────────────────────────────────────────────────────

async def _seed_profile(db, player, **over) -> None:
    db.add(CmsLocalControlProfile(
        id_org=player.id_org, id_player=player.id_player, token="t",
        expires_at=datetime.now(UTC) + timedelta(hours=4), **over,
    ))
    await db.commit()


async def _seed_basket(db, org, name="B") -> int:
    b = CmsAudioBasket(id_org=org_id_of(org), basket_name=name, basket_type="music")
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return b.id_basket


def org_id_of(org) -> int:
    return org.id_org if hasattr(org, "id_org") else org


async def test_action_toggle_basket_persists_and_audits(db_session, player, org) -> None:
    await _seed_profile(db_session, player)
    b = await _seed_basket(db_session, org)

    await _apply_local_control_action(db_session, player.id_player, {
        "type": "local_control:action", "action": "toggle_basket", "id_basket": b, "is_active": True,
    })

    cfg = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(
            CmsPlayerBasketConfig.id_player == player.id_player,
            CmsPlayerBasketConfig.id_basket == b,
        )
    )).scalar_one()
    assert cfg.is_active is True

    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:toggle_basket",
            CmsAuditLog.id_org == player.id_org,
        )
    )).scalar_one()
    assert audit.source == "local_control"
    assert audit.id_user is None


async def test_action_set_ratio_forbidden_without_permission(db_session, player, org) -> None:
    await _seed_profile(db_session, player, can_edit_ratio=False)
    b = await _seed_basket(db_session, org)

    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_ratio", "id_basket": b, "mix_ratio": 40,
    })
    # Aucune config créée
    cfg = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_basket == b)
    )).scalar_one_or_none()
    assert cfg is None
    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:set_ratio",
            CmsAuditLog.id_org == player.id_org,
        )
    )).scalar_one()
    assert audit.detail["result"] == "forbidden"


async def test_action_ratio_sum_exceeds_100_rejected(db_session, player, org) -> None:
    await _seed_profile(db_session, player, can_edit_ratio=True)
    b1 = await _seed_basket(db_session, org, "B1")
    b2 = await _seed_basket(db_session, org, "B2")
    # b1 actif à 70
    db_session.add(CmsPlayerBasketConfig(id_player=player.id_player, id_basket=b1, mix_ratio=70, is_active=True))
    await db_session.commit()

    # set b2 à 40 (actif par défaut) → 70+40 > 100 → rejeté
    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_ratio", "id_basket": b2, "mix_ratio": 40,
    })
    cfg = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_basket == b2)
    )).scalar_one_or_none()
    assert cfg is None
    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:set_ratio",
            CmsAuditLog.id_org == player.id_org,
        )
    )).scalar_one()
    assert audit.detail["result"] == "rejected"


async def test_action_set_ratios_batch(db_session, player, org) -> None:
    """set_ratios (auto-équilibrage) upsert plusieurs overlays en une fois."""
    await _seed_profile(db_session, player, can_edit_ratio=True)
    b1 = await _seed_basket(db_session, org, "M1")
    b2 = await _seed_basket(db_session, org, "M2")
    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_ratios",
        "ratios": [{"id_basket": b1, "mix_ratio": 70}, {"id_basket": b2, "mix_ratio": 30}],
    })
    rows = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_player == player.id_player)
    )).scalars().all()
    assert {r.id_basket: r.mix_ratio for r in rows} == {b1: 70, b2: 30}


async def test_action_set_ratios_forbidden_without_permission(db_session, player, org) -> None:
    await _seed_profile(db_session, player, can_edit_ratio=False)
    b1 = await _seed_basket(db_session, org, "M1")
    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_ratios", "ratios": [{"id_basket": b1, "mix_ratio": 50}],
    })
    rows = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_player == player.id_player)
    )).scalars().all()
    assert rows == []


async def test_action_set_volume_updates_display_config(db_session, player) -> None:
    await _seed_profile(db_session, player, can_set_volume=True)
    await _apply_local_control_action(db_session, player.id_player, {"action": "set_volume", "volume": 65})
    await db_session.refresh(player)
    assert player.display_config["audio_volume"] == 65


async def test_action_set_output_updates_display_config(db_session, player) -> None:
    await _seed_profile(db_session, player, can_set_volume=True)
    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_output", "basket_output": "jack", "content_sound": "muted",
    })
    await db_session.refresh(player)
    assert player.display_config["audio_basket_output"] == "jack"
    assert player.display_config["content_sound"] == "muted"


async def test_action_disabled_server_ignored(db_session, org) -> None:
    # Player avec serveur désactivé
    p = CmsPlayer(id_org=org.id_org, player_name="Off", player_os="linux",
                  display_config={"local_control_enabled": False})
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    await _seed_profile(db_session, p, can_set_volume=True)

    await _apply_local_control_action(db_session, p.id_player, {"action": "set_volume", "volume": 50})
    await db_session.refresh(p)
    assert "audio_volume" not in (p.display_config or {})


async def test_action_set_family_volume_persists(db_session, player, org) -> None:
    """set_family_volume persiste audio_music_volume / audio_ambiance_volume ; famille invalide rejetée."""
    await _seed_profile(db_session, player, can_set_volume=True)

    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_family_volume", "family": "music", "volume": 40,
    })
    await db_session.refresh(player)
    assert (player.display_config or {}).get("audio_music_volume") == 40

    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_family_volume", "family": "ambiance", "volume": 0,
    })
    await db_session.refresh(player)
    assert (player.display_config or {}).get("audio_ambiance_volume") == 0  # 0 explicite accepté

    # Famille invalide → rejetée, rien d'autre persisté
    await _apply_local_control_action(db_session, player.id_player, {
        "action": "set_family_volume", "family": "bogus", "volume": 80,
    })
    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:set_family_volume",
            CmsAuditLog.id_org == player.id_org,
        ).order_by(CmsAuditLog.id_audit.desc())
    )).scalars().first()
    assert audit.detail["result"] == "rejected"


async def test_action_reset_overrides_clears_config(db_session, player, org) -> None:
    """Rappel des réglages serveur : efface tous les overrides opérateur du player."""
    await _seed_profile(db_session, player, can_edit_ratio=True)
    b1 = await _seed_basket(db_session, org, "B1")
    b2 = await _seed_basket(db_session, org, "B2")
    db_session.add(CmsPlayerBasketConfig(id_player=player.id_player, id_basket=b1, mix_ratio=60, is_active=True))
    db_session.add(CmsPlayerBasketConfig(id_player=player.id_player, id_basket=b2, mix_ratio=40, is_active=True))
    await db_session.commit()

    await _apply_local_control_action(db_session, player.id_player, {"action": "reset_overrides"})

    remaining = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_player == player.id_player)
    )).scalars().all()
    assert remaining == []
    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:reset_overrides",
            CmsAuditLog.id_org == player.id_org,
        )
    )).scalar_one()
    assert audit.detail["result"] == "ok"
    assert audit.detail["cleared"] == 2
    assert audit.source == "local_control"


async def test_action_reset_overrides_forbidden_without_permission(db_session, player, org) -> None:
    """Sans can_edit_ratio, le reset est refusé et les overrides restent intacts."""
    await _seed_profile(db_session, player, can_edit_ratio=False)
    b = await _seed_basket(db_session, org)
    db_session.add(CmsPlayerBasketConfig(id_player=player.id_player, id_basket=b, mix_ratio=50, is_active=True))
    await db_session.commit()

    await _apply_local_control_action(db_session, player.id_player, {"action": "reset_overrides"})

    cfg = (await db_session.execute(
        select(CmsPlayerBasketConfig).where(CmsPlayerBasketConfig.id_player == player.id_player)
    )).scalar_one()
    assert cfg.is_active is True  # override conservé
    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:reset_overrides",
            CmsAuditLog.id_org == player.id_org,
        )
    )).scalar_one()
    assert audit.detail["result"] == "forbidden"


# ── play_vod : relais cloud vers les BrightSign (sourds au broadcast UDP :7779) ──

async def test_action_play_vod_relays_to_brightsign(db_session, player, org, monkeypatch) -> None:
    """Le panneau local déclenche les pairs Electron par UDP LAN ; les BrightSign
    n'écoutent pas :7779 → le backend relaie un `play_now` cloud vers EUX SEULS
    (le player Electron ciblé n'est PAS relayé — il est servi par l'UDP)."""
    import json as _json
    import uuid as _uuid

    import app.api.v1.endpoints.ws as ws_mod
    from app.models.media import CmsMedia
    from app.models.vod import CmsVodConfig, CmsVodConfigMedia, CmsVodConfigPlayer

    class _FakeRedis:
        published: list = []

        async def publish(self, channel, payload):
            _FakeRedis.published.append((channel, _json.loads(payload)))

        async def aclose(self):
            pass

    _FakeRedis.published = []
    monkeypatch.setattr(ws_mod.aioredis, "from_url", lambda url: _FakeRedis())

    await _seed_profile(db_session, player, can_trigger_event=True)
    oid = org_id_of(org)
    bs = CmsPlayer(id_org=oid, player_name="BS-XT", player_os="brightsign")
    media = CmsMedia(id_org=oid, media_name="vod-vid", media_type="video",
                     storage_key=f"t/{_uuid.uuid4().hex}.mp4", checksum_sha256="x",
                     transcode_status="done", duration_ms=12_000)
    db_session.add_all([bs, media])
    await db_session.flush()
    vod = CmsVodConfig(id_org=oid, vod_name="V-test")
    db_session.add(vod)
    await db_session.flush()
    db_session.add_all([
        CmsVodConfigMedia(id_vod=vod.id_vod, id_media=media.id_media),
        CmsVodConfigPlayer(id_vod=vod.id_vod, id_player=player.id_player),
        CmsVodConfigPlayer(id_vod=vod.id_vod, id_player=bs.id_player),
    ])
    await db_session.commit()

    await _apply_local_control_action(db_session, player.id_player, {
        "type": "local_control:action", "action": "play_vod",
        "id_media": media.id_media, "mode": "once",
        "id_players": [player.id_player, bs.id_player],
    })

    # Un SEUL relais : le BS (l'Electron est déjà servi par le broadcast UDP LAN).
    assert [c for c, _ in _FakeRedis.published] == [f"signflow:player:{bs.id_player}:cmds"]
    cmd = _FakeRedis.published[0][1]
    assert cmd["command"] == "play_now"
    assert cmd["params"]["id_media"] == media.id_media
    assert cmd["params"]["mode"] == "once"
    assert cmd["params"]["cache_key"]  # offline-first : lecture locale si cachée

    audit = (await db_session.execute(
        select(CmsAuditLog).where(
            CmsAuditLog.action == "local_control:play_vod",
            CmsAuditLog.id_org == oid,
        )
    )).scalar_one()
    assert audit.detail["relayed_brightsign"] == [bs.id_player]

    # Média hors config VOD → aucun relais (re-vérification serveur).
    _FakeRedis.published = []
    rogue = CmsMedia(id_org=oid, media_name="rogue", media_type="video",
                     storage_key=f"t/{_uuid.uuid4().hex}.mp4", checksum_sha256="y",
                     transcode_status="done", duration_ms=5_000)
    db_session.add(rogue)
    await db_session.commit()
    await _apply_local_control_action(db_session, player.id_player, {
        "type": "local_control:action", "action": "play_vod",
        "id_media": rogue.id_media, "mode": "once",
        "id_players": [bs.id_player],
    })
    assert _FakeRedis.published == []

    # BS ≥ 2.0.19 (autorun v50) : reçoit le broadcast UDP :7779 directement → PAS de
    # relais cloud (sinon double lecture UDP + relais = la vidéo redémarre).
    _FakeRedis.published = []
    bs2 = CmsPlayer(id_org=oid, player_name="BS-v50", player_os="brightsign",
                    player_version="2.0.19")
    db_session.add(bs2)
    await db_session.flush()
    db_session.add(CmsVodConfigPlayer(id_vod=vod.id_vod, id_player=bs2.id_player))
    await db_session.commit()
    await _apply_local_control_action(db_session, player.id_player, {
        "type": "local_control:action", "action": "play_vod",
        "id_media": media.id_media, "mode": "once",
        "id_players": [bs2.id_player],
    })
    assert _FakeRedis.published == []
