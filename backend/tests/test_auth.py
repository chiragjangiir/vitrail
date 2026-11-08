"""
Tests Sprint 1.1 — Authentification (§II.1, §2.1.1).

Couvre :
  - test_login_valid_credentials
  - test_login_invalid_password
  - test_login_embeds_locale_in_jwt
  - test_totp_setup_and_verify
  - test_2fa_policy_required_blocks_user_without_totp
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"auth-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="TestOrg", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    email = f"alice.{uuid.uuid4().hex[:8]}@example.com"
    u = CmsUser(
        id_org=org.id_org,
        email=email,
        password_hash=hash_password("password123"),
        full_name="Alice Test",
        locale="fr",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_login_valid_credentials(client: AsyncClient, user: CmsUser) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, user: CmsUser) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_embeds_locale_in_jwt(client: AsyncClient, user: CmsUser) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["locale"] == "fr"

    payload = jwt.decode(
        data["access_token"],
        settings.CMS_JWT_SECRET,
        algorithms=[settings.CMS_JWT_ALGORITHM],
    )
    assert payload["locale"] == "fr"
    assert payload["type"] == "access"
    assert "org" in payload


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient, org: CmsOrganization) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, user: CmsUser) -> None:
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_totp_setup_and_verify(
    client: AsyncClient, user: CmsUser, db_session: AsyncSession
) -> None:
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    setup_resp = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert setup_resp.status_code == 200
    setup_data = setup_resp.json()
    assert "secret" in setup_data
    assert "qr_b64" in setup_data
    assert len(setup_data["backup_codes"]) == 10

    import pyotp
    code = pyotp.TOTP(setup_data["secret"]).now()
    verify_resp = await client.post(
        "/api/v1/auth/totp/verify",
        json={"secret": setup_data["secret"], "code": code},
        headers=headers,
    )
    assert verify_resp.status_code == 204

    from sqlalchemy import select
    result = await db_session.execute(
        select(CmsUser).where(CmsUser.id_user == user.id_user)
    )
    updated = result.scalar_one()
    assert updated.totp_enabled is True


@pytest.mark.asyncio
async def test_2fa_policy_required_blocks_user_without_totp(
    client: AsyncClient,
    db_session: AsyncSession,
    org: CmsOrganization,
) -> None:
    email = f"bob.{uuid.uuid4().hex[:8]}@example.com"
    u = CmsUser(
        id_org=org.id_org,
        email=email,
        password_hash=hash_password("pass123"),
    )
    db_session.add(u)

    await db_session.execute(
        update(CmsOrgAuthSettings)
        .where(CmsOrgAuthSettings.id_org == org.id_org)
        .values(auth_2fa_policy="required")
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass123"},
    )
    assert resp.status_code == 403
    assert resp.headers.get("x-force-2fa-setup") == "true"


@pytest.mark.asyncio
async def test_login_rate_limited_after_repeated_failures(
    client: AsyncClient, user: CmsUser
) -> None:
    """Régression sécurité (audit 2026-06-24) : après N échecs, le login renvoie 429
    (anti-brute-force). Seuls les ÉCHECS comptent — un login réussi ne bloque pas."""
    import redis.asyncio as aioredis

    from app.api.v1.endpoints.auth import _LOGIN_MAX_ATTEMPTS

    async def _flush_fail_keys() -> None:
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            async for k in r.scan_iter("signflow:login:fail:*"):
                await r.delete(k)

    await _flush_fail_keys()
    try:
        codes = []
        for _ in range(_LOGIN_MAX_ATTEMPTS + 1):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": "wrong"},
            )
            codes.append(resp.status_code)
        assert codes[:_LOGIN_MAX_ATTEMPTS] == [401] * _LOGIN_MAX_ATTEMPTS
        assert codes[_LOGIN_MAX_ATTEMPTS] == 429
    finally:
        await _flush_fail_keys()


# ── Durcissement TOTP (audit 2026-06-24) ─────────────────────────────────────────

async def test_totp_secret_encrypted_at_rest() -> None:
    """Le secret TOTP est chiffré au repos (coffre dispo) et déchiffrable ; un secret
    legacy en clair reste toléré (repli)."""
    import pyotp

    from app.services.totp import (
        protect_totp_secret,
        reveal_totp_secret,
        secret_is_encrypted,
    )

    s = pyotp.random_base32()
    stored = protect_totp_secret(s)
    assert stored != s
    assert secret_is_encrypted(stored)
    assert reveal_totp_secret(stored) == s
    # Legacy en clair : toléré, non considéré comme chiffré.
    assert reveal_totp_secret(s) == s
    assert secret_is_encrypted(s) is False


@pytest.mark.asyncio
async def test_login_totp_code_single_use(
    client: AsyncClient, org: CmsOrganization, db_session: AsyncSession
) -> None:
    """Anti-rejeu : un code TOTP valide n'est accepté qu'UNE fois au login (rejeu → 401)."""
    import pyotp
    import redis.asyncio as aioredis

    from app.services.totp import protect_totp_secret

    secret = pyotp.random_base32()
    u = CmsUser(
        id_org=org.id_org,
        email=f"mfa.{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        totp_secret=protect_totp_secret(secret),
        totp_enabled=True,
    )
    db_session.add(u)
    await db_session.commit()

    async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
        async for k in r.scan_iter("signflow:login:fail:*"):
            await r.delete(k)
        async for k in r.scan_iter("signflow:totp:used:*"):
            await r.delete(k)

    code = pyotp.TOTP(secret).now()
    body = {"email": u.email, "password": "password123", "totp_code": code}
    r1 = await client.post("/api/v1/auth/login", json=body)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/auth/login", json=body)
    assert r2.status_code == 401  # même code rejoué → refusé


def test_hashing_a_password_prints_no_traceback(caplog):
    """P2.5 — passlib journalise une trace Python complete en sondant la version de bcrypt
    (attribut disparu en bcrypt 4.1). Il l'attrape et poursuit : rien ne casse. Mais cette
    trace sort a l'etape « compte administrateur » de l'installation client, la ou elle se
    lit comme un echec sur une installation parfaitement reussie.

    On mesure le RESULTAT (aucun enregistrement bruyant pendant un hachage), pas le reglage
    de niveau — verifier qu'on a bien appele `setLevel` ne prouverait que d'avoir ecrit la
    ligne, pas qu'elle produit le silence attendu.
    """
    import logging

    from app.core.security import hash_password, verify_password

    with caplog.at_level(logging.WARNING, logger="passlib.handlers.bcrypt"):
        digest = hash_password("Password1!")

    assert verify_password("Password1!", digest), "le hachage doit rester fonctionnel"
    noisy = [r for r in caplog.records if r.name.startswith("passlib")]
    assert not noisy, f"passlib parle encore pendant le hachage : {[r.message for r in noisy]}"
