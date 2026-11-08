"""Révocation des sessions ouvertes — P1.1 (migration 0122).

CE QUE ÇA FERME. Réinitialiser le mot de passe de quelqu'un ne fermait **aucune** de ses
sessions : un JWT reste valable jusqu'à son expiration, et rien ne permettait de dire « ce
jeton est antérieur à la coupure » — seuls les jetons *player* portaient une date
d'émission. Reprendre en main un compte compromis ne coupait donc rien du tout.

LE PIÈGE QUI FAIT TOUTE LA DIFFICULTÉ, et que la moitié de ce fichier verrouille : borner
les seuls jetons d'ACCÈS rendrait la révocation **décorative**. `/auth/refresh` ne vérifiait
que la liste noire Redis et le type du jeton ; l'accès refusé (401) déclenche un
rafraîchissement automatique côté front, qui aurait rendu un jeton neuf d'`iat` postérieur à
la borne — **et la session aurait survécu à sa propre révocation**, en donnant l'illusion
contraire. C'est le test `..._kills_the_refresh_token_too` : s'il tombe, la fonctionnalité
n'existe plus, elle fait seulement semblant.

Les deux règles de bord, chacune avec son test :

  · **borne tronquée à la seconde + comparaison stricte** : `iat` compte des secondes
    entières. Une borne au microseconde près rendrait « plus vieux qu'elle » un jeton émis
    dans la même seconde — l'utilisateur se reconnecte, reçoit un jeton déjà périmé, se
    fait refuser : boucle permanente. Fenêtre d'une seconde assumée contre boucle infinie ;
  · **un jeton sans `iat` est antérieur à toute borne** — il date d'avant le mécanisme.
    Mais tant qu'un compte n'a jamais été révoqué, il ne se passe **rien** : c'est l'état
    de tout le parc au déploiement, et un correctif de sécurité qui déconnecterait tout le
    monde en s'installant serait un incident.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_enrolment_token,
    create_refresh_token,
    hash_password,
)
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.session_revocation import revocation_bound, token_predates_revocation

PASSWORD = "Password1!"
NEW_PASSWORD = "Password2!"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _forge(user: CmsUser, *, kind: str = "access", iat: int | None = None) -> str:
    """Jeton signé maison — le seul moyen d'exercer les cas de bord (`iat` absent, `iat`
    à la seconde exacte de la borne) que les fabriques ne produisent pas."""
    payload = {
        "sub": str(user.id_user),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "type": kind,
        "org": user.id_org,
        "roles": [],
        "locale": "en",
    }
    if iat is not None:
        payload["iat"] = iat
    return jwt.encode(payload, settings.CMS_JWT_SECRET, algorithm=settings.CMS_JWT_ALGORITHM)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Revoke", org_slug=f"revoke-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _grant(db_session: AsyncSession, user: CmsUser, *keys: str) -> None:
    for key in keys:
        await db_session.execute(
            pg_insert(CmsRole).values(role_key=key, label=key, is_system=True)
            .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
        )
        await db_session.flush()
        role = (await db_session.execute(
            select(CmsRole).where(CmsRole.role_key == key))).scalar_one()
        db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()


@pytest_asyncio.fixture
async def victim(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    """Le compte dont on va reprendre la main : un org-admin, 2FA déjà enrôlée (sinon
    la connexion répondrait 403 et l'on mesurerait autre chose)."""
    import pyotp

    from app.services.totp import protect_totp_secret

    user = CmsUser(
        id_org=org.id_org, email=f"vic-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password(PASSWORD), is_active=True,
        totp_enabled=True, totp_secret=protect_totp_secret(pyotp.random_base32()),
    )
    db_session.add(user)
    await db_session.flush()
    await _grant(db_session, user, "CMS_ORG_ADMIN")
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def super_admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    user = CmsUser(id_org=org.id_org, email=f"sa-{uuid.uuid4().hex[:8]}@test.com",
                   password_hash=hash_password(PASSWORD), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await _grant(db_session, user, "CMS_SUPER_ADMIN")
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"], "locale": "en"}
    )


def _session_opened_a_minute_ago(user: CmsUser) -> tuple[str, str]:
    """Les deux jetons d'une session déjà ouverte quand la coupure arrive.

    ⚠️ Volontairement horodatés une minute plus tôt, et ce n'est pas de la décoration :
    la borne est tronquée à la seconde et la comparaison est stricte, donc un jeton frappé
    dans la MÊME seconde que la révocation survit — c'est le prix assumé contre la boucle
    de reconnexion. Un test qui minterait ses jetons juste avant d'appeler la remise à zéro
    mesurerait donc la vitesse de bcrypt : vert ou rouge selon que le hachage a franchi ou
    non une frontière de seconde. (Vécu en écrivant ce fichier : le test du rafraîchissement
    passait, celui de l'accès tombait, pour cette seule raison.)
    """
    issued = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    return _forge(user, iat=issued), _forge(user, kind="refresh", iat=issued)


async def _reset_admin(client: AsyncClient, token: str, org: CmsOrganization, user: CmsUser):
    return await client.post(
        f"/api/v1/orgs/{org.id_org}/reset-admin",
        headers=_bearer(token),
        json={"email": user.email, "password": NEW_PASSWORD, "full_name": "Repris"},
    )


# ── Le cœur : la reprise en main coupe RÉELLEMENT les sessions ─────────────────────

@pytest.mark.asyncio
async def test_a_password_reset_kills_the_open_access_token(
    client: AsyncClient, db_session: AsyncSession, org, victim, super_admin_token
):
    """Le scénario nominal, par le vrai endpoint : le jeton d'accès ouvert avant la
    réinitialisation ne vaut plus rien après."""
    stolen, _ = _session_opened_a_minute_ago(victim)
    assert (await client.get("/api/v1/users/me", headers=_bearer(stolen))).status_code == 200

    resp = await _reset_admin(client, super_admin_token, org, victim)
    assert resp.status_code == 200, resp.text

    assert (await client.get("/api/v1/users/me", headers=_bearer(stolen))).status_code == 401


@pytest.mark.asyncio
async def test_a_password_reset_kills_the_refresh_token_too(
    client: AsyncClient, db_session: AsyncSession, org, victim, super_admin_token
):
    """LE test du chantier. Sans lui, la révocation serait un décor : le 401 sur l'accès
    déclenche un rafraîchissement côté front, et cette route rendrait un jeton neuf,
    postérieur à la borne. La session survivrait à sa propre révocation."""
    _, stolen_refresh = _session_opened_a_minute_ago(victim)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh})
    assert first.status_code == 200, "le jeton de rafraîchissement doit marcher AVANT"

    assert (await _reset_admin(client, super_admin_token, org, victim)).status_code == 200

    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh})
    assert after.status_code == 401, (
        "le rafraîchissement ressuscite la session révoquée — la révocation est décorative"
    )


@pytest.mark.asyncio
async def test_the_account_is_usable_again_right_after_the_reset(
    client: AsyncClient, db_session: AsyncSession, org, victim, super_admin_token
):
    """Contrepartie obligatoire : on coupe les sessions, on ne condamne pas le compte.
    Un jeton émis APRÈS la borne passe — sinon la victime serait enfermée dehors, ce qui
    est exactement le défaut que P0.2 vient de fermer."""
    assert (await _reset_admin(client, super_admin_token, org, victim)).status_code == 200

    fresh = create_access_token(
        victim.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"}
    )
    assert (await client.get("/api/v1/users/me", headers=_bearer(fresh))).status_code == 200
    assert (await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": create_refresh_token(victim.id_user)}
    )).status_code == 200


# ── Les deux règles de bord ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_token_issued_in_the_same_second_as_the_bound_survives(
    client: AsyncClient, db_session: AsyncSession, victim
):
    """La troncature à la seconde, exercée. `iat` ne compte que des secondes : sans elle,
    le jeton reçu à la reconnexion paraîtrait plus vieux que la borne, serait refusé, et
    l'utilisateur boucherait indéfiniment entre connexion et 401."""
    bound = revocation_bound()
    victim.sessions_valid_from = bound
    await db_session.commit()

    same_second = _forge(victim, iat=int(bound.timestamp()))
    assert (await client.get("/api/v1/users/me", headers=_bearer(same_second))).status_code == 200

    one_second_before = _forge(victim, iat=int(bound.timestamp()) - 1)
    assert (
        await client.get("/api/v1/users/me", headers=_bearer(one_second_before))
    ).status_code == 401


@pytest.mark.asyncio
async def test_a_token_without_issued_at_is_refused_once_a_bound_exists(
    client: AsyncClient, db_session: AsyncSession, victim
):
    """Les jetons émis avant ce déploiement n'ont pas d'`iat`. Ils datent donc forcément
    d'avant n'importe quelle borne : les accepter laisserait une révocation sans effet sur
    exactement les sessions qu'on cherche à couper — celles déjà ouvertes."""
    legacy = _forge(victim, iat=None)
    assert (await client.get("/api/v1/users/me", headers=_bearer(legacy))).status_code == 200

    victim.sessions_valid_from = revocation_bound()
    await db_session.commit()

    assert (await client.get("/api/v1/users/me", headers=_bearer(legacy))).status_code == 401


@pytest.mark.asyncio
async def test_an_account_never_revoked_is_never_disconnected(
    client: AsyncClient, db_session: AsyncSession, org, victim
):
    """La sûreté du déploiement : au moment où la migration passe, TOUS les comptes sont à
    NULL. Un correctif de sécurité qui déconnecterait le parc en s'installant serait un
    incident, pas un correctif."""
    assert victim.sessions_valid_from is None
    for token in (
        create_access_token(victim.id_user, extra={"org": org.id_org, "roles": [], "locale": "en"}),
        _forge(victim, iat=None),
        _forge(victim, iat=int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())),
    ):
        assert (await client.get("/api/v1/users/me", headers=_bearer(token))).status_code == 200


# ── La réactivation ne ressuscite pas la vie d'avant ───────────────────────────────

@pytest.mark.asyncio
async def test_reactivating_a_revoked_account_does_not_resurrect_its_sessions(
    db_session: AsyncSession, org, victim
):
    """Trou trouvé en mesurant les chemins de mot de passe (05/08). Désactiver un compte
    faisait refuser ses jetons par le contrôle `is_active` — mais ne les TUAIT pas. Le jour
    où on le réactive (ré-invitation d'un annonceur révoqué), son ancien jeton de
    rafraîchissement rouvrait la session, sous une identité de rôles périmée, sans que
    personne ne se soit reconnecté.

    On mesure la RÈGLE plutôt que l'endpoint annonceur (qui demande tout un décor de
    campagnes) : ce que le code de réactivation fait est poser cette borne."""
    old_token_payload = {"iat": int((datetime.now(timezone.utc) - timedelta(days=20)).timestamp())}

    victim.is_active = False
    await db_session.commit()
    victim.is_active = True
    victim.sessions_valid_from = revocation_bound()   # ce que fait la ré-invitation
    await db_session.commit()

    assert token_predates_revocation(victim, old_token_payload) is True


@pytest.mark.asyncio
async def test_the_reactivation_path_really_sets_the_bound():
    """Garde anti-dérive sur le code, pas sur la règle : le chemin de ré-invitation d'un
    annonceur doit poser la borne quand il réactive. Sans cette lecture, le test ci-dessus
    resterait vert alors que l'endpoint aurait cessé de la poser."""
    import inspect

    from app.api.v1.endpoints import campaigns

    source = inspect.getsource(campaigns)
    assert "sessions_valid_from = revocation_bound()" in source, (
        "la ré-invitation d'un compte désactivé ne borne plus ses anciennes sessions"
    )


# ── L'enrôlement 2FA suit la même règle ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_enrolment_token_is_bounded_too(
    client: AsyncClient, db_session: AsyncSession, victim
):
    """Le jeton d'enrôlement de P0.2 est délivré après vérification du mot de passe. Un
    mot de passe révoqué ne doit donc pas laisser derrière lui un jeton d'enrôlement
    encore valable — sinon la reprise en main laisserait une porte entrouverte."""
    token = create_enrolment_token(victim.id_user)
    assert (await client.post("/api/v1/auth/totp/setup", headers=_bearer(token))).status_code == 200

    victim.sessions_valid_from = revocation_bound(datetime.now(timezone.utc) + timedelta(seconds=1))
    await db_session.commit()

    assert (await client.post("/api/v1/auth/totp/setup", headers=_bearer(token))).status_code == 401


# ── Toutes les fabriques de jetons utilisateurs portent bien un `iat` ──────────────

def test_every_user_token_factory_stamps_an_issued_at():
    """Une fabrique ajoutée plus tard sans `iat` créerait des jetons **immortels** vis-à-vis
    de la révocation : ils seraient refusés dès la première borne (règle « absence = plus
    vieux »), ce qui se verrait comme des déconnexions inexplicables. On vérifie donc les
    trois fabriques d'un coup, plutôt qu'au cas par cas."""
    for factory in (create_access_token, create_refresh_token, create_enrolment_token):
        payload = jwt.decode(
            factory(1), settings.CMS_JWT_SECRET, algorithms=[settings.CMS_JWT_ALGORITHM]
        )
        assert isinstance(payload.get("iat"), int), f"{factory.__name__} n'horodate pas son jeton"
