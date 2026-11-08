"""
Tests Sprint 2.1 — Event Engine : modèle, CRUD, activation manuelle (§XX).

Couvre :
  - test_create_event
  - test_activate_event
  - test_deactivate_event
  - test_cancel_event
  - test_event_condition_schedule_evaluates_correctly
  - test_manual_event_activates_and_reverts
  - test_event_rls_cross_tenant
  - test_player_event_stack
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.event_condition import EventConditionEvaluator


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"ev-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="EventOrg", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> CmsOrganization:
    slug = f"evb-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="EventOrgB", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def playlist(db_session: AsyncSession, org: CmsOrganization) -> CmsPlaylist:
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Test Playlist")
    db_session.add(pl)
    await db_session.commit()
    await db_session.refresh(pl)
    return pl


@pytest_asyncio.fixture
async def playlist_b(db_session: AsyncSession, org_b: CmsOrganization) -> CmsPlaylist:
    pl = CmsPlaylist(id_org=org_b.id_org, playlist_name="Playlist B")
    db_session.add(pl)
    await db_session.commit()
    await db_session.refresh(pl)
    return pl


async def _make_user_with_event_perms(
    db: AsyncSession, org: CmsOrganization
) -> tuple[CmsUser, str]:
    """Crée un utilisateur avec les permissions events:read/write/edit/delete et players:read."""
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"ev-user-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    role_key = f"CMS_EVENT_TEST_{uid}"
    await db.execute(
        pg_insert(CmsRole)
        .values(
            role_key=role_key,
            label="Event Test Role",
            is_system=False,
            is_active=True,
        )
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    from sqlalchemy import select
    role = (await db.execute(
        select(CmsRole).where(CmsRole.role_key == role_key)
    )).scalar_one()

    for module, op in [
        ("events", "read"),
        ("events", "create"),
        ("events", "trigger"),
        # `edit` ajoutée le 2026-07-29 : PUT /events/{id} était gardé par `trigger`, une
        # permission de DÉCLENCHEMENT, alors qu'il réécrit contenu, cibles et embargo
        # (migr 0117 — la permission n'existait pas au catalogue).
        ("events", "edit"),
        ("events", "delete"),
        ("players", "read"),
    ]:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=op)
            .on_conflict_do_nothing(
                constraint="uq_cms_permissions_module_operation"
            )
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
        user.id_user,
        extra={"org": org.id_org, "roles": [role_key], "locale": "en"},
    )
    return user, token


@pytest_asyncio.fixture
async def admin_token(
    db_session: AsyncSession, org: CmsOrganization
) -> tuple[CmsUser, str]:
    return await _make_user_with_event_perms(db_session, org)


@pytest_asyncio.fixture
async def admin_token_b(
    db_session: AsyncSession, org_b: CmsOrganization
) -> tuple[CmsUser, str]:
    return await _make_user_with_event_perms(db_session, org_b)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _event_payload(playlist_id: int, **overrides) -> dict:
    base = {
        "event_name": "Test Event",
        "event_type": "manual",
        "id_playlist": playlist_id,
        "priority": 80,
        "target_config": {"target_type": "org", "target_ids": []},
    }
    base.update(overrides)
    return base


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_create_event(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    _, token = admin_token
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["event_name"] == "Test Event"
    assert data["status"] == "inactive"
    assert data["priority"] == 80
    assert data["playlist_name"] == "Test Playlist"


async def test_activate_event(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    _, token = admin_token
    create_resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist),
        headers={"Authorization": f"Bearer {token}"},
    )
    id_event = create_resp.json()["id_event"]

    resp = await client.post(
        f"/api/v1/events/{id_event}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["activated_at"] is not None


async def test_deactivate_event(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    _, token = admin_token
    create_resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist),
        headers={"Authorization": f"Bearer {token}"},
    )
    id_event = create_resp.json()["id_event"]

    await client.post(
        f"/api/v1/events/{id_event}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/events/{id_event}/deactivate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # Revert manuel → état transitoire 'reverting' (§20.3) ; finalisé par le worker ensuite
    assert resp.json()["status"] == "reverting"


async def test_cancel_event(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    _, token = admin_token
    create_resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist),
        headers={"Authorization": f"Bearer {token}"},
    )
    id_event = create_resp.json()["id_event"]

    resp = await client.post(
        f"/api/v1/events/{id_event}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_event_condition_schedule_evaluates_correctly() -> None:
    """Unit test pur — EventConditionEvaluator évalue correctement les plages horaires."""
    evaluator = EventConditionEvaluator()

    # Lundi 12h00
    mon_noon = datetime(2026, 5, 25, 12, 0, 0)  # 2026-05-25 = lundi

    # Condition : lundi–vendredi 08:00–18:00 → doit être vraie
    assert evaluator.evaluate(
        {
            "logic": "AND",
            "conditions": [
                {
                    "source": "schedule",
                    "days_of_week": [0, 1, 2, 3, 4],
                    "time_start": "08:00",
                    "time_end": "18:00",
                }
            ],
        },
        {"now": mon_noon},
    )

    # Samedi 12h00 → hors jours → faux
    sat_noon = datetime(2026, 5, 30, 12, 0, 0)  # 2026-05-30 = samedi
    assert not evaluator.evaluate(
        {
            "logic": "AND",
            "conditions": [
                {
                    "source": "schedule",
                    "days_of_week": [0, 1, 2, 3, 4],
                    "time_start": "08:00",
                    "time_end": "18:00",
                }
            ],
        },
        {"now": sat_noon},
    )

    # source=manual → toujours vrai
    assert evaluator.evaluate(
        {"logic": "AND", "conditions": [{"source": "manual"}]}
    )

    # source=webhook → toujours vrai
    assert evaluator.evaluate(
        {"logic": "AND", "conditions": [{"source": "webhook"}]}
    )

    # trigger_config None → vrai (pas de condition)
    assert evaluator.evaluate(None)


async def test_manual_event_activates_and_reverts(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    """Lifecycle complet : créer → activer → vérifier actif → revert manuel → vérifier reverting."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    # Créer
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist, event_name="Flash Sale"),
        headers=headers,
    )
    assert resp.status_code == 201
    id_event = resp.json()["id_event"]

    # Activer
    resp = await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    # Visible dans /events/active
    resp = await client.get("/api/v1/events/active", headers=headers)
    assert resp.status_code == 200
    active_ids = [e["id_event"] for e in resp.json()]
    assert id_event in active_ids

    # Revert manuel → reverting (transitoire)
    resp = await client.post(f"/api/v1/events/{id_event}/deactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "reverting"

    # Plus visible dans /events/active (reverting n'est pas 'active')
    resp = await client.get("/api/v1/events/active", headers=headers)
    assert id_event not in [e["id_event"] for e in resp.json()]


async def test_event_rls_cross_tenant(
    client: AsyncClient,
    admin_token,
    admin_token_b,
    playlist: CmsPlaylist,
    playlist_b: CmsPlaylist,
) -> None:
    """Un utilisateur de l'org B ne peut pas voir ni modifier les events de l'org A (404)."""
    _, token_a = admin_token
    _, token_b = admin_token_b

    # Créer un event dans l'org A
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist),
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    id_event_a = resp.json()["id_event"]

    # Org B essaie de lire cet event → 404
    resp = await client.get(
        f"/api/v1/events/{id_event_a}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404

    # Org B essaie d'activer cet event → 404
    resp = await client.post(
        f"/api/v1/events/{id_event_a}/activate",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404


async def test_player_event_stack(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token,
    playlist: CmsPlaylist,
    org: CmsOrganization,
) -> None:
    """GET /players/{id}/event-stack retourne les events actifs ciblant ce player."""
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    # Créer un player dans l'org
    player = CmsPlayer(
        id_org=org.id_org,
        player_name="Stack Test Player",
        player_os="linux-x64",
        status="offline",
    )
    db_session.add(player)
    await db_session.commit()
    await db_session.refresh(player)

    # Créer un event ciblant ce player et l'activer
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(
            playlist.id_playlist,
            event_name="Player Stack Event",
            priority=75,
            target_config={"target_type": "player", "target_ids": [player.id_player]},
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    id_event = resp.json()["id_event"]

    await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)

    # Stack du player
    resp = await client.get(
        f"/api/v1/players/{player.id_player}/event-stack", headers=headers
    )
    assert resp.status_code == 200
    stack = resp.json()
    assert len(stack) >= 1
    assert any(e["id_event"] == id_event for e in stack)
    # Trié par priorité décroissante
    priorities = [e["priority"] for e in stack]
    assert priorities == sorted(priorities, reverse=True)


async def test_create_event_with_media(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token,
    org: CmsOrganization,
) -> None:
    """Créer un event avec id_media (pas de playlist) doit retourner 201 avec media_name enrichi."""
    _, token = admin_token
    # Créer un media dans l'org
    media = CmsMedia(
        id_org=org.id_org,
        media_name="Flash Sale Image",
        media_type="image",
        storage_key="test/flash_sale.jpg",
        checksum_sha256="abc123",
        source="upload",
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)

    resp = await client.post(
        "/api/v1/events",
        json={
            "event_name": "Flash Sale",
            "event_type": "manual",
            "id_media": media.id_media,
            "priority": 90,
            "target_config": {"target_type": "org", "target_ids": []},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id_media"] == media.id_media
    assert data["id_playlist"] is None
    assert data["media_name"] == "Flash Sale Image"


async def test_create_event_without_content_returns_422(
    client: AsyncClient, admin_token
) -> None:
    """Créer un event sans id_playlist ni id_media doit retourner 422."""
    _, token = admin_token
    resp = await client.post(
        "/api/v1/events",
        json={
            "event_name": "Bad Event",
            "event_type": "manual",
            "target_config": {"target_type": "org", "target_ids": []},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def _finalize_reverting(db: AsyncSession, id_event: int) -> None:
    """Simule finalize_reverting_events (worker psycopg2) : reverting → completed."""
    ev = (
        await db.execute(select(CmsEvent).where(CmsEvent.id_event == id_event))
    ).scalar_one()
    ev.status = "completed"
    await db.commit()


async def test_update_event_resets_completed_to_inactive(
    client: AsyncClient, admin_token, playlist: CmsPlaylist, db_session: AsyncSession
) -> None:
    """
    Un event en status 'completed' doit repasser en 'inactive' après un PUT
    pour permettre de le relancer.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    # Créer → activer → revert manuel (→ reverting) → finalisation worker (→ completed)
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist, event_name="Reactivatable"),
        headers=headers,
    )
    assert resp.status_code == 201
    id_event = resp.json()["id_event"]

    await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)
    await client.post(f"/api/v1/events/{id_event}/deactivate", headers=headers)
    await _finalize_reverting(db_session, id_event)

    # Vérifier que l'event est bien completed
    resp = await client.get(f"/api/v1/events/{id_event}", headers=headers)
    assert resp.json()["status"] == "completed"

    # Mettre à jour (changement de nom) → doit repasser en inactive
    resp = await client.put(
        f"/api/v1/events/{id_event}",
        json={"event_name": "Reactivatable v2"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "inactive"
    assert data["event_name"] == "Reactivatable v2"
    assert data["activated_at"] is None
    assert data["expires_at"] is None


async def test_activate_event_rejects_outside_validity(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    """
    L'activation manuelle doit être refusée (400) si la date actuelle est
    en dehors de la fenêtre valid_from/valid_until.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    now_utc = datetime.now(UTC)

    # Event avec valid_until dans le passé → activation impossible
    past = (now_utc - timedelta(days=1)).isoformat()
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(
            playlist.id_playlist,
            event_name="Expired Event",
            valid_until=past,
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    id_expired = resp.json()["id_event"]

    resp = await client.post(
        f"/api/v1/events/{id_expired}/activate", headers=headers
    )
    assert resp.status_code == 400
    assert "valid_until" in resp.json()["detail"].lower() or "validity" in resp.json()["detail"].lower()

    # Event avec valid_from dans le futur → activation impossible
    future = (now_utc + timedelta(days=1)).isoformat()
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(
            playlist.id_playlist,
            event_name="Future Event",
            valid_from=future,
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    id_future = resp.json()["id_event"]

    resp = await client.post(
        f"/api/v1/events/{id_future}/activate", headers=headers
    )
    assert resp.status_code == 400
    assert "valid_from" in resp.json()["detail"].lower() or "validity" in resp.json()["detail"].lower()


async def test_cancel_completed_event(
    client: AsyncClient, admin_token, playlist: CmsPlaylist, db_session: AsyncSession
) -> None:
    """
    Annuler un event déjà 'completed' doit retourner 200 (pas d'erreur).
    Cas réel : le worker passe l'event en completed, puis l'opérateur clique
    sur "Annuler" depuis l'interface — ne doit pas échouer.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    # Créer → activer → revert manuel (→ reverting) → finalisation worker (→ completed)
    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(playlist.id_playlist, event_name="Completed Cancel"),
        headers=headers,
    )
    id_event = resp.json()["id_event"]
    await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)
    await client.post(f"/api/v1/events/{id_event}/deactivate", headers=headers)
    await _finalize_reverting(db_session, id_event)

    # Vérifier completed
    assert (await client.get(f"/api/v1/events/{id_event}", headers=headers)).json()["status"] == "completed"

    # Annuler depuis completed → 200 et status=cancelled
    resp = await client.post(f"/api/v1/events/{id_event}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_embargo_blocks_manual_activation(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    """
    Un event avec not_before_utc dans le futur ne peut pas être activé
    manuellement — le backend retourne 400 avec mention de l'embargo.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(
            playlist.id_playlist,
            event_name="Embargoed Event",
            not_before_utc=future,
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["not_before_utc"] is not None
    id_event = data["id_event"]

    resp = await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)
    assert resp.status_code == 400
    assert "embargo" in resp.json()["detail"].lower()


async def test_embargo_allows_activation_after_lift(
    client: AsyncClient, admin_token, playlist: CmsPlaylist
) -> None:
    """
    Un event avec not_before_utc dans le passé peut être activé normalement.
    """
    _, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    resp = await client.post(
        "/api/v1/events",
        json=_event_payload(
            playlist.id_playlist,
            event_name="Lifted Embargo Event",
            not_before_utc=past,
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    id_event = resp.json()["id_event"]

    resp = await client.post(f"/api/v1/events/{id_event}/activate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


# ── État reverting & cascade (§20.3 / §20.5) ─────────────────────────────────────

def test_revert_target_status() -> None:
    """Unit pur — décision d'état final après la phase transitoire 'reverting'."""
    from app.workers.event_worker import _revert_target_status

    # Non récurrent → toujours completed
    assert _revert_target_status(is_recurring=False, past_validity=False) == "completed"
    assert _revert_target_status(is_recurring=False, past_validity=True) == "completed"
    # Récurrent encore valide → inactive (se relancera) ; validité dépassée → completed
    assert _revert_target_status(is_recurring=True, past_validity=False) == "inactive"
    assert _revert_target_status(is_recurring=True, past_validity=True) == "completed"


def test_reapply_time_windows_pushes_graceful_to_online(monkeypatch) -> None:
    """Le tick beat re-pousse un sync *graceful* aux seuls players en ligne.

    Garantit que les fenêtres horaires (item-rules + règles de schedule) sont
    ré-évaluées périodiquement sans intervention (sinon un item 18h-19h ne s'éteint
    jamais tout seul), et sans coupure (preemptive=False → bascule à la frontière).
    """
    from app.workers import event_worker

    captured: dict = {}

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        def fetchall(self):
            return [(11,), (22,)]

    class _FakeConn:
        def cursor(self, *a, **k):
            return _FakeCursor()

        def commit(self):
            captured["committed"] = True

        def rollback(self):
            captured["rolledback"] = True

        def close(self):
            captured["closed"] = True

    pushed: dict = {}
    monkeypatch.setattr(event_worker, "_db_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        event_worker,
        "_push_sync",
        lambda ids, is_preemptive=False: pushed.update(ids=list(ids), preemptive=is_preemptive),
    )

    result = event_worker.reapply_time_windows()

    assert result == {"players_synced": 2}
    assert pushed["ids"] == [11, 22]
    assert pushed["preemptive"] is False  # graceful — appliqué à la frontière, pas de coupure
    assert "last_seen_at" in captured["sql"]  # restreint aux players en ligne
    assert captured.get("committed") is True


async def test_event_reverts_in_cascade(
    db_session: AsyncSession, org: CmsOrganization, playlist: CmsPlaylist, monkeypatch
) -> None:
    """
    Cascade de revert (§20.3 étape 7) : quand l'event actif de tête passe en 'reverting',
    le player recalcule sa pile et l'event actif suivant (priorité inférieure) reprend la
    main — _resolve_sync_payload ne retient que les events status='active'.
    """
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload
    from app.workers.event_worker import _revert_target_status

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    player = CmsPlayer(id_org=org.id_org, player_name="Cascade Player", player_os="linux")
    db_session.add(player)

    playlist_lo = CmsPlaylist(id_org=org.id_org, playlist_name="Low Prio Playlist")
    db_session.add(playlist_lo)
    await db_session.flush()

    target = {"target_type": "org", "target_ids": []}
    ev_hi = CmsEvent(
        id_org=org.id_org, event_name="High", event_type="manual", status="active",
        priority=90, id_playlist=playlist.id_playlist, target_config=target,
    )
    ev_lo = CmsEvent(
        id_org=org.id_org, event_name="Low", event_type="manual", status="active",
        priority=50, id_playlist=playlist_lo.id_playlist, target_config=target,
    )
    db_session.add_all([ev_hi, ev_lo])
    await db_session.commit()

    # Deux events actifs → l'event prioritaire (90) gagne
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["id_event"] == ev_hi.id_event
    assert payload["id_playlist"] == playlist.id_playlist

    # L'event de tête passe en 'reverting' (active→reverting, ce que fait expire_events/deactivate)
    ev_hi.status = "reverting"
    await db_session.commit()

    # Cascade : l'event de priorité inférieure encore actif reprend la main
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["id_event"] == ev_lo.id_event
    assert payload["id_playlist"] == playlist_lo.id_playlist

    # Finalisation : non récurrent → completed ; ev_lo reste actif et gagnant
    ev_hi.status = _revert_target_status(is_recurring=ev_hi.is_recurring, past_validity=False)
    await db_session.commit()
    assert ev_hi.status == "completed"

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["id_event"] == ev_lo.id_event


async def test_single_media_event_wall_clock_offset_for_lan_group(
    db_session: AsyncSession, org: CmsOrganization, monkeypatch
) -> None:
    """Event mono-média (id_media, bouclé) sur un groupe LAN Sync : le serveur calcule un
    start_offset_ms wall-clock (depuis activated_at, modulo la durée vidéo) pour aligner tous
    les membres. Un player HORS groupe LAN garde offset 0 (synchro apparente = horloges NTP)."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    media = CmsMedia(
        id_org=org.id_org, media_name="Loop Clip", media_type="video",
        storage_key="test/loop.mp4", checksum_sha256="vid1", source="upload",
        duration_ms=10000,
    )
    db_session.add(media)
    await db_session.flush()

    ev = CmsEvent(
        id_org=org.id_org, event_name="Loop Event", event_type="manual", status="active",
        priority=90, id_media=media.id_media,
        target_config={"target_type": "org", "target_ids": []},
        activated_at=datetime.now(UTC) - timedelta(seconds=3),
    )
    db_session.add(ev)

    lan_player = CmsPlayer(
        id_org=org.id_org, player_name="Wall L", player_os="linux",
        display_config={"lan_sync_enabled": True, "lan_sync_group": "wall"},
    )
    solo_player = CmsPlayer(id_org=org.id_org, player_name="Solo", player_os="linux")
    db_session.add_all([lan_player, solo_player])
    await db_session.commit()

    # Membre du groupe LAN → offset wall-clock dans (0, durée vidéo).
    p_lan = await _resolve_sync_payload(db_session, lan_player.id_player)
    assert p_lan["id_media"] == media.id_media
    assert 0 < p_lan["start_offset_ms"] < media.duration_ms

    # Player hors groupe LAN → offset 0 (pas d'alignement serveur).
    p_solo = await _resolve_sync_payload(db_session, solo_player.id_player)
    assert p_solo["start_offset_ms"] == 0


async def test_single_media_event_offset_uses_event_loop_period(
    db_session: AsyncSession, org: CmsOrganization, monkeypatch
) -> None:
    """Quand l'event impose une durée d'affichage ≠ durée naturelle de la vidéo, le renderer
    reboucle à active_event.duration_ms. Le modulo wall-clock DOIT donc utiliser cette période
    (et non media.duration_ms), sinon l'offset tombe hors de la fenêtre de boucle → désync."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    media = CmsMedia(
        id_org=org.id_org, media_name="Long Clip", media_type="video",
        storage_key="test/long.mp4", checksum_sha256="vid2", source="upload",
        duration_ms=10000,   # durée naturelle
    )
    db_session.add(media)
    await db_session.flush()

    ev = CmsEvent(
        id_org=org.id_org, event_name="Short Loop", event_type="manual", status="active",
        priority=90, id_media=media.id_media,
        duration_ms=4000,   # période d'affichage imposée < durée naturelle → le renderer reboucle à 4000
        target_config={"target_type": "org", "target_ids": []},
        activated_at=datetime.now(UTC) - timedelta(seconds=5),   # 5000ms : 5000%4000=1000, 5000%10000=5000
    )
    db_session.add(ev)

    lan_player = CmsPlayer(
        id_org=org.id_org, player_name="Wall L2", player_os="linux",
        display_config={"lan_sync_enabled": True, "lan_sync_group": "wall2"},
    )
    db_session.add(lan_player)
    await db_session.commit()

    p_lan = await _resolve_sync_payload(db_session, lan_player.id_player)
    # L'offset doit rester DANS la période de boucle de l'event (4000ms). Avec l'ancien modulo
    # sur media.duration_ms il vaudrait ~5000ms → hors fenêtre (échec de cette assertion).
    assert 0 < p_lan["start_offset_ms"] < ev.duration_ms


# ── Récurrence par intervalle (« spot toutes les N min ») — Feature A 2026-06-14 ─────
def test_interval_recurrence_slot_logic():
    """Mode intervalle : deux instants du MÊME créneau de N min → même slot_start (pas de
    ré-activation) ; créneaux différents ou jours différents → slot_start distinct (ré-activation).
    Test pur (sans DB), robuste à SIGNFLOW_TZ (compare des slots entre eux)."""
    from datetime import UTC, datetime
    from app.workers.event_worker import _interval_minutes, _interval_slot_start

    tc = {
        "recurrence": {"type": "interval", "every_minutes": 60},
        "conditions": [{"source": "schedule", "time_start": "09:00", "time_end": "19:00"}],
    }
    # Détection du mode
    assert _interval_minutes(tc) == 60
    assert _interval_minutes({"recurrence": {"type": "interval", "every_minutes": 0}}) is None
    assert _interval_minutes({"recurrence": {"type": "always"}}) is None
    assert _interval_minutes({}) is None
    assert _interval_minutes(None) is None

    base    = datetime(2026, 7, 3, 9, 5, tzinfo=UTC)
    same    = datetime(2026, 7, 3, 9, 7, tzinfo=UTC)    # +2 min → même créneau de 60 min
    nxt     = datetime(2026, 7, 3, 11, 5, tzinfo=UTC)   # +120 min → 2 créneaux plus loin
    nextday = datetime(2026, 7, 4, 9, 5, tzinfo=UTC)    # lendemain, même heure → créneau distinct

    s_base = _interval_slot_start(tc, 60, base)
    assert s_base is not None
    assert _interval_slot_start(tc, 60, same) == s_base       # même créneau → cooldown actif
    assert _interval_slot_start(tc, 60, nxt) != s_base        # créneau suivant → ré-activation
    assert _interval_slot_start(tc, 60, nextday) != s_base    # jour différent → ré-activation

    # Sans fenêtre (pas de time_start) : repli ancrage minuit local — doit quand même donner des
    # créneaux cohérents (même heure même créneau, +120 min créneau distinct).
    tc_nowin = {"recurrence": {"type": "interval", "every_minutes": 60}}
    assert _interval_slot_start(tc_nowin, 60, same) == _interval_slot_start(tc_nowin, 60, base)
    assert _interval_slot_start(tc_nowin, 60, nxt) != _interval_slot_start(tc_nowin, 60, base)


def test_spot_cooldown_survives_finalize():
    """Décision de cooldown end-to-end (`_in_same_occurrence`) — régression du bug terrain
    2026-06-15 : un spot play-once recurring rejouait EN CONTINU car `finalize_reverting_events`
    nullait `activated_at`. Le fix conserve `activated_at` ; ce test valide qu'avec ce marqueur
    préservé, le cooldown bloque la même occurrence et autorise la suivante.

    `_in_same_occurrence(trigger_config, every_min, last_act, now)` == True ⟹ déjà joué (skip)."""
    from datetime import UTC, datetime
    from app.workers.event_worker import _in_same_occurrence, _interval_minutes

    # — Mode INTERVALLE (spot toutes les 10 min, fenêtre 9h-19h) —
    tc_int = {
        "recurrence": {"type": "interval", "every_minutes": 10},
        "conditions": [{"source": "schedule", "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                        "time_start": "09:00", "time_end": "19:00"}],
    }
    em = _interval_minutes(tc_int)
    last = datetime(2026, 7, 3, 9, 5, tzinfo=UTC)
    # Le scénario du bug : last_act survit au finalize → ces instants sont dans le MÊME créneau
    # de 10 min → on NE doit PAS ré-activer (avant le fix, activated_at=NULL → on ré-activait).
    assert _in_same_occurrence(tc_int, em, last, datetime(2026, 7, 3, 9, 6, tzinfo=UTC)) is True
    assert _in_same_occurrence(tc_int, em, last, datetime(2026, 7, 3, 9, 9, tzinfo=UTC)) is True
    # Créneau suivant → ré-activation autorisée.
    assert _in_same_occurrence(tc_int, em, last, datetime(2026, 7, 3, 9, 12, tzinfo=UTC)) is False
    # Lendemain → ré-activation autorisée (slot absolu distinct).
    assert _in_same_occurrence(tc_int, em, last, datetime(2026, 7, 4, 9, 5, tzinfo=UTC)) is False

    # — Mode FENÊTRE play-once (sans intervalle) : 1× par occurrence de fenêtre / jour —
    tc_win = {
        "conditions": [{"source": "schedule", "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                        "time_start": "09:00", "time_end": "19:00"}],
    }
    last_w = datetime(2026, 7, 3, 9, 30, tzinfo=UTC)
    # Même jour, même fenêtre → déjà joué.
    assert _in_same_occurrence(tc_win, None, last_w, datetime(2026, 7, 3, 15, 0, tzinfo=UTC)) is True
    # Lendemain, même fenêtre → nouvelle occurrence → ré-activation.
    assert _in_same_occurrence(tc_win, None, last_w, datetime(2026, 7, 4, 9, 30, tzinfo=UTC)) is False
