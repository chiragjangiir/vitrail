"""
Tests Sprint 1.7 — Player Groups CRUD + assignment (§III).

Covers:
  - test_create_group
  - test_list_groups
  - test_update_group
  - test_add_player_to_group
  - test_list_group_players
  - test_remove_player_from_group
  - test_delete_group
  - test_player_stats
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"grp-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="GroupOrg", org_slug=slug)
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
        email=f"admin-{uid}@grptest.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

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
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


@pytest_asyncio.fixture
async def player_id(client: AsyncClient, admin_token: str) -> int:
    resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"grp-player-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_player"]


@pytest_asyncio.fixture
async def group_id(client: AsyncClient, admin_token: str) -> int:
    resp = await client.post(
        "/api/v1/player-groups/",
        json={"group_name": f"Group-{uuid.uuid4().hex[:8]}", "description": "Test group"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_group"]


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_create_group(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/player-groups/",
        json={"group_name": f"Zone-{uuid.uuid4().hex[:8]}", "description": "Retail zone A"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id_group" in data
    assert data["description"] == "Retail zone A"


async def test_list_groups(client: AsyncClient, admin_token: str, group_id: int) -> None:
    resp = await client.get(
        "/api/v1/player-groups/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    ids = [g["id_group"] for g in resp.json()]
    assert group_id in ids


async def test_update_group(client: AsyncClient, admin_token: str, group_id: int) -> None:
    new_name = f"Updated-{uuid.uuid4().hex[:8]}"
    resp = await client.put(
        f"/api/v1/player-groups/{group_id}",
        json={"group_name": new_name},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["group_name"] == new_name


async def test_add_player_to_group(
    client: AsyncClient, admin_token: str, group_id: int, player_id: int
) -> None:
    resp = await client.post(
        f"/api/v1/player-groups/{group_id}/players",
        json={"id_player": player_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


async def test_add_player_idempotent(
    client: AsyncClient, admin_token: str, group_id: int, player_id: int
) -> None:
    for _ in range(2):
        resp = await client.post(
            f"/api/v1/player-groups/{group_id}/players",
            json={"id_player": player_id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204


async def test_list_group_players(
    client: AsyncClient, admin_token: str, group_id: int, player_id: int
) -> None:
    await client.post(
        f"/api/v1/player-groups/{group_id}/players",
        json={"id_player": player_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        f"/api/v1/player-groups/{group_id}/players",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    ids = [p["id_player"] for p in resp.json()]
    assert player_id in ids


async def test_remove_player_from_group(
    client: AsyncClient, admin_token: str, group_id: int, player_id: int
) -> None:
    await client.post(
        f"/api/v1/player-groups/{group_id}/players",
        json={"id_player": player_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.delete(
        f"/api/v1/player-groups/{group_id}/players/{player_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204

    list_resp = await client.get(
        f"/api/v1/player-groups/{group_id}/players",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ids = [p["id_player"] for p in list_resp.json()]
    assert player_id not in ids


async def test_delete_group(client: AsyncClient, admin_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/player-groups/",
        json={"group_name": f"ToDelete-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    gid = create_resp.json()["id_group"]

    del_resp = await client.delete(
        f"/api/v1/player-groups/{gid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/player-groups/{gid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 404


async def test_player_stats(client: AsyncClient, admin_token: str, player_id: int) -> None:
    resp = await client.get(
        "/api/v1/players/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "online" in data
    assert "offline" in data
    assert "warning" in data
    assert data["total"] >= 1


async def test_delete_group_cleans_generic_targets(
    client: AsyncClient, admin_token: str, group_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    """La suppression d'un GROUPE retire aussi ses cibles GÉNÉRIQUES sans FK :
    lignes cms_schedule_targets (target_type group/player_group) + id dans les
    target_ids JSONB des events — même fuite que la suppression de player
    (fix f5ac283), constatée côté player en prod le 2026-07-07."""
    from app.models.event import CmsEvent
    from app.models.schedule import CmsSchedule, CmsScheduleTarget

    sched = CmsSchedule(id_org=org.id_org, schedule_name="S-ghost-grp", schedule_kind="content")
    ev = CmsEvent(
        id_org=org.id_org, event_name="E-ghost-grp", event_type="manual", event_kind="content",
        target_config={"target_type": "group", "target_ids": [group_id, 888888]},
    )
    db_session.add_all([sched, ev])
    await db_session.flush()
    db_session.add(CmsScheduleTarget(
        id_schedule=sched.id_schedule, target_type="group", target_id=group_id))
    db_session.add(CmsScheduleTarget(
        id_schedule=sched.id_schedule, target_type="player_group", target_id=group_id))
    await db_session.commit()
    ev_id, sched_id = ev.id_event, sched.id_schedule

    del_resp = await client.delete(
        f"/api/v1/player-groups/{group_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    db_session.expire_all()
    ev2 = (await db_session.execute(
        select(CmsEvent).where(CmsEvent.id_event == ev_id))).scalar_one()
    ids = (ev2.target_config or {}).get("target_ids", [])
    assert group_id not in ids     # le groupe supprimé n'est plus ciblé
    assert 888888 in ids           # les autres cibles sont préservées
    left = (await db_session.execute(select(CmsScheduleTarget).where(
        CmsScheduleTarget.id_schedule == sched_id))).scalars().all()
    assert left == []              # les 2 alias (group + player_group) sont purgés
