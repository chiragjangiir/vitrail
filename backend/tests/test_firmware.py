"""Tests P1.1 — MAJ firmware BrightSign depuis l'UI (§XXX).

Couvre : upload + pin (un seul pinned par famille), garde-fous du push (version épinglée résolue
serveur, famille requise, déjà à jour), création deployment+target, gating super-admin.
"""
import uuid

import boto3
import pytest
import pytest_asyncio
from botocore.exceptions import ClientError
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.player_version import CmsUpdateDeployment, CmsUpdateDeploymentTarget
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="FwOrg", org_slug=f"fw-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _token(db: AsyncSession, org: CmsOrganization, role_key: str) -> str:
    user = CmsUser(id_org=org.id_org, email=f"{role_key.lower()}-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    await db.execute(
        pg_insert(CmsRole).values(role_key=role_key, label=role_key, is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    return create_access_token(user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"})


@pytest_asyncio.fixture
async def super_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    return await _token(db_session, org, "CMS_SUPER_ADMIN")


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    return await _token(db_session, org, "CMS_ORG_ADMIN")


@pytest.fixture
def minio_mock():
    with mock_aws():
        client = boto3.client(
            "s3", endpoint_url=f"http://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY, region_name="us-east-1",
        )
        try:
            client.create_bucket(Bucket=settings.MINIO_BUCKET_MEDIA)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
        yield client


async def _upload(client: AsyncClient, token: str, version: str, family: str) -> dict:
    resp = await client.post(
        "/api/v1/firmware/versions",
        files={"file": (f"{version}.bsfw", b"FWDATA" * 100, "application/octet-stream")},
        data={"version": version, "model_family": family},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _player(db: AsyncSession, org: CmsOrganization, family: str, bos: str) -> CmsPlayer:
    p = CmsPlayer(id_org=org.id_org, player_name=f"bs-{uuid.uuid4().hex[:6]}", player_os="brightsign",
                  capabilities={"bs_family": family, "bs_bos": bos, "bs_model": "XT1144"})
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_upload_pin_single_per_family(
    client: AsyncClient, super_token: str, minio_mock,
) -> None:
    """Upload 2 versions même famille + pin chacune → une SEULE reste épinglée (la dernière)."""
    fam = f"malibu-{uuid.uuid4().hex[:6]}"
    ver_a, ver_b = f"9.0.{uuid.uuid4().hex[:6]}", f"9.1.{uuid.uuid4().hex[:6]}"
    v1 = await _upload(client, super_token, ver_a, fam)
    v2 = await _upload(client, super_token, ver_b, fam)
    assert v1["is_pinned"] is False and v1["sha256_checksum"]

    r1 = await client.post(f"/api/v1/firmware/versions/{v1['id_version']}/pin",
                           headers={"Authorization": f"Bearer {super_token}"})
    assert r1.status_code == 200 and r1.json()["is_pinned"] is True
    r2 = await client.post(f"/api/v1/firmware/versions/{v2['id_version']}/pin",
                           headers={"Authorization": f"Bearer {super_token}"})
    assert r2.status_code == 200 and r2.json()["is_pinned"] is True

    lst = await client.get("/api/v1/firmware/versions",
                           headers={"Authorization": f"Bearer {super_token}"})
    pinned = [v for v in lst.json() if v["is_pinned"] and (v["model_family"] or "") == fam]
    assert len(pinned) == 1 and pinned[0]["version"] == ver_b


async def test_upload_same_version_different_families(
    client: AsyncClient, super_token: str, minio_mock,
) -> None:
    """Régression : malibu (XT4) et pagani (HD4) partagent la version OS 9.1.132 → les DEUX doivent
    s'enregistrer. L'unicité porte sur (track, version, model_family), pas (track, version)."""
    ver = "9.1.132"
    suffix = uuid.uuid4().hex[:6]
    v1 = await _upload(client, super_token, ver, f"malibu-{suffix}")
    v2 = await _upload(client, super_token, ver, f"pagani-{suffix}")
    assert v1["id_version"] != v2["id_version"]
    assert v1["version"] == v2["version"] == ver
    assert v1["model_family"] != v2["model_family"]


async def test_pinned_firmware_for_sd_bundle(
    client: AsyncClient, super_token: str, admin_token: str, minio_mock,
) -> None:
    """`GET /firmware/pinned` (org-admin) liste les firmwares épinglés + URL signée, pour le
    bundle SD d'un nouveau player. Absent tant que non épinglé."""
    hdr = {"Authorization": f"Bearer {admin_token}"}
    fam, ver = f"pagani-{uuid.uuid4().hex[:6]}", f"9.1.{uuid.uuid4().hex[:6]}"
    v = await _upload(client, super_token, ver, fam)

    r0 = await client.get("/api/v1/firmware/pinned", headers=hdr)
    assert r0.status_code == 200
    assert not any((x["model_family"] or "") == fam for x in r0.json())

    await client.post(f"/api/v1/firmware/versions/{v['id_version']}/pin",
                      headers={"Authorization": f"Bearer {super_token}"})
    r1 = await client.get("/api/v1/firmware/pinned", headers=hdr)
    match = [x for x in r1.json() if (x["model_family"] or "") == fam]
    assert len(match) == 1 and match[0]["version"] == ver and match[0]["download_url"]


async def test_versions_list_denied_to_org_admin_when_super_admin_exists(
    client: AsyncClient, admin_token: str, super_token: str,
) -> None:
    """Serveur d'intégrateur (un super-admin existe) : l'org-admin d'une marque n'est
    pas l’exploitant du serveur → gestes firmware fermés. `super_token` est demandé
    pour GARANTIR qu'un super-admin actif existe au moment de l'assertion."""
    resp = await client.get("/api/v1/firmware/versions",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 403


async def test_versions_list_open_to_lone_org_admin(
    client: AsyncClient, admin_token: str, db_session: AsyncSession,
) -> None:
    """Install autonome : sans super-admin actif, l'org-admin EST l'exploitant
    (critère `rbac.user_is_server_operator`).

    ⚠️ État SERVEUR partagé par toute la suite (d'autres fichiers créent des
    super-admins) : on les neutralise le temps de l'assertion, puis on restaure."""
    supers = (await db_session.execute(
        select(CmsUser)
        .join(CmsUserRoleAssignment, CmsUserRoleAssignment.id_user == CmsUser.id_user)
        .join(CmsRole, CmsRole.id_role == CmsUserRoleAssignment.id_role)
        .where(CmsRole.role_key == "CMS_SUPER_ADMIN", CmsUser.is_active.is_(True))
    )).scalars().all()
    for u in supers:
        u.is_active = False
    await db_session.commit()
    try:
        resp = await client.get("/api/v1/firmware/versions",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
    finally:
        for u in supers:
            u.is_active = True
        await db_session.commit()


async def test_push_blocked_without_pinned(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
    admin_token: str, minio_mock,
) -> None:
    """Aucune version épinglée pour la famille → push refusé (400)."""
    player = await _player(db_session, org, f"malibu-{uuid.uuid4().hex[:6]}", "9.0.0")
    resp = await client.post(f"/api/v1/firmware/players/{player.id_player}/update",
                             headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 400


async def test_push_creates_deployment_and_target(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
    super_token: str, admin_token: str, minio_mock,
) -> None:
    """Version épinglée + famille match + bos différent → push 202, deployment+target créés, état MAJ dispo."""
    fam, ver = f"malibu-{uuid.uuid4().hex[:6]}", f"9.1.{uuid.uuid4().hex[:6]}"
    v = await _upload(client, super_token, ver, fam)
    await client.post(f"/api/v1/firmware/versions/{v['id_version']}/pin",
                      headers={"Authorization": f"Bearer {super_token}"})
    player = await _player(db_session, org, fam, "9.0.0")

    # État : MAJ disponible
    st = await client.get(f"/api/v1/firmware/players/{player.id_player}/state",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert st.status_code == 200
    assert st.json()["update_available"] is True and st.json()["pinned_version"] == ver

    # Push
    resp = await client.post(f"/api/v1/firmware/players/{player.id_player}/update",
                             headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 202, resp.text
    assert resp.json()["version"] == ver and resp.json()["previous_version"] == "9.0.0"

    dep = (await db_session.execute(
        select(CmsUpdateDeployment).where(CmsUpdateDeployment.id_org == org.id_org)
    )).scalars().all()
    assert len(dep) == 1 and dep[0].id_version == v["id_version"]
    tgt = (await db_session.execute(
        select(CmsUpdateDeploymentTarget).where(CmsUpdateDeploymentTarget.id_player == player.id_player)
    )).scalars().all()
    assert len(tgt) == 1 and tgt[0].status == "queued" and tgt[0].previous_version == "9.0.0"


async def test_firmware_target_settles_when_device_reports_version(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
    super_token: str, admin_token: str, minio_mock,
) -> None:
    """La cible de MAJ passe à 'success' quand le device remonte la version poussée (réconciliation à
    la lecture de l'état) — l'autorun reboote sans renvoyer de callback de complétion → comble le
    « queued » éternel."""
    fam, ver = f"malibu-{uuid.uuid4().hex[:6]}", f"9.1.{uuid.uuid4().hex[:6]}"
    v = await _upload(client, super_token, ver, fam)
    await client.post(f"/api/v1/firmware/versions/{v['id_version']}/pin",
                      headers={"Authorization": f"Bearer {super_token}"})
    player = await _player(db_session, org, fam, "9.0.0")
    r = await client.post(f"/api/v1/firmware/players/{player.id_player}/update",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 202

    # Le device reboote sur la nouvelle version (heartbeat capabilities.bs_bos).
    player.capabilities = {**(player.capabilities or {}), "bs_bos": ver}
    await db_session.commit()

    st = await client.get(f"/api/v1/firmware/players/{player.id_player}/state",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert st.status_code == 200
    assert st.json()["last_status"] == "success"
    assert st.json()["update_available"] is False
    tgt = (await db_session.execute(
        select(CmsUpdateDeploymentTarget).where(CmsUpdateDeploymentTarget.id_player == player.id_player)
    )).scalars().all()
    assert len(tgt) == 1 and tgt[0].status == "success"


async def test_push_blocked_when_already_up_to_date(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
    super_token: str, admin_token: str, minio_mock,
) -> None:
    fam, ver = f"malibu-{uuid.uuid4().hex[:6]}", f"9.1.{uuid.uuid4().hex[:6]}"
    v = await _upload(client, super_token, ver, fam)
    await client.post(f"/api/v1/firmware/versions/{v['id_version']}/pin",
                      headers={"Authorization": f"Bearer {super_token}"})
    player = await _player(db_session, org, fam, ver)  # déjà à jour
    resp = await client.post(f"/api/v1/firmware/players/{player.id_player}/update",
                             headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 409


# ── /meta/operator : même critère, exposé pour l'affichage de la page firmware ──

async def test_meta_operator_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/meta/operator")
    assert resp.status_code == 401


async def test_meta_operator_super_admin(client: AsyncClient, super_token: str) -> None:
    resp = await client.get("/api/v1/meta/operator",
                            headers={"Authorization": f"Bearer {super_token}"})
    assert resp.status_code == 200
    assert resp.json() == {"is_operator": True}


async def test_meta_operator_org_admin_with_super_admin(
    client: AsyncClient, admin_token: str, super_token: str,
) -> None:
    # `super_token` garantit qu'un super-admin actif existe au moment de l'assertion.
    resp = await client.get("/api/v1/meta/operator",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json() == {"is_operator": False}


async def test_meta_operator_lone_org_admin(
    client: AsyncClient, admin_token: str, db_session: AsyncSession,
) -> None:
    """Install autonome : sans super-admin actif, l'org-admin EST l'exploitant. État
    SERVEUR partagé par la suite : les super-admins sont neutralisés puis restaurés."""
    supers = (await db_session.execute(
        select(CmsUser)
        .join(CmsUserRoleAssignment, CmsUserRoleAssignment.id_user == CmsUser.id_user)
        .join(CmsRole, CmsRole.id_role == CmsUserRoleAssignment.id_role)
        .where(CmsRole.role_key == "CMS_SUPER_ADMIN", CmsUser.is_active.is_(True))
    )).scalars().all()
    for u in supers:
        u.is_active = False
    await db_session.commit()
    try:
        resp = await client.get("/api/v1/meta/operator",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert resp.json() == {"is_operator": True}
    finally:
        for u in supers:
            u.is_active = True
        await db_session.commit()
