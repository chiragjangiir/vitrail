"""Coffre-fort de clés API IA par organisation (BYOK §XXVII) — socle session A.

Vérifie : chiffrement round-trip + indisponibilité sans clé de coffre ; stockage chiffré
(jamais en clair) + masquage last4 + statut ; les branches de resolve_ai_credentials
(clé org → byok ; strict sans clé → None ; platform Anthropic autorisé → clé plateforme ;
génération fal/elevenlabs toujours strict ; platform sans ANTHROPIC_API_KEY → None).
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.api.v1.endpoints.assistant as assistant_ep
from app.core.config import settings
from app.models.assistant import CmsAssistantStat
from app.core.crypto import (
    VaultKeyMissing,
    decrypt_secret,
    encrypt_secret,
    vault_available,
)
from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services import ai_credentials
from app.services.ai_credentials import (
    delete_org_key,
    get_org_key_row,
    resolve_ai_credentials,
    upsert_org_key,
)

_SEQ = [0]


def _uid() -> int:
    _SEQ[0] += 1
    return _SEQ[0]


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Fournit une clé de coffre fraîche à chaque test (sauf override explicite)."""
    monkeypatch.setattr(settings, "CMS_VAULT_KEY", Fernet.generate_key().decode())


async def _org(db, **kw) -> CmsOrganization:
    o = CmsOrganization(org_name=f"AiOrg{_uid()}", org_slug=f"ai-{_uid()}", **kw)
    db.add(o)
    await db.flush()
    return o


# ── Chiffrement ──────────────────────────────────────────────────────────────

def test_encrypt_round_trip():
    token = encrypt_secret("sk-ant-secret-1234")
    assert token != "sk-ant-secret-1234"  # bien chiffré
    assert decrypt_secret(token) == "sk-ant-secret-1234"


def test_encrypt_is_non_deterministic():
    # Fernet inclut un IV/timestamp → deux chiffrés du même clair diffèrent.
    assert encrypt_secret("same") != encrypt_secret("same")


def test_vault_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(settings, "CMS_VAULT_KEY", None)
    assert vault_available() is False
    with pytest.raises(VaultKeyMissing):
        encrypt_secret("x")


def test_vault_invalid_key(monkeypatch):
    monkeypatch.setattr(settings, "CMS_VAULT_KEY", "pas-une-cle-fernet")
    assert vault_available() is False
    with pytest.raises(VaultKeyMissing):
        encrypt_secret("x")


# ── Stockage ─────────────────────────────────────────────────────────────────

async def test_upsert_stores_encrypted_with_last4(db_session):
    org = await _org(db_session)
    row = await upsert_org_key(db_session, org.id_org, "fal", "fal-key-abcd1234", created_by=None)
    assert row.secret_encrypted != "fal-key-abcd1234"        # jamais en clair
    assert decrypt_secret(row.secret_encrypted) == "fal-key-abcd1234"
    assert row.key_last4 == "1234"
    assert row.status == "unverified"


async def test_upsert_replaces_and_resets_status(db_session):
    org = await _org(db_session)
    row = await upsert_org_key(db_session, org.id_org, "fal", "old-key-0000")
    row.status = "valid"
    await db_session.flush()
    row2 = await upsert_org_key(db_session, org.id_org, "fal", "new-key-9999")
    assert row2.id_credential == row.id_credential               # même ligne (upsert)
    assert decrypt_secret(row2.secret_encrypted) == "new-key-9999"
    assert row2.key_last4 == "9999"
    assert row2.status == "unverified"                            # statut réinitialisé
    assert row2.validated_at is None


async def test_delete_org_key(db_session):
    org = await _org(db_session)
    await upsert_org_key(db_session, org.id_org, "elevenlabs", "el-key-5678")
    assert await delete_org_key(db_session, org.id_org, "elevenlabs") is True
    assert await get_org_key_row(db_session, org.id_org, "elevenlabs") is None
    assert await delete_org_key(db_session, org.id_org, "elevenlabs") is False


# ── Résolution (le cœur de la politique) ──────────────────────────────────────

async def test_resolve_org_key_is_byok(db_session):
    org = await _org(db_session, ai_byok_mode="strict")
    await upsert_org_key(db_session, org.id_org, "anthropic", "sk-org-key-aaaa")
    resolved = await resolve_ai_credentials(db_session, org, "anthropic")
    assert resolved is not None
    assert resolved.api_key == "sk-org-key-aaaa"
    assert resolved.byok is True
    assert resolved.source == "org"


async def test_resolve_strict_without_key_is_disabled(db_session):
    org = await _org(db_session, ai_byok_mode="strict")
    assert await resolve_ai_credentials(db_session, org, "anthropic") is None


async def test_resolve_platform_authorized_uses_platform_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-platform-ed")
    org = await _org(db_session, ai_byok_mode="platform")
    resolved = await resolve_ai_credentials(db_session, org, "anthropic")
    assert resolved is not None
    assert resolved.api_key == "sk-platform-ed"
    assert resolved.byok is False          # plateforme → quota appliqué
    assert resolved.source == "platform"


async def test_resolve_org_key_overrides_platform(db_session, monkeypatch):
    # Même en mode platform, la clé de l'org prime (le client paie).
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-platform-ed")
    org = await _org(db_session, ai_byok_mode="platform")
    await upsert_org_key(db_session, org.id_org, "anthropic", "sk-org-key-bbbb")
    resolved = await resolve_ai_credentials(db_session, org, "anthropic")
    assert resolved is not None
    assert resolved.api_key == "sk-org-key-bbbb"
    assert resolved.byok is True


async def test_resolve_platform_uses_proxy_without_backend_key(db_session, monkeypatch):
    # Mode platform = proxy LiteLLM (qui détient la clé) → PAS désactivé même si le backend
    # n'a pas ANTHROPIC_API_KEY dans son env. byok=False → le caller passe par le proxy.
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    org = await _org(db_session, ai_byok_mode="platform")
    resolved = await resolve_ai_credentials(db_session, org, "anthropic")
    assert resolved is not None
    assert resolved.byok is False
    assert resolved.source == "platform"


async def test_resolve_generation_is_strict_even_in_platform_mode(db_session, monkeypatch):
    # fal/elevenlabs n'ont AUCUNE clé plateforme → toujours None sans clé org, quel que soit le mode.
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-platform-ed")
    org = await _org(db_session, ai_byok_mode="platform")
    assert await resolve_ai_credentials(db_session, org, "fal") is None
    assert await resolve_ai_credentials(db_session, org, "elevenlabs") is None


async def test_resolve_generation_org_key(db_session):
    org = await _org(db_session, ai_byok_mode="strict")
    await upsert_org_key(db_session, org.id_org, "fal", "fal-client-key-cccc")
    resolved = await resolve_ai_credentials(db_session, org, "fal")
    assert resolved is not None
    assert resolved.byok is True
    assert resolved.source == "org"


# ── Endpoints /orgs/{id}/ai-keys ──────────────────────────────────────────────

async def _admin_with_role(db, id_org, role_key):
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=id_org, email=f"{role_key.lower()}-{uid}@t.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.execute(
        pg_insert(CmsRole)
        .values(role_key=role_key, label=role_key, is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    token = create_access_token(
        user.id_user, extra={"org": id_org, "roles": [role_key], "locale": "en"}
    )
    return user, token


@pytest_asyncio.fixture
async def admin_ctx(db_session):
    org = await _org(db_session)
    await db_session.commit()
    _, token = await _admin_with_role(db_session, org.id_org, "CMS_ORG_ADMIN")
    return org, token


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def test_put_then_get_masks_secret(client: AsyncClient, admin_ctx):
    org, token = admin_ctx
    resp = await client.put(
        f"/api/v1/orgs/{org.id_org}/ai-keys",
        json={"provider": "fal", "api_key": "fal-secret-key-7788"},
        headers=_h(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "fal"
    assert data["key_last4"] == "7788"
    assert data["status"] == "unverified"
    # le secret ne ressort JAMAIS
    assert "api_key" not in data and "secret_encrypted" not in data
    assert "fal-secret-key-7788" not in resp.text

    lst = await client.get(f"/api/v1/orgs/{org.id_org}/ai-keys", headers=_h(token))
    assert lst.status_code == 200
    rows = lst.json()
    assert len(rows) == 1
    assert rows[0]["key_last4"] == "7788"
    assert "secret_encrypted" not in rows[0]


async def test_put_replaces_same_provider(client: AsyncClient, admin_ctx):
    org, token = admin_ctx
    await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                     json={"provider": "fal", "api_key": "old-0000"}, headers=_h(token))
    await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                     json={"provider": "fal", "api_key": "new-1111"}, headers=_h(token))
    rows = (await client.get(f"/api/v1/orgs/{org.id_org}/ai-keys", headers=_h(token))).json()
    assert len(rows) == 1 and rows[0]["key_last4"] == "1111"


async def test_delete_ai_key(client: AsyncClient, admin_ctx):
    org, token = admin_ctx
    await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                     json={"provider": "elevenlabs", "api_key": "el-2222"}, headers=_h(token))
    d = await client.delete(f"/api/v1/orgs/{org.id_org}/ai-keys/elevenlabs", headers=_h(token))
    assert d.status_code == 204
    rows = (await client.get(f"/api/v1/orgs/{org.id_org}/ai-keys", headers=_h(token))).json()
    assert rows == []
    # re-delete → 404
    assert (await client.delete(
        f"/api/v1/orgs/{org.id_org}/ai-keys/elevenlabs", headers=_h(token)
    )).status_code == 404


async def test_invalid_provider_rejected(client: AsyncClient, admin_ctx):
    org, token = admin_ctx
    resp = await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                            json={"provider": "openai", "api_key": "x"}, headers=_h(token))
    assert resp.status_code == 422


async def test_viewer_forbidden(client: AsyncClient, db_session):
    org = await _org(db_session)
    await db_session.commit()
    _, vtoken = await _admin_with_role(db_session, org.id_org, "CMS_VIEWER")
    resp = await client.get(f"/api/v1/orgs/{org.id_org}/ai-keys", headers=_h(vtoken))
    assert resp.status_code == 403


async def test_cross_org_is_404(client: AsyncClient, admin_ctx, db_session):
    org_a, token_a = admin_ctx
    org_b = await _org(db_session)
    await db_session.commit()
    resp = await client.get(f"/api/v1/orgs/{org_b.id_org}/ai-keys", headers=_h(token_a))
    assert resp.status_code == 404


async def test_put_without_vault_key_is_503(client: AsyncClient, admin_ctx, monkeypatch):
    org, token = admin_ctx
    monkeypatch.setattr(settings, "CMS_VAULT_KEY", None)
    resp = await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                            json={"provider": "fal", "api_key": "x-9999"}, headers=_h(token))
    assert resp.status_code == 503


async def test_test_endpoint_marks_valid(client: AsyncClient, admin_ctx, monkeypatch):
    org, token = admin_ctx
    await client.put(f"/api/v1/orgs/{org.id_org}/ai-keys",
                     json={"provider": "anthropic", "api_key": "sk-ant-3333"}, headers=_h(token))

    async def _fake_validate(provider, api_key):
        return True, "HTTP 200"

    monkeypatch.setattr(ai_credentials, "validate_provider_key", _fake_validate)
    resp = await client.post(
        f"/api/v1/orgs/{org.id_org}/ai-keys/anthropic/test", headers=_h(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "valid"
    rows = (await client.get(f"/api/v1/orgs/{org.id_org}/ai-keys", headers=_h(token))).json()
    assert rows[0]["status"] == "valid" and rows[0]["validated_at"] is not None


# ── Résolveur SYNC pour les workers Celery (feed/feedback) ────────────────────

class _FakeCursor:
    def __init__(self, results):
        self._results = list(results)
        self.closed = False
    def execute(self, *a, **k):
        pass
    def fetchone(self):
        return self._results.pop(0) if self._results else None
    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, results):
        self._cur = _FakeCursor(results)
    def cursor(self):
        return self._cur


def test_worker_resolver_org_key():
    conn = _FakeConn([(encrypt_secret("worker-org-key"),)])
    key, mode = ai_credentials.resolve_anthropic_for_worker(conn, 1)
    assert key == "worker-org-key" and mode == "org"


def test_worker_resolver_platform_uses_proxy():
    # platform → (None, "platform") : pas de clé renvoyée, le worker passe par le proxy.
    conn = _FakeConn([None, ("platform",)])
    assert ai_credentials.resolve_anthropic_for_worker(conn, 1) == (None, "platform")


def test_worker_resolver_strict_is_disabled():
    conn = _FakeConn([None, ("strict",)])
    assert ai_credentials.resolve_anthropic_for_worker(conn, 1) == (None, None)


def test_worker_resolver_provider_strict_byok():
    # fal/elevenlabs : strict BYOK, pas de plateforme → clé org ou None.
    conn = _FakeConn([(encrypt_secret("fal-org-key"),)])
    assert ai_credentials.resolve_provider_key_sync(conn, 1, "fal") == "fal-org-key"


def test_worker_resolver_provider_no_key():
    conn = _FakeConn([None])
    assert ai_credentials.resolve_provider_key_sync(conn, 1, "fal") is None


def test_fal_media_url_extraction():
    from app.services.generation import fal

    assert fal._media_url({"video": {"url": "http://x/v.mp4"}}, "video") == "http://x/v.mp4"
    assert fal._media_url({"video": "http://x/v.mp4"}, "video") == "http://x/v.mp4"
    assert fal._media_url({"videos": [{"url": "http://x/v.mp4"}]}, "video", "videos") == "http://x/v.mp4"
    assert fal._media_url({}, "video") is None


# ── Endpoint /assistant/chat — résolution BYOK + ai_disabled + quota ──────────

async def test_chat_ai_disabled_when_strict_no_key(client: AsyncClient, admin_ctx, monkeypatch):
    org, token = admin_ctx  # org strict, aucune clé
    called = {"n": 0}

    async def _fake_agent(db, **kw):
        called["n"] += 1
        yield "x"

    monkeypatch.setattr(assistant_ep, "run_agent", _fake_agent)
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={"messages": [{"role": "user", "content": "salut"}]},
        headers=_h(token),
    )
    assert resp.status_code == 200
    assert '"ai_disabled": true' in resp.text
    assert called["n"] == 0  # aucun appel modèle


async def test_chat_byok_bypasses_quota(client: AsyncClient, admin_ctx, db_session, monkeypatch):
    org, token = admin_ctx
    org.ai_quota_unit = "tokens"
    org.ai_quota_tokens = 1  # quota minuscule
    db_session.add(CmsAssistantStat(
        id_org=org.id_org, stat_date=date.today(), token_count=999, message_count=5
    ))
    await upsert_org_key(db_session, org.id_org, "anthropic", "sk-org-byok")
    await db_session.commit()
    captured: dict = {}

    async def _fake_agent(db, **kw):
        captured.update(kw)
        yield "x"

    monkeypatch.setattr(assistant_ep, "run_agent", _fake_agent)
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={"messages": [{"role": "user", "content": "salut"}]},
        headers=_h(token),
    )
    assert resp.status_code == 200
    assert "quota_exceeded" not in resp.text          # clé client → quota ignoré
    assert captured.get("byok_key") == "sk-org-byok"  # clé de l'org transmise à l'agent


async def test_chat_platform_mode_enforces_quota(client: AsyncClient, admin_ctx, db_session, monkeypatch):
    org, token = admin_ctx
    org.ai_byok_mode = "platform"
    org.ai_quota_unit = "tokens"
    org.ai_quota_tokens = 1
    db_session.add(CmsAssistantStat(
        id_org=org.id_org, stat_date=date.today(), token_count=999, message_count=5
    ))
    await db_session.commit()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-platform")
    called = {"n": 0}

    async def _fake_agent(db, **kw):
        called["n"] += 1
        yield "x"

    monkeypatch.setattr(assistant_ep, "run_agent", _fake_agent)
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={"messages": [{"role": "user", "content": "salut"}]},
        headers=_h(token),
    )
    assert resp.status_code == 200
    assert '"quota_exceeded": true' in resp.text  # clé plateforme → quota appliqué
    assert called["n"] == 0
