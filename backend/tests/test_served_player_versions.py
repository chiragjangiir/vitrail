"""Renderers SERVIS par le serveur (BrightSign/ChromeOS) — manifeste, déclaration, ÉPINGLAGE (§XXX #4).

Ces plateformes n'ont pas de bundle : leur code est servi par l'image frontend. Pour éviter qu'une MAJ
serveur ne mette à jour le parc au prochain reboot (reprise auto involontaire), le player charge une
version ÉPINGLÉE (pilotée par les déploiements de son org), pas « la dernière servie ».
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.served_versions import served_player_versions

# signflow.js porte les constantes CANONIQUES des versions renderer (source de vérité côté player).
# Le conteneur backend ne monte que backend/ → hors du repo complet le fichier est absent : la garde
# anti-dérive se skippe alors proprement (elle est ACTIVE en CI et en repo complet, là où ça compte).
_SIGNFLOW_JS = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "public" / "player-chromeos" / "signflow.js"
)


def _js_const(js: str, name: str) -> str | None:
    m = re.search(rf"const\s+{name}\s*=\s*'([^']+)'", js)
    return m.group(1) if m else None


def test_manifest_matches_code_constants() -> None:
    """Le manifeste backend NE DOIT PAS dériver des constantes de signflow.js — sinon on déclarerait/
    épinglerait une version que le serveur ne sert pas. (Culture `gen_role_matrix` / `test_demo_guard`.)"""
    manifest = served_player_versions()
    assert manifest, "manifeste des versions servies vide"
    if not _SIGNFLOW_JS.exists():
        pytest.skip("signflow.js absent (conteneur backend seul) — garde active en CI / repo complet")
    js = _SIGNFLOW_JS.read_text(encoding="utf-8")
    assert manifest.get("chromeos") == _js_const(js, "CHROMEOS_PLAYER_VERSION")
    assert manifest.get("brightsign") == _js_const(js, "BS_PLAYER_VERSION")


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RndOrg", org_slug=f"rnd-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    user = CmsUser(id_org=org.id_org, email=f"adm-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole).values(role_key="CMS_SUPER_ADMIN", label="Super", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"], "locale": "fr"})


@pytest_asyncio.fixture(autouse=True)
async def _clean_ota_globals(db_session: AsyncSession):
    """`cms_player_update_versions` est GLOBALE (pas d'id_org) et `create_deployment` COMMIT → fuite
    entre tests. Purge des 3 tables globales après chaque test (cf. test_updates.py)."""
    yield
    for tbl in ("cms_update_deployment_targets", "cms_update_deployments",
                "cms_player_update_versions"):
        await db_session.execute(text(f"DELETE FROM {tbl}"))
    await db_session.commit()


async def test_served_versions_register_and_list(
    client: AsyncClient, admin_token: str
) -> None:
    """GET expose les versions servies (chromeos/brightsign) ; POST register les déclare au catalogue
    (download_url NULL), idempotent ; plateforme inconnue → 400."""
    h = {"Authorization": f"Bearer {admin_token}"}

    sv = {r["platform"]: r for r in (
        await client.get("/api/v1/updates/served-versions", headers=h)).json()}
    assert sv["chromeos"]["served_version"] == served_player_versions()["chromeos"]
    assert sv["chromeos"]["registered"] is False
    assert sv["brightsign"]["served_version"] == served_player_versions()["brightsign"]

    reg = await client.post("/api/v1/updates/served-versions/register", headers=h,
                            json={"platform": "chromeos"})
    assert reg.status_code == 200
    body = reg.json()
    assert body["version"] == served_player_versions()["chromeos"]
    assert body["model_family"] == "chromeos"
    assert body["download_url"] is None
    id1 = body["id_version"]

    # Idempotent : re-déclarer renvoie la MÊME ligne (pas de doublon).
    reg2 = await client.post("/api/v1/updates/served-versions/register", headers=h,
                             json={"platform": "chromeos"})
    assert reg2.status_code == 200 and reg2.json()["id_version"] == id1

    sv2 = {r["platform"]: r for r in (
        await client.get("/api/v1/updates/served-versions", headers=h)).json()}
    assert sv2["chromeos"]["registered"] is True
    assert sv2["chromeos"]["latest_registered"] == served_player_versions()["chromeos"]

    bad = await client.post("/api/v1/updates/served-versions/register", headers=h,
                            json={"platform": "nope"})
    assert bad.status_code == 400


async def test_renderer_version_endpoint_player_auth(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """GET /updates/renderer-version est authentifié PLAYER → un token player DOIT passer (200).
    Régression prod 2026-07-22 : l'endpoint prenait sa session via `get_db` (qui dépend de
    `get_current_user`, auth UTILISATEUR type=access) au lieu de `get_db_worker` → un token player
    (type=player) recevait 401 « Token invalide ou expiré » → le pin ne se résolvait JAMAIS côté
    ChromeOS (loader) et BrightSign (autorun) → repli plat → épinglage HS."""
    from app.core.security import create_player_token
    from app.models.player import CmsPlayer

    p = CmsPlayer(id_org=org.id_org, player_name="Chromebox", player_os="chromeos",
                  player_version="2.0.7", status="online")
    db_session.add(p)
    await db_session.flush()
    token, _exp = create_player_token(p.id_player)
    p.player_token = token   # la garde de révocation exige presented == player.player_token
    await db_session.commit()

    r = await client.get("/api/v1/updates/renderer-version",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "chromeos"
    assert body["version"] == "2.0.7"   # défaut = version courante connue (pas de déploiement)

    # Sans token → 401 (l'endpoint reste protégé).
    assert (await client.get("/api/v1/updates/renderer-version")).status_code in (401, 403)


async def test_resolve_renderer_version_pinning(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Le pin d'un player servi = version du dernier déploiement le ciblant ; une MAJ serveur (nouvelle
    version SERVIE) ne l'avance JAMAIS seule. Défaut = version courante connue → sinon version servie."""
    from app.models.player_version import CmsPlayerUpdateVersion
    from app.services import ota
    from app.services.targeting import Target

    u = CmsUser(id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@t.com",
                password_hash=hash_password("Password1!"), is_active=True)
    served = served_player_versions()["chromeos"]           # ex. "2.0.7" (version SERVIE)
    # Player déjà en service sur une version ANTÉRIEURE à la version servie.
    cr = CmsPlayer(id_org=org.id_org, player_name="Chromebox", player_os="chromeos",
                   player_version="2.0.6", status="online")
    db_session.add_all([u, cr])
    await db_session.flush()

    # Sans déploiement : le pin PRÉSERVE sa version courante (2.0.6), PAS la version servie (2.0.7).
    # → une MAJ serveur qui sert 2.0.7 ne met PAS ce player à jour tout seul.
    assert await ota.resolve_renderer_version(db_session, cr) == "2.0.6"

    # L'admin déclare la version servie + la déploie SUR CE player → le pin avance.
    ver = CmsPlayerUpdateVersion(track="player", version=served, model_family="chromeos")
    db_session.add(ver)
    await db_session.flush()
    await ota.create_deployment(
        db_session, org.id_org, ver.id_version,
        [Target(target_type="player", target_id=cr.id_player)], "immediate", {}, u.id_user)
    assert await ota.resolve_renderer_version(db_session, cr) == served

    # Un player NEUF (aucune version connue, aucun déploiement) → défaut = version servie (bootstrap).
    fresh = CmsPlayer(id_org=org.id_org, player_name="FreshCros", player_os="chromeos",
                      player_version=None, status="online")
    db_session.add(fresh)
    await db_session.flush()
    assert await ota.resolve_renderer_version(db_session, fresh) == served
