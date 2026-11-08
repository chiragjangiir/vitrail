"""
Tests Sprint 1.5 — Players CRUD + token player (§III).

Couvre :
  - test_create_player
  - test_list_players
  - test_get_player
  - test_generate_player_token
  - test_player_token_type_and_subject
  - test_delete_player
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"player-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="PlayerOrg", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def org_admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"admin-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    # role_key a une contrainte UNIQUE globale — upsert pour éviter les conflits entre tests
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (
        await db_session.execute(select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))
    ).scalar_one()

    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_token(org_admin: CmsUser, org: CmsOrganization) -> str:
    # JWT direct — bypass du check 2FA (CMS_ORG_ADMIN force la 2FA sur le login endpoint)
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


@pytest_asyncio.fixture
async def player_id(client: AsyncClient, admin_token: str) -> int:
    resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"nuc-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_player"]


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_create_player(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"nuc-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "offline"
    assert data["player_os"] == "linux"
    assert data["cpu_usage"] is None
    assert data["token_expires_at"] is None


async def test_player_role_default_and_update(client: AsyncClient, admin_token: str, player_id: int) -> None:
    """player_role défaut 'content' ; modifiable en audio/mixed (§XIX)."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get(f"/api/v1/players/{player_id}", headers=headers)
    assert resp.json()["player_role"] == "content"

    resp = await client.put(f"/api/v1/players/{player_id}", json={"player_role": "mixed"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["player_role"] == "mixed"

    # Valeur hors énumération → 422
    resp = await client.put(f"/api/v1/players/{player_id}", json={"player_role": "bogus"}, headers=headers)
    assert resp.status_code == 422


async def test_list_players(client: AsyncClient, admin_token: str, player_id: int) -> None:
    resp = await client.get(
        "/api/v1/players/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    ids = [p["id_player"] for p in resp.json()]
    assert player_id in ids


async def test_get_player(client: AsyncClient, admin_token: str, player_id: int) -> None:
    resp = await client.get(
        f"/api/v1/players/{player_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id_player"] == player_id


async def test_generate_player_token(client: AsyncClient, admin_token: str, player_id: int) -> None:
    resp = await client.post(
        f"/api/v1/players/{player_id}/token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "player_token" in data
    assert "expires_at" in data
    assert len(data["player_token"]) > 20


async def test_player_token_type_and_subject(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    resp = await client.post(
        f"/api/v1/players/{player_id}/token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = resp.json()["player_token"]
    payload = decode_token(token)
    assert payload["type"] == "player"
    assert int(payload["sub"]) == player_id


async def test_delete_player(client: AsyncClient, admin_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"nuc-del-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    pid = create_resp.json()["id_player"]

    del_resp = await client.delete(
        f"/api/v1/players/{pid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/players/{pid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 404


async def test_screenshot_upload_sets_timestamp_and_url(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """Upload d'une capture (auth player) → last_screenshot_at horodaté + screenshot_url
    signé exposé dans PlayerRead. Avant tout upload, les deux champs sont null."""
    # Avant upload : pas de capture
    before = await client.get(
        f"/api/v1/players/{player_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert before.json()["last_screenshot_at"] is None
    assert before.json()["screenshot_url"] is None

    # Token player pour s'authentifier en tant que machine
    tok = (await client.post(
        f"/api/v1/players/{player_id}/token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )).json()["player_token"]

    with patch("app.api.v1.endpoints.players.upload_file", new=AsyncMock()) as up, \
         patch("app.api.v1.endpoints.players.get_signed_url", return_value="http://minio/screenshots/x.png"):
        up_resp = await client.post(
            f"/api/v1/players/{player_id}/screenshot",
            content=b"\x89PNG fake bytes",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/png"},
        )
        assert up_resp.status_code == 204
        up.assert_awaited_once()

        # Après upload : horodatage posé + URL signée exposée
        after = await client.get(
            f"/api/v1/players/{player_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    data = after.json()
    assert data["last_screenshot_at"] is not None
    assert data["screenshot_url"] == "http://minio/screenshots/x.png"


async def test_screenshot_upload_preserves_jpeg_content_type(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """Le BrightSign envoie du JPEG (snapshot DWS) → on stocke avec le bon Content-Type
    (l'URL signée du drawer sert alors l'image telle quelle). La clé reste `latest.png`."""
    tok = (await client.post(
        f"/api/v1/players/{player_id}/token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )).json()["player_token"]

    with patch("app.api.v1.endpoints.players.upload_file", new=AsyncMock()) as up:
        up_resp = await client.post(
            f"/api/v1/players/{player_id}/screenshot",
            content=b"\xff\xd8\xff fake jpeg bytes",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"},
        )
        assert up_resp.status_code == 204
        # 3e arg positionnel = content_type passé à upload_file
        assert up.await_args.args[2] == "image/jpeg"
        assert up.await_args.args[1] == f"screenshots/{player_id}/latest.png"


async def test_delete_player_cleans_generic_targets(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """La suppression d'un player retire aussi ses cibles GÉNÉRIQUES sans FK :
    lignes cms_schedule_targets (target_type='player') + id dans les target_ids
    JSONB des events — sinon cibles fantômes à vie (constaté prod 2026-07-07)."""
    from app.models.event import CmsEvent
    from app.models.player import CmsPlayer
    from app.models.schedule import CmsSchedule, CmsScheduleTarget

    create_resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"nuc-ghost-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    pid = create_resp.json()["id_player"]
    org_id = (await db_session.execute(
        select(CmsPlayer.id_org).where(CmsPlayer.id_player == pid))).scalar_one()

    sched = CmsSchedule(id_org=org_id, schedule_name="S-ghost", schedule_kind="content")
    ev = CmsEvent(
        id_org=org_id, event_name="E-ghost", event_type="manual", event_kind="content",
        target_config={"target_type": "player", "target_ids": [pid, 999999]},
    )
    db_session.add_all([sched, ev])
    await db_session.flush()
    db_session.add(CmsScheduleTarget(
        id_schedule=sched.id_schedule, target_type="player", target_id=pid))
    await db_session.commit()
    ev_id, sched_id = ev.id_event, sched.id_schedule

    del_resp = await client.delete(
        f"/api/v1/players/{pid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    db_session.expire_all()
    ev2 = (await db_session.execute(
        select(CmsEvent).where(CmsEvent.id_event == ev_id))).scalar_one()
    ids = (ev2.target_config or {}).get("target_ids", [])
    assert pid not in ids          # le player supprimé n'est plus ciblé
    assert 999999 in ids           # les autres cibles sont préservées
    left = (await db_session.execute(select(CmsScheduleTarget).where(
        CmsScheduleTarget.id_schedule == sched_id))).scalars().all()
    assert left == []              # la cible générique de schedule est purgée


async def test_maintenance_toggle(
    client: AsyncClient, admin_token: str, player_id: int, db_session: AsyncSession
) -> None:
    """Mode maintenance manuel : ON pose status='maintenance' + vide les alertes ; OFF
    ré-évalue (offline si jamais vu). Chaque bascule journalise un audit."""
    from app.models.audit_log import CmsAuditLog
    from app.models.player import CmsPlayer

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Player nouvellement créé : online par défaut, une raison d'alerte fictive.
    p = (await db_session.execute(
        select(CmsPlayer).where(CmsPlayer.id_player == player_id))).scalar_one()
    p.status = "online"
    p.alert_reasons = ["cpu_high"]
    await db_session.commit()

    # ON → maintenance + alertes vidées
    r = await client.post(f"/api/v1/players/{player_id}/maintenance",
                          json={"enabled": True}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "maintenance"
    db_session.expire_all()
    p = (await db_session.execute(
        select(CmsPlayer).where(CmsPlayer.id_player == player_id))).scalar_one()
    assert p.status == "maintenance" and (p.alert_reasons or []) == []

    # OFF → jamais vu (last_seen_at NULL) donc offline
    r = await client.post(f"/api/v1/players/{player_id}/maintenance",
                          json={"enabled": False}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "offline"

    # Deux entrées d'audit (on puis off)
    org_id = (await db_session.execute(
        select(CmsPlayer.id_org).where(CmsPlayer.id_player == player_id))).scalar_one()
    actions = (await db_session.execute(
        select(CmsAuditLog.action).where(
            CmsAuditLog.id_org == org_id,
            CmsAuditLog.resource_type == "player",
            CmsAuditLog.resource_id == str(player_id),
        ))).scalars().all()
    assert "player_maintenance_on" in actions
    assert "player_maintenance_off" in actions


def test_effective_status_derivation() -> None:
    """online/warning avec heartbeat périmé (> 3 min) → offline à l'affichage ; offline,
    critical et maintenance sont inchangés ; un heartbeat frais reste online."""
    from datetime import UTC, datetime, timedelta

    from app.services.analytics import effective_status

    now = datetime.now(UTC)
    fresh = now - timedelta(seconds=30)
    stale = now - timedelta(minutes=10)

    assert effective_status("online", stale, now) == "offline"
    assert effective_status("warning", stale, now) == "offline"
    assert effective_status("online", fresh, now) == "online"
    assert effective_status("online", None, now) == "online"      # jamais vu mais pas encore marqué
    assert effective_status("offline", stale, now) == "offline"
    assert effective_status("critical", stale, now) == "critical"
    assert effective_status("maintenance", stale, now) == "maintenance"  # jamais réveillé


async def test_current_state_with_active_playlist(
    client: AsyncClient, admin_token: str, player_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    """🔴 `GET /players/{id}/current-state` répondait 500 dès qu'un écran avait une playlist.

    Cause : le calcul de la durée totale sélectionne UNIQUEMENT une fonction d'agrégat, si
    bien qu'aucune entité n'établit le côté gauche de la jointure vers les médias —
    SQLAlchemy refuse de deviner. Introduit le 2026-07-16 avec les documents multipages et
    mesuré en production le 29/07 à ~20 erreurs/minute : la route n'avait **aucun test**,
    donc rien ne l'a vu pendant 13 jours.

    Le test monte le cas NOMINAL (un programme actif qui vise ce player) — c'est
    précisément celui qui déclenchait l'erreur ; sans playlist, la route répondait 200 et
    n'aurait rien prouvé.
    """
    from app.models.media import CmsMedia
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem
    from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget

    headers = {"Authorization": f"Bearer {admin_token}"}

    media = CmsMedia(
        id_org=org.id_org, media_name="clip.mp4", media_type="video", mime_type="video/mp4",
        storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        duration_ms=10000, source="upload", transcode_status="done",
    )
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL courante", sync_mode="wall_clock")
    db_session.add_all([media, pl])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=10000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="SC", schedule_kind="content",
                        priority=10, is_active=True, id_playlist=pl.id_playlist)
    db_session.add(sched)
    await db_session.flush()
    db_session.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player_id),
    ])
    await db_session.commit()

    resp = await client.get(f"/api/v1/players/{player_id}/current-state", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_playlist"] is not None
    assert body["active_playlist"]["playlist_name"] == "PL courante"
    assert body["active_playlist"]["total_duration_ms"] == 10000
