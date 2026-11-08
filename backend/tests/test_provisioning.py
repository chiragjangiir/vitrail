"""
Tests Sprint 1.6 — Provisioning tokens + enregistrement player (§XXIX.2).

Couvre :
  - test_create_provisioning_token_returns_token_value
  - test_list_provisioning_tokens
  - test_player_register_with_valid_token
  - test_player_register_respects_max_uses
  - test_player_register_expired_token_rejected
  - test_revoke_provisioning_token
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"prov-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="ProvOrg", org_slug=slug)
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
        email=f"admin-{uid}@prov.test",
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
def admin_token(org_admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


def _expires_future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


def _expires_past() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_create_provisioning_token_returns_token_value(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Player Windows", "expires_at": _expires_future(), "max_uses": 5},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["token_value"].startswith("sfp_")
    assert len(data["token_value"]) > 20
    assert data["key_prefix"] == data["token_value"][:12]
    assert data["use_count"] == 0
    assert data["max_uses"] == 5
    assert data["is_active"] is True


async def test_list_provisioning_tokens(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Token List Test", "expires_at": _expires_future()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert len(tokens) >= 1
    # token_value absent dans la liste (uniquement à la création)
    assert all(t.get("token_value") is None for t in tokens)


async def test_provisioning_payload_create_then_reattach(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}

    # 1) Génère un payload (création) → pré-crée le player + token sfp_ lié.
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-payload",
        json={"ref": "Boutique Lyon", "os": "android",
              "backend_url": "https://cms.example", "options": {"resolution": "1920x1080"}},
        headers=h)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["token"].startswith("sfp_")
    assert p["os"] == "android" and p["backend_url"] == "https://cms.example"
    pid = p["id_player"]
    assert pid is not None

    # 2) Le device s'enregistre → se ré-attache au player pré-créé (pas de doublon).
    r = await client.post(
        "/api/v1/players/register",
        json={"player_name": "x", "player_os": "android", "org_token": p["token"]})
    assert r.status_code == 201, r.text
    assert r.json()["id_player"] == pid

    # 3) Payload de RÉ-ATTACHE explicite vers ce player.
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-payload",
        json={"ref": "Boutique Lyon", "os": "android", "id_player": pid}, headers=h)
    assert r.status_code == 201, r.text
    p2 = r.json()
    assert p2["id_player"] == pid

    # 4) Register avec ce token → MÊME player (anti-doublon).
    r = await client.post(
        "/api/v1/players/register",
        json={"player_name": "y", "player_os": "android", "org_token": p2["token"]})
    assert r.status_code == 201
    assert r.json()["id_player"] == pid

    # 5) Player cible inexistant → 404.
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-payload",
        json={"ref": "z", "os": "android", "id_player": 999999}, headers=h)
    assert r.status_code == 404


async def test_player_register_with_valid_token(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Windows Player", "expires_at": _expires_future()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    org_token = create_resp.json()["token_value"]

    resp = await client.post(
        "/api/v1/players/register",
        json={
            "player_name": f"win-{uuid.uuid4().hex[:8]}",
            "player_os": "windows",
            "player_version": "1.6.0",
            "org_token": org_token,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "player_token" in data
    assert "id_player" in data
    assert "expires_at" in data
    assert len(data["player_token"]) > 20


async def test_player_register_respects_max_uses(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Max Uses 1", "expires_at": _expires_future(), "max_uses": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    org_token = create_resp.json()["token_value"]
    payload = {
        "player_name": f"win-{uuid.uuid4().hex[:8]}",
        "player_os": "windows",
        "org_token": org_token,
    }

    resp1 = await client.post("/api/v1/players/register", json=payload)
    assert resp1.status_code == 201

    payload["player_name"] = f"win-{uuid.uuid4().hex[:8]}"
    resp2 = await client.post("/api/v1/players/register", json=payload)
    assert resp2.status_code == 409


async def test_player_register_reattaches_by_serial(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    """Ré-attache idempotente (P0 self-heal) : un device qui re-`register` avec un n° de série DÉJÀ
    connu est ré-attaché au player existant (même id_player), sans 409 ni doublon, même si le token
    de provisioning est ÉPUISÉ (max_uses atteint) — cas du BrightSign qui perd son JWT au saut de
    firmware (wipe du profil Chromium)."""
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Serial reattach", "expires_at": _expires_future(), "max_uses": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    org_token = create_resp.json()["token_value"]
    serial = f"SN-{uuid.uuid4().hex[:10]}"

    def _body(name: str, sn: str) -> dict:
        return {
            "player_name": name, "player_os": "brightsign",
            "org_token": org_token, "serial": sn,
        }

    # 1re inscription (consomme l'unique usage) → crée le player + sème le serial.
    r1 = await client.post("/api/v1/players/register", json=_body("bs-1", serial))
    assert r1.status_code == 201
    id_player = r1.json()["id_player"]

    # Re-`register` (token épuisé) avec le MÊME serial → ré-attache (201, même player), PAS 409.
    r2 = await client.post("/api/v1/players/register", json=_body("bs-1", serial))
    assert r2.status_code == 201, r2.text
    assert r2.json()["id_player"] == id_player
    assert len(r2.json()["player_token"]) > 20

    # Un serial INCONNU avec le même token épuisé → pas de ré-attache → 409 (max_uses respecté).
    r3 = await client.post(
        "/api/v1/players/register", json=_body("bs-2", f"SN-{uuid.uuid4().hex[:10]}")
    )
    assert r3.status_code == 409


async def test_player_register_expired_token_rejected(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "Expired", "expires_at": _expires_past()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    org_token = create_resp.json()["token_value"]

    resp = await client.post(
        "/api/v1/players/register",
        json={"player_name": "win-expired", "player_os": "windows", "org_token": org_token},
    )
    assert resp.status_code == 401


async def test_revoke_provisioning_token(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "To Revoke", "expires_at": _expires_future()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    id_key = create_resp.json()["id_key"]
    org_token = create_resp.json()["token_value"]

    revoke_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens/{id_key}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoke_resp.status_code == 204

    # Tentative d'enregistrement avec token révoqué → 401
    resp = await client.post(
        "/api/v1/players/register",
        json={"player_name": "win-revoked", "player_os": "windows", "org_token": org_token},
    )
    assert resp.status_code == 401


async def test_delete_provisioning_token(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    create_resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "To Delete", "expires_at": _expires_future()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    id_key = create_resp.json()["id_key"]

    # Révoquer d'abord
    await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens/{id_key}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Puis supprimer définitivement
    del_resp = await client.delete(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens/{id_key}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    # Plus dans la liste
    list_resp = await client.get(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ids = [t["id_key"] for t in list_resp.json()]
    assert id_key not in ids


async def test_create_token_without_expiry(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    """Token sans expiration (expires_at=null) — doit être créé et fonctionner."""
    resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-tokens",
        json={"label": "No expiry token"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is None
    assert data["is_active"] is True


# ── Clé opérateur de provisioning (§XXIX) ────────────────────────────────────────

async def test_operator_key_create_use_and_revoke(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    """Cycle clé opérateur : l'org-admin la crée, elle sert à créer un payload + lire whoami/status
    SANS JWT, puis révoquée elle est rejetée."""
    h_admin = {"Authorization": f"Bearer {admin_token}"}

    # 1) Création (org-admin) → renvoie sfk_ une seule fois.
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-keys",
        json={"label": "Terrain 2026", "expires_in_days": 90}, headers=h_admin)
    assert r.status_code == 201, r.text
    key = r.json()["token_value"]
    assert key.startswith("sfk_")
    id_key = r.json()["id_key"]
    h_key = {"Authorization": f"Bearer {key}"}

    # 2) whoami avec la clé → bonne org, kind=key.
    r = await client.get("/api/v1/provisioning/whoami", headers=h_key)
    assert r.status_code == 200, r.text
    assert r.json() == {"id_org": org.id_org, "kind": "key"}

    # 3) La clé crée un payload (comme un org-admin) → pré-crée le player.
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-payload",
        json={"ref": "PC Accueil", "os": "windows", "backend_url": "https://cms.example"},
        headers=h_key)
    assert r.status_code == 201, r.text
    pid = r.json()["id_player"]
    assert r.json()["token"].startswith("sfp_")

    # 4) status du player avec la clé (poll online).
    r = await client.get(f"/api/v1/provisioning/players/{pid}/status", headers=h_key)
    assert r.status_code == 200, r.text
    assert r.json()["id_player"] == pid and "status" in r.json()

    # 5) Liste (org-admin) — la clé y figure, jamais le secret.
    r = await client.get(f"/api/v1/orgs/{org.id_org}/provisioning-keys", headers=h_admin)
    assert r.status_code == 200
    assert any(k["id_key"] == id_key for k in r.json())
    assert all(k.get("token_value") is None for k in r.json())

    # 6) Révocation → la clé est rejetée (401).
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-keys/{id_key}/revoke", headers=h_admin)
    assert r.status_code == 204
    r = await client.get("/api/v1/provisioning/whoami", headers=h_key)
    assert r.status_code == 401


async def test_operator_key_scoped_to_its_org(
    client: AsyncClient, admin_token: str, org: CmsOrganization
) -> None:
    """Une clé opérateur ne peut créer un payload que pour SON org (cross-org → 403)."""
    h_admin = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        f"/api/v1/orgs/{org.id_org}/provisioning-keys",
        json={"label": "Scoped", "expires_in_days": 30}, headers=h_admin)
    key = r.json()["token_value"]
    r = await client.post(
        f"/api/v1/orgs/{org.id_org + 99999}/provisioning-payload",
        json={"ref": "x", "os": "linux"},
        headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403


async def test_provisioning_endpoints_reject_garbage_key(client: AsyncClient) -> None:
    """Une clé sfk_ inconnue est rejetée (401)."""
    r = await client.get(
        "/api/v1/provisioning/whoami",
        headers={"Authorization": "Bearer sfk_inexistante"})
    assert r.status_code == 401
