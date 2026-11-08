"""Commandes players EN MASSE + garde PIN (migr 0097).

Deux choses à prouver, et elles sont indépendantes :
  1. la CIBLE est réellement résolue par le targeting canonique (org/site/group/player) —
     et pas par un résolveur maison qui raterait `site`/`site_group` (audit 2026-07-18) ;
  2. le PIN garde les commandes DESTRUCTIVES et elles seules, avec compteur + verrou.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser

PIN = "246813"


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="BulkOrg", org_slug=f"bulk-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    user = CmsUser(id_org=org.id_org, email=f"a-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True,
                   assistant_pin_hash=hash_password(PIN))
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def token(admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        admin.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"})


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _site(db, org, name="S"):
    s = CmsSite(id_org=org.id_org, site_name=name)
    db.add(s)
    await db.flush()
    return s


async def _player(db, org, name, id_site=None):
    p = CmsPlayer(id_org=org.id_org, player_name=name, player_os="linux", id_site=id_site)
    db.add(p)
    await db.flush()
    return p


# ── Résolution de la cible ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_targets_whole_site(client: AsyncClient, db_session, org, token) -> None:
    """Une cible `site` touche tous les players du site — et EUX SEULS."""
    site = await _site(db_session, org, "A")
    other = await _site(db_session, org, "B")
    p1 = await _player(db_session, org, "a", site.id_site)
    p2 = await _player(db_session, org, "b", site.id_site)
    await _player(db_session, org, "ailleurs", other.id_site)
    await db_session.commit()

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "screenshot",
            "targets": [{"target_type": "site", "target_id": site.id_site}]})
    assert r.status_code == 202, r.text
    assert set(r.json()["dispatched"]) == {p1.id_player, p2.id_player}
    assert r.json()["count"] == 2


@pytest.mark.asyncio
async def test_bulk_multi_targets_union_dedup(client, db_session, org, token) -> None:
    """Cibles multiples = UNION dédoublonnée (un player visé 2× n'est commandé qu'une fois)."""
    site = await _site(db_session, org, "A")
    p1 = await _player(db_session, org, "a", site.id_site)
    await db_session.commit()

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "screenshot", "targets": [
                {"target_type": "site", "target_id": site.id_site},
                {"target_type": "player", "target_id": p1.id_player}]})
    assert r.status_code == 202, r.text
    assert r.json()["dispatched"] == [p1.id_player]


@pytest.mark.asyncio
async def test_bulk_empty_target_is_400(client, db_session, org, token) -> None:
    """Cible qui ne résout aucun player → 400 explicite, jamais un 202 trompeur."""
    site = await _site(db_session, org, "vide")
    await db_session.commit()
    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "screenshot",
        "targets": [{"target_type": "site", "target_id": site.id_site}]})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_requires_targets_and_known_command(client, org, token) -> None:
    """Cibles vides ou commande inconnue → 422 (jamais avalé silencieusement)."""
    r = await client.post("/api/v1/players/commands", headers=_h(token),
                          json={"command": "screenshot", "targets": []})
    assert r.status_code == 422
    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "self_destruct", "targets": [{"target_type": "org"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_is_org_scoped(client, db_session, org, token) -> None:
    """Une cible `org` ne sort jamais de l'organisation de l'appelant."""
    other_org = CmsOrganization(org_name="Autre", org_slug=f"o-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    await db_session.flush()
    intruder = await _player(db_session, other_org, "etranger")
    mine = await _player(db_session, org, "mien")
    await db_session.commit()

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "screenshot", "targets": [{"target_type": "org"}]})
    assert r.status_code == 202, r.text
    assert intruder.id_player not in r.json()["dispatched"]
    assert mine.id_player in r.json()["dispatched"]


# ── Garde PIN ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_destructive_requires_pin(client, db_session, org, token) -> None:
    """reboot_os sans PIN → 403 ; avec le bon PIN → 202."""
    await _player(db_session, org, "a")
    await db_session.commit()

    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "reboot_os", "targets": [{"target_type": "org"}]})
    assert r.status_code == 403

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": PIN})
    assert r.status_code == 202, r.text


@pytest.mark.asyncio
async def test_harmless_command_needs_no_pin(client, db_session, org, token) -> None:
    """Une capture d'écran de parc ne doit PAS réclamer le PIN (sinon il finit sur un post-it)."""
    await _player(db_session, org, "a")
    await db_session.commit()
    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "screenshot", "targets": [{"target_type": "org"}]})
    assert r.status_code == 202, r.text


@pytest.mark.asyncio
async def test_no_pin_defined_is_412(client, db_session, org, admin, token) -> None:
    """Sans PIN au profil : 412 (message « définissez-le »), pas un 403 « PIN incorrect »."""
    admin.assistant_pin_hash = None
    await db_session.commit()
    await _player(db_session, org, "a")
    await db_session.commit()

    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": PIN})
    assert r.status_code == 412


@pytest.mark.asyncio
async def test_pin_lockout_after_three_attempts(client, db_session, org, admin, token) -> None:
    """3 essais faux → verrou 15 min : même le BON PIN est ensuite refusé (423)."""
    await _player(db_session, org, "a")
    await db_session.commit()

    for _ in range(2):
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": "000000"})
        assert r.status_code == 403
    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": "000000"})
    assert r.status_code == 423

    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": PIN})
    assert r.status_code == 423

    await db_session.refresh(admin)
    assert admin.assistant_pin_locked_until is not None


@pytest.mark.asyncio
async def test_pin_success_resets_attempts(client, db_session, org, admin, token) -> None:
    """Un succès remet le compteur à zéro (sinon 2 fautes d'un lundi verrouillent le mardi)."""
    await _player(db_session, org, "a")
    await db_session.commit()

    r = await client.post("/api/v1/players/commands", headers=_h(token), json={
        "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": "000000"})
    assert r.status_code == 403
    await db_session.refresh(admin)
    assert admin.assistant_pin_attempts == 1

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "reboot_os", "targets": [{"target_type": "org"}], "pin": PIN})
    assert r.status_code == 202
    await db_session.refresh(admin)
    assert admin.assistant_pin_attempts == 0


# ── Traçabilité ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_writes_audit_log(client, db_session, org, admin, token) -> None:
    """Une action de masse doit rester explicable après coup : audit + liste des players."""
    site = await _site(db_session, org, "A")
    p1 = await _player(db_session, org, "a", site.id_site)
    await db_session.commit()

    with patch("app.api.v1.endpoints.players.aioredis.from_url") as m:
        m.return_value = AsyncMock()
        r = await client.post("/api/v1/players/commands", headers=_h(token), json={
            "command": "reboot_os",
            "targets": [{"target_type": "site", "target_id": site.id_site}], "pin": PIN})
    assert r.status_code == 202, r.text

    row = (await db_session.execute(select(CmsAuditLog).where(
        CmsAuditLog.action == "player_bulk_command",
        CmsAuditLog.id_org == org.id_org))).scalars().first()
    assert row is not None
    assert row.id_user == admin.id_user
    assert row.detail["command"] == "reboot_os"
    assert row.detail["players"] == [p1.id_player]
    assert row.detail["count"] == 1
    # La CIBLE demandée est conservée, pas seulement les players résolus : on doit pouvoir
    # relire « il a visé le site A », même si le parc a changé depuis.
    assert row.detail["targets"][0]["target_type"] == "site"


@pytest.mark.asyncio
async def test_bulk_requires_org_admin(client, db_session, org) -> None:
    """Un non-admin ne commande pas un parc."""
    user = CmsUser(id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.commit()
    tok = create_access_token(user.id_user,
                             extra={"org": org.id_org, "roles": ["CMS_VIEWER"], "locale": "en"})
    r = await client.post("/api/v1/players/commands", headers=_h(tok), json={
        "command": "screenshot", "targets": [{"target_type": "org"}]})
    assert r.status_code == 403
