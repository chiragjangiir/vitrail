"""
Tests Sprint 2.3 — Display Control RS232/IP (§2.10).

Couvre :
  - test_player_read_exposes_display_config
  - test_update_display_config_rs232
  - test_update_display_config_ip
  - test_update_display_config_clear
  - test_display_command_power_on_publishes_to_redis
  - test_display_command_set_brightness_with_params
  - test_display_command_invalid_returns_422
  - test_display_command_unknown_player_returns_404
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    slug = f"display-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="DisplayOrg", org_slug=slug)
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
        email=f"admin-{uid}@display-test.com",
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
        json={"player_name": f"display-player-{uuid.uuid4().hex[:8]}", "player_os": "linux"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_player"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_redis():
    """Retourne un patch context manager pour aioredis.from_url."""
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.aclose = AsyncMock()
    mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
    mock_redis.__aexit__ = AsyncMock(return_value=None)

    patcher = patch(
        "app.api.v1.endpoints.players.aioredis.from_url",
        return_value=mock_redis,
    )
    return patcher, mock_redis


# ── Tests — PlayerRead.display_config ─────────────────────────────────────────

async def test_player_read_exposes_display_config(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """GET /players/{id} doit inclure le champ display_config (null par defaut)."""
    resp = await client.get(
        f"/api/v1/players/{player_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "display_config" in data
    assert data["display_config"] is None


# ── Tests — PUT display_config ─────────────────────────────────────────────────

async def test_update_display_config_rs232(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """PUT /players/{id} avec display_config RS232 doit persister la config."""
    cfg = {
        "type": "rs232",
        "serial_port": "/dev/ttyUSB0",
        "baud_rate": 9600,
        "model": "samsung_mdc",
        "address": 1,
        "lan_sync_enabled": False,
    }
    resp = await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": cfg},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_config"]["type"] == "rs232"
    assert data["display_config"]["serial_port"] == "/dev/ttyUSB0"
    assert data["display_config"]["model"] == "samsung_mdc"


async def test_update_display_config_ip(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """PUT /players/{id} avec display_config IP doit persister host + tcp_port."""
    cfg = {
        "type": "ip",
        "host": "192.168.1.55",
        "tcp_port": 1515,
        "model": "samsung_mdc",
        "address": 1,
        "lan_sync_enabled": True,
        "lan_sync_group": "videowall-a",
    }
    resp = await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": cfg},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_config"]["type"] == "ip"
    assert data["display_config"]["host"] == "192.168.1.55"
    assert data["display_config"]["tcp_port"] == 1515
    assert data["display_config"]["lan_sync_enabled"] is True


async def test_update_display_config_clear(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """PUT /players/{id} avec display_config=null doit effacer la config."""
    # Definir une config d'abord
    await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": {"type": "rs232", "serial_port": "/dev/ttyUSB0"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Puis la supprimer
    resp = await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_config"] is None


# ── Tests — POST /display/command ─────────────────────────────────────────────

async def test_display_command_power_on_publishes_to_redis(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """POST /players/{id}/display/command power_on doit publier dans Redis (202)."""
    patcher, mock_redis = _mock_redis()
    with patcher:
        resp = await client.post(
            f"/api/v1/players/{player_id}/display/command",
            json={"command": "power_on"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "sent"
    assert data["display_cmd"] == "power_on"

    # Verifier que publish a bien ete appele avec le bon canal et la bonne commande
    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args[0]
    channel   = call_args[0]
    payload   = json.loads(call_args[1])

    assert channel == f"signflow:player:{player_id}:cmds"
    assert payload["type"] == "player:command"
    assert payload["command"] == "display_command"
    assert payload["params"]["display_cmd"] == "power_on"


async def test_display_command_set_brightness_with_params(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """set_brightness avec params.level doit etre inclus dans le payload Redis."""
    patcher, mock_redis = _mock_redis()
    with patcher:
        resp = await client.post(
            f"/api/v1/players/{player_id}/display/command",
            json={"command": "set_brightness", "params": {"level": 75}},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 202
    payload = json.loads(mock_redis.publish.call_args[0][1])
    assert payload["params"]["display_cmd"] == "set_brightness"
    assert payload["params"]["level"] == 75


async def test_display_command_set_input_with_source(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """set_input avec params.source doit etre inclus dans le payload Redis."""
    patcher, mock_redis = _mock_redis()
    with patcher:
        resp = await client.post(
            f"/api/v1/players/{player_id}/display/command",
            json={"command": "set_input", "params": {"source": "hdmi2"}},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 202
    payload = json.loads(mock_redis.publish.call_args[0][1])
    assert payload["params"]["display_cmd"] == "set_input"
    assert payload["params"]["source"] == "hdmi2"


async def test_display_command_invalid_command_returns_422(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """Une commande inconnue doit etre rejetee par Pydantic (422)."""
    resp = await client.post(
        f"/api/v1/players/{player_id}/display/command",
        json={"command": "reboot_display"},   # commande inexistante
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


async def test_display_command_unknown_player_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    """Un player inexistant doit retourner 404."""
    patcher, _ = _mock_redis()
    with patcher:
        resp = await client.post(
            "/api/v1/players/999999/display/command",
            json={"command": "power_on"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 404


async def test_update_display_config_with_schedule(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """PUT /players/{id} avec display_config incluant un schedule doit persister le schedule."""
    cfg = {
        "type": "rs232",
        "serial_port": "/dev/ttyUSB0",
        "baud_rate": 9600,
        "model": "samsung_mdc",
        "address": 1,
        "schedule": {
            "power_on": "08:30",
            "power_off": "19:30",
            "days": [1, 2, 3, 4, 5],
        },
    }
    resp = await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": cfg},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    sched = resp.json()["display_config"]["schedule"]
    assert sched["power_on"] == "08:30"
    assert sched["power_off"] == "19:30"
    assert sched["days"] == [1, 2, 3, 4, 5]


async def test_update_display_config_schedule_cleared_with_config(
    client: AsyncClient, admin_token: str, player_id: int
) -> None:
    """Effacer display_config (null) doit aussi effacer le schedule."""
    # Definir une config avec schedule
    await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": {
            "type": "ip", "host": "192.168.1.10", "tcp_port": 1515,
            "schedule": {"power_on": "09:00", "power_off": "18:00"},
        }},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Effacer la config
    resp = await client.put(
        f"/api/v1/players/{player_id}",
        json={"display_config": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_config"] is None
