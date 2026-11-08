"""Enrôlement 2FA — la seule porte étroite de l'authentification.

Le trou fermé ici (mesuré le 2026-08-04, `docs/RAPPORT_REPRISES_IA_GENERATION.md` ④) :

  · la 2FA est OBLIGATOIRE pour `CMS_SUPER_ADMIN` et `CMS_ORG_ADMIN` ;
  · la connexion d'un tel compte non enrôlé répondait **403 sans rien d'autre** ;
  · `/auth/totp/setup` exigeait `get_current_user`, c'est-à-dire un jeton d'accès qu'on ne
    peut justement pas obtenir tant qu'on n'est pas enrôlé.

**La boucle était fermée** : le compte était définitivement hors de l'application, sauf à
lire son secret depuis un shell sur le serveur. Le colmatage du 2026-07-19 (afficher le
secret TOTP à l'installation) ne couvrait que le tout premier compte ; le piège se rouvrait
à chaque `provision-admin` / `reset-admin`, et dès qu'un administrateur client perdait son
téléphone.

Le jeton d'enrôlement est délivré APRÈS vérification du mot de passe, donc il ne donne rien
que le mot de passe ne donnait déjà. Ce qui le rend sûr est sa PORTÉE : il n'ouvre que les
deux endpoints d'enrôlement. C'est cela que la moitié des tests ci-dessous verrouille — un
jeton d'enrôlement qui passerait ailleurs serait un contournement de la 2FA, pas un secours.
"""

import uuid
from datetime import datetime, timezone

import pyotp
import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser

PASSWORD = "Password1!"

# Ce qu'un jeton d'enrôlement ne doit JAMAIS ouvrir. Un seul de ces 200 et la 2FA
# obligatoire devient facultative pour qui connaît le mot de passe.
_FORBIDDEN_TO_ENROLMENT = [
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/media/"),
    ("GET", "/api/v1/players/"),
    ("GET", "/api/v1/dashboard/summary"),
    ("GET", "/api/v1/sites"),          # ⚠️ sans slash final : `/sites/` redirige en 307
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Enrol", org_slug=f"enrol-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    """Un org-admin SANS second facteur — exactement le compte qui restait dehors."""
    user = CmsUser(
        id_org=org.id_org, email=f"adm-{uuid.uuid4().hex[:8]}@test.com", full_name="Admin",
        password_hash=hash_password(PASSWORD), is_active=True, totp_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login(client: AsyncClient, user: CmsUser, **extra) -> "object":
    return await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD, **extra}
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Le refus tend la main au lieu de fermer la porte ──────────────────────────

@pytest.mark.asyncio
async def test_a_2fa_required_login_hands_over_an_enrolment_token(
    client: AsyncClient, admin: CmsUser
):
    resp = await _login(client, admin)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["force_2fa_setup"] is True
    token = detail["enrolment_token"]
    assert token
    payload = jwt.decode(token, settings.CMS_JWT_SECRET,
                         algorithms=[settings.CMS_JWT_ALGORITHM])
    assert payload["type"] == "totp_enrolment"
    assert payload["sub"] == str(admin.id_user)


@pytest.mark.asyncio
async def test_the_enrolment_token_is_short_lived(client: AsyncClient, admin: CmsUser):
    """Il ne remplace pas une session : il n'a que le temps de scanner un QR code."""
    token = (await _login(client, admin)).json()["detail"]["enrolment_token"]
    payload = jwt.decode(token, settings.CMS_JWT_SECRET,
                         algorithms=[settings.CMS_JWT_ALGORITHM])
    ttl_min = (payload["exp"] - datetime.now(timezone.utc).timestamp()) / 60
    assert 0 < ttl_min <= settings.CMS_JWT_ENROLMENT_TOKEN_EXPIRE_MINUTES + 1
    assert ttl_min > settings.CMS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES / 60  # pas une miette


@pytest.mark.asyncio
async def test_no_token_is_handed_over_before_the_password_is_verified(
    client: AsyncClient, admin: CmsUser
):
    """Le jeton ne donne rien de plus que le mot de passe — encore faut-il l'avoir donné."""
    resp = await client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert "enrolment_token" not in resp.text


# ── Ce que le jeton ouvre : l'enrôlement, et rien d'autre ─────────────────────

@pytest.mark.asyncio
async def test_the_enrolment_token_opens_the_two_enrolment_endpoints(
    client: AsyncClient, admin: CmsUser
):
    token = (await _login(client, admin)).json()["detail"]["enrolment_token"]

    setup = await client.post("/api/v1/auth/totp/setup", headers=_bearer(token))
    assert setup.status_code == 200
    body = setup.json()
    assert body["secret"] and body["qr_b64"] and len(body["backup_codes"]) == 10

    code = pyotp.TOTP(body["secret"]).now()
    verify = await client.post(
        "/api/v1/auth/totp/verify", json={"secret": body["secret"], "code": code},
        headers=_bearer(token),
    )
    assert verify.status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _FORBIDDEN_TO_ENROLMENT)
async def test_the_enrolment_token_opens_nothing_else(
    client: AsyncClient, admin: CmsUser, method: str, path: str
):
    """🔑 Le test qui rend le jeton sûr. S'il tombe, le second facteur est contournable
    par quiconque détient le mot de passe."""
    token = (await _login(client, admin)).json()["detail"]["enrolment_token"]
    resp = await client.request(method, path, headers=_bearer(token))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_a_refresh_token_is_not_an_enrolment_token(client: AsyncClient, admin: CmsUser):
    """La discrimination se fait sur le TYPE, jamais sur la seule signature."""
    resp = await client.post(
        "/api/v1/auth/totp/setup", headers=_bearer(create_refresh_token(admin.id_user))
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_an_ordinary_access_token_still_enrols(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
):
    """L'enrôlement VOLONTAIRE depuis le profil doit continuer de marcher : la nouvelle
    dépendance ÉLARGIT ce qui est accepté, elle ne remplace pas."""
    user = CmsUser(
        id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@test.com", full_name="Simple",
        password_hash=hash_password(PASSWORD), is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.post(
        "/api/v1/auth/totp/setup", headers=_bearer(create_access_token(user.id_user))
    )
    assert resp.status_code == 200


# ── Le cycle complet : dehors → enrôlé → dedans ───────────────────────────────

@pytest.mark.asyncio
async def test_the_account_that_was_locked_out_can_now_get_in(
    client: AsyncClient, admin: CmsUser
):
    """Le parcours de bout en bout, dans l'ordre où un humain le vit."""
    refused = await _login(client, admin)
    assert refused.status_code == 403
    token = refused.json()["detail"]["enrolment_token"]

    body = (await client.post("/api/v1/auth/totp/setup", headers=_bearer(token))).json()
    code = pyotp.TOTP(body["secret"]).now()
    assert (await client.post(
        "/api/v1/auth/totp/verify", json={"secret": body["secret"], "code": code},
        headers=_bearer(token),
    )).status_code == 204

    # 🔑 On repasse par /auth/login : ce chemin porte les compteurs anti-force brute,
    # l'horodatage de dernière connexion et l'entrée de journal. Il ne doit y avoir
    # qu'UNE seule façon d'entrer.
    ok = await _login(client, admin, totp_code=pyotp.TOTP(body["secret"]).now())
    assert ok.status_code == 200
    assert ok.json()["access_token"]
