"""Audit menu ⑩ Rapports (2026-07-31) — héritage de la décision D1 (périmètre N8/G1).

Contexte : l'audit du Dashboard (28/07) a fermé `/analytics/noc` et `/analytics/geo`, qui
laissaient un admin de nœud lire l'inventaire COMPLET du parc parce qu'ils sont gatés
`reports:read` (porté par 5 rôles système) et non `players:read`. Il notait explicitement :
« même classe sur `/analytics/content` et `/executive` — agrégats de diffusion, question
différente ⇒ à trancher à l'audit du menu Rapports ». C'est ce fichier.

Décision d'Ed reprise ici : **hors périmètre = RIEN** (la même que D1).

⛔ EXCEPTION ASSUMÉE — les chemins d'INTÉGRITÉ (`/pop/verify`, `/pop/certificate`) ne sont
PAS filtrés : la chaîne de hachage est par écran, mais le `merkle_root` est AGRÉGÉ. Le
filtrer produirait une racine partielle — c'est-à-dire une **attestation différente de celle
de l'organisation**, indiscernable d'une chaîne altérée pour qui compare. Même règle que le
23/07 sur `screen_off` : on filtre les COMPTAGES, jamais l'intégrité.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.governance import (
    CmsGovernanceAssignment,
    CmsGovernanceNode,
    CmsGovernanceNodeAdmin,
)
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

_PERMS = [("reports", "read"), ("reports", "export")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RepAudit", org_slug=f"ra-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org: CmsOrganization) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"ra-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_RA_{uid}", label="RA", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in _PERMS:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org):
    """Un nœud administré par `node_admin` contient p_in ; p_out est hors périmètre.

    Chaque écran a diffusé un média DISTINCT : les agrégats de contenu sont donc
    discriminants — si le média de p_out apparaît, la fuite est prouvée par la donnée
    elle-même, pas par un compteur ambigu.
    """
    site_in = CmsSite(id_org=org.id_org, site_name="Site-IN")
    site_out = CmsSite(id_org=org.id_org, site_name="Site-OUT")
    db_session.add_all([site_in, site_out])
    await db_session.flush()
    p_in = CmsPlayer(id_org=org.id_org, id_site=site_in.id_site, player_name="P-IN")
    p_out = CmsPlayer(id_org=org.id_org, id_site=site_out.id_site, player_name="P-OUT")
    db_session.add_all([p_in, p_out])
    await db_session.flush()

    m_in = CmsMedia(id_org=org.id_org, media_name="MEDIA-IN", media_type="video",
                    storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256="a",
                    duration_ms=5000, transcode_status="ready")
    m_out = CmsMedia(id_org=org.id_org, media_name="MEDIA-OUT", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256="b",
                     duration_ms=5000, transcode_status="ready")
    db_session.add_all([m_in, m_out])
    await db_session.flush()

    now = datetime.now(UTC) - timedelta(hours=2)
    for player, media in ((p_in, m_in), (p_out, m_out)):
        db_session.add(CmsProofOfPlay(
            id_org=org.id_org, id_player=player.id_player, id_media=media.id_media,
            played_at=now, duration_ms=5000, merkle_hash=uuid.uuid4().hex,
        ))

    node = CmsGovernanceNode(id_org=org.id_org, node_name="N", node_level=0,
                             node_type="national", requires_approval=False, path="")
    db_session.add(node)
    await db_session.flush()
    node.path = str(node.id_node)
    db_session.add(CmsGovernanceAssignment(
        id_node=node.id_node, target_type="player", target_id=p_in.id_player))

    node_admin = await _mk_user(db_session, org)
    db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=node_admin.id_user))
    classic = await _mk_user(db_session, org)   # reports:read, AUCUN nœud administré
    await db_session.commit()
    return {
        "node_admin": node_admin, "classic": classic,
        "p_in": p_in, "p_out": p_out, "m_in": m_in, "m_out": m_out,
        "site_in": site_in, "site_out": site_out,
    }


# ── D1 sur les agrégats de diffusion ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_performance_respects_perimeter(client: AsyncClient, scene) -> None:
    """Le contenu diffusé HORS périmètre ne doit pas apparaître (ni son nom, ni ses
    passages) : c'est la campagne du voisin qu'on lirait dans le classement."""
    r = await client.get("/api/v1/analytics/content", headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    names = [row["media_name"] for row in r.json()["rows"]]
    assert "MEDIA-IN" in names
    assert "MEDIA-OUT" not in names, f"contenu hors périmètre exposé : {names}"


@pytest.mark.asyncio
async def test_executive_respects_perimeter(client: AsyncClient, scene) -> None:
    """Le tableau exécutif agrège tout le parc : sans périmètre, un responsable de nœud
    lit les indicateurs de l'enseigne entière."""
    r = await client.get("/api/v1/analytics/executive", headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    fleet = body.get("fleet") or {}
    assert fleet.get("total") == 1, f"parc annoncé : {fleet}"


@pytest.mark.asyncio
async def test_audience_respects_perimeter(client: AsyncClient, scene) -> None:
    r = await client.get("/api/v1/analytics/audience", headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    # L'audience est ventilée PAR SITE : le site hors périmètre ne doit pas y figurer
    # (sinon on lit la fréquentation estimée d'un magasin qu'on n'administre pas).
    sites = {row["site_name"] for row in r.json()["by_site"]}
    assert "Site-OUT" not in sites, f"site hors périmètre exposé : {sites}"


@pytest.mark.asyncio
async def test_pop_plays_respect_perimeter(client: AsyncClient, scene) -> None:
    """Le Proof of Play NOMME l'écran et le contenu : c'est la preuve de diffusion du
    réseau entier qu'un admin de nœud lisait."""
    today = datetime.now(UTC).date().isoformat()
    r = await client.get(f"/api/v1/pop/plays?from={today}&until={today}",
                         headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    players = {row["player_name"] for row in r.json()["rows"]}
    assert players <= {"P-IN"}, f"écrans hors périmètre exposés : {players}"


@pytest.mark.asyncio
async def test_pop_analytics_respect_perimeter(client: AsyncClient, scene) -> None:
    r = await client.get("/api/v1/pop/analytics", headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    assert r.json()["total_plays"] == 1, r.text


@pytest.mark.asyncio
async def test_explicit_player_filter_cannot_escape_perimeter(
    client: AsyncClient, scene
) -> None:
    """🔑 Le filtre `id_players` de l'écran exécutif est fourni PAR LE CLIENT : sans
    intersection avec le périmètre, il suffit de nommer l'écran du voisin pour lire ses
    chiffres — le filtre devient une porte."""
    r = await client.get(
        f"/api/v1/analytics/executive?id_players={scene['p_out'].id_player}",
        headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    fleet = r.json().get("fleet") or {}
    assert fleet.get("total") == 0, f"écran hors périmètre atteint par filtre : {fleet}"


@pytest.mark.asyncio
async def test_bi_pop_export_respects_perimeter(client: AsyncClient, scene) -> None:
    """L'export BI est un flux de preuves BRUTES (écran, site, contenu nommés) : sans
    périmètre, il devient la porte de sortie que les écrans viennent de fermer."""
    today = datetime.now(UTC).date().isoformat()
    r = await client.get(f"/api/v1/analytics/export/pop.csv?from={today}&until={today}",
                         headers=_h(scene["node_admin"]))
    assert r.status_code == 200, r.text
    assert "P-IN" in r.text
    assert "P-OUT" not in r.text, "écran hors périmètre exporté en CSV"


@pytest.mark.asyncio
async def test_network_metrics_export_is_org_admin_only(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Décision d'Ed (31/07) : ce rollup est agrégé au jour et à l'organisation, SANS
    dimension écran — il n'y a rien à intersecter. Plutôt que de laisser un admin de nœud
    lire les indicateurs de tout le réseau par la seule porte restée ouverte, on la ferme.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.role import CmsRole, CmsUserRoleAssignment

    today = datetime.now(UTC).date().isoformat()
    url = f"/api/v1/analytics/export/network-metrics.csv?from={today}&until={today}"

    # Admin de nœud (reports:read/export mais pas org-admin) → refusé.
    assert (await client.get(url, headers=_h(scene["node_admin"]))).status_code == 403
    # Rôle de reporting classique, sans nœud : refusé aussi — la donnée est d'organisation.
    assert (await client.get(url, headers=_h(scene["classic"]))).status_code == 403

    # Org-admin → autorisé.
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    oa_role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    admin = await _mk_user(db_session, org)
    db_session.add(CmsUserRoleAssignment(id_user=admin.id_user, id_role=oa_role.id_role))
    await db_session.commit()
    assert (await client.get(url, headers=_h(admin))).status_code == 200


# ── Ce qui ne doit PAS changer ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classic_report_viewer_is_unrestricted(client: AsyncClient, scene) -> None:
    """Un rôle de reporting SANS nœud administré garde la vue d'organisation : le
    périmètre est porté par l'ASSIGNATION, pas par la permission (règle G1/N8)."""
    r = await client.get("/api/v1/analytics/content", headers=_h(scene["classic"]))
    assert r.status_code == 200, r.text
    names = [row["media_name"] for row in r.json()["rows"]]
    assert {"MEDIA-IN", "MEDIA-OUT"} <= set(names), names


@pytest.mark.asyncio
async def test_integrity_paths_stay_org_wide(client: AsyncClient, scene) -> None:
    """⛔ `/pop/verify` atteste l'organisation. Sa racine de Merkle est AGRÉGÉE : la
    filtrer produirait une racine partielle, indiscernable d'une chaîne altérée pour qui
    compare deux attestations. On ne filtre jamais l'intégrité (règle du 23/07)."""
    admin_view = await client.get("/api/v1/pop/verify", headers=_h(scene["node_admin"]))
    classic_view = await client.get("/api/v1/pop/verify", headers=_h(scene["classic"]))
    assert admin_view.status_code == 200 and classic_view.status_code == 200
    assert admin_view.json()["merkle_root"] == classic_view.json()["merkle_root"]
    assert admin_view.json()["total"] == classic_view.json()["total"]
