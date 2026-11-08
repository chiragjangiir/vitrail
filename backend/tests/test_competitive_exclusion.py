"""Tests exclusion concurrentielle #10 (option B, migr 0087).

Catégories d'industrie par org + catégorie sur l'annonceur + catégories exclues
par SITE → les players du site sortent de l'inventaire de tout annonceur de la
catégorie (même tuyau que l'opt-out : ciblage, occupation/devis, portail,
diffusion). Couvre :
- CRUD catégories (RBAC, doublon 409, delete = SET NULL annonceurs + CASCADE
  exclusions, cross-org 404) ;
- PUT /sites/{id} campaign_excluded_categories (remplace, cross-tenant 404) ;
- résolution : target_player_count / occupancy-check id_advertiser ;
- portail : sites marqués excluded + screen_count 0 ;
- diffusion : campaign_ad_slots n'injecte jamais un annonceur exclu du site.
"""

import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.campaign import (
    CmsAdvertiser,
    CmsAdvertiserIndustryCategory,
    CmsCampaign,
    CmsCampaignCreative,
    CmsCampaignTarget,
    CmsIndustryCategory,
    CmsSiteExcludedCategory,
)
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.campaign_delivery import campaign_ad_slots


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="CX", org_slug=f"cx-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


async def _grant(db: AsyncSession, role: CmsRole, module: str, op: str) -> None:
    await db.execute(
        pg_insert(CmsPermission)
        .values(module=module, operation=op, label=f"{module}.{op}")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
    await db.flush()
    perm = (await db.execute(select(CmsPermission).where(
        CmsPermission.module == module, CmsPermission.operation == op))).scalar_one()
    await db.execute(
        pg_insert(CmsRolePermission)
        .values(id_role=role.id_role, id_permission=perm.id_permission)
        .on_conflict_do_nothing())


async def _user(db: AsyncSession, org: CmsOrganization, role_key: str,
                perms: list[tuple[str, str]], *, is_system: bool = True,
                id_advertiser: int | None = None) -> CmsUser:
    user = CmsUser(id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True,
                   full_name=f"User {role_key[:12]}", id_advertiser=id_advertiser)
    db.add(user)
    await db.flush()
    role = (await db.execute(select(CmsRole).where(
        CmsRole.role_key == role_key))).scalars().first()
    if role is None:
        role = CmsRole(id_org=None if is_system else org.id_org, role_key=role_key,
                       label=role_key, is_system=is_system)
        db.add(role)
        await db.flush()
    for module, op in perms:
        await _grant(db, role, module, op)
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    return user


def _headers(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    return await _user(
        db_session, org, "CMS_ORG_ADMIN",
        [("campaigns", op) for op in ("read", "create", "edit", "publish", "delete")]
        + [("players", "read"), ("players", "edit")])


async def _inventory(db: AsyncSession, org: CmsOrganization) -> dict:
    """2 sites × 1 player, catégorie « Automobile », annonceur Peugeot (Automobile),
    le site 1 (concession Renault) EXCLUT Automobile."""
    s1 = CmsSite(id_org=org.id_org, site_name="Concession Renault")
    s2 = CmsSite(id_org=org.id_org, site_name="Centre commercial")
    db.add_all([s1, s2])
    await db.flush()
    p1 = CmsPlayer(id_org=org.id_org, id_site=s1.id_site, player_name="P-concession",
                   status="online")
    p2 = CmsPlayer(id_org=org.id_org, id_site=s2.id_site, player_name="P-centre",
                   status="online")
    cat = CmsIndustryCategory(id_org=org.id_org, category_name="Automobile")
    db.add_all([p1, p2, cat])
    await db.flush()
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Peugeot")
    db.add(adv)
    await db.flush()
    db.add(CmsAdvertiserIndustryCategory(
        id_advertiser=adv.id_advertiser, id_category=cat.id_category, id_org=org.id_org))
    db.add(CmsSiteExcludedCategory(id_site=s1.id_site, id_category=cat.id_category,
                                   id_org=org.id_org))
    await db.commit()
    return {"s1": s1, "s2": s2, "p1": p1, "p2": p2, "cat": cat, "adv": adv}


@pytest.mark.asyncio
async def test_category_crud_and_counts(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
        admin: CmsUser):
    r = await client.post("/api/v1/campaigns/industry-categories",
                          headers=_headers(admin), json={"category_name": "Boissons"})
    assert r.status_code == 201, r.text
    cid = r.json()["id_category"]
    # doublon (insensible à la casse) = 409
    r = await client.post("/api/v1/campaigns/industry-categories",
                          headers=_headers(admin), json={"category_name": "boissons"})
    assert r.status_code == 409

    inv = await _inventory(db_session, org)
    r = await client.get("/api/v1/campaigns/industry-categories", headers=_headers(admin))
    assert r.status_code == 200
    by_name = {c["category_name"]: c for c in r.json()}
    assert by_name["Automobile"]["advertiser_count"] == 1
    assert by_name["Automobile"]["excluded_site_count"] == 1
    assert by_name["Boissons"]["advertiser_count"] == 0

    # la liste des annonceurs expose les noms des catégories (multi 0088)
    r = await client.get("/api/v1/advertisers/", headers=_headers(admin))
    adv = next(a for a in r.json() if a["advertiser_name"] == "Peugeot")
    assert adv["industry_category_names"] == ["Automobile"]

    # delete : liaisons annonceur ET exclusions de sites purgées (CASCADE)
    r = await client.delete(
        f"/api/v1/campaigns/industry-categories/{inv['cat'].id_category}",
        headers=_headers(admin))
    assert r.status_code == 204
    links = (await db_session.execute(select(CmsAdvertiserIndustryCategory).where(
        CmsAdvertiserIndustryCategory.id_advertiser == inv["adv"].id_advertiser
    ))).scalars().all()
    assert links == []
    left = (await db_session.execute(select(CmsSiteExcludedCategory).where(
        CmsSiteExcludedCategory.id_site == inv["s1"].id_site))).scalars().all()
    assert left == []

    # cross-org = 404
    org_b = CmsOrganization(org_name="B", org_slug=f"b-{uuid.uuid4().hex[:8]}")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=org_b.id_org))
    await db_session.commit()
    admin_b = await _user(db_session, org_b, "CMS_ORG_ADMIN",
                          [("campaigns", "read"), ("campaigns", "edit")])
    r = await client.delete(f"/api/v1/campaigns/industry-categories/{cid}",
                            headers=_headers(admin_b))
    assert r.status_code == 404
    # ... et un annonceur ne peut pas pointer la catégorie d'une autre org
    r = await client.post("/api/v1/advertisers/", headers=_headers(admin_b),
                          json={"advertiser_name": "X",
                                "industry_categories": [cid]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_multi_categories_any_match_excludes(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
        admin: CmsUser):
    """Retour Ed 12/07 #8 : une agence de pub porte PLUSIEURS industries (migr 0088).
    Un site qui exclut AU MOINS UNE des catégories de l'annonceur l'exclut."""
    from app.services.campaign_inventory import advertiser_excluded_sites

    inv = await _inventory(db_session, org)
    cat2 = CmsIndustryCategory(id_org=org.id_org, category_name="Boissons")
    db_session.add(cat2)
    await db_session.commit()

    # l'annonceur devient une agence : Automobile + Boissons (PUT = remplace la liste)
    r = await client.put(f"/api/v1/advertisers/{inv['adv'].id_advertiser}",
                         headers=_headers(admin),
                         json={"industry_categories": [inv["cat"].id_category,
                                                       cat2.id_category]})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["industry_category_names"]) == ["Automobile", "Boissons"]

    # le site 1 n'exclut qu'Automobile → l'annonceur reste exclu (match sur AU MOINS une)
    excluded = await advertiser_excluded_sites(db_session, inv["adv"].id_advertiser)
    assert excluded == {inv["s1"].id_site}

    # retirer Automobile → plus exclu nulle part
    r = await client.put(f"/api/v1/advertisers/{inv['adv'].id_advertiser}",
                         headers=_headers(admin),
                         json={"industry_categories": [cat2.id_category]})
    assert r.status_code == 200
    assert r.json()["industry_category_names"] == ["Boissons"]
    excluded = await advertiser_excluded_sites(db_session, inv["adv"].id_advertiser)
    assert excluded == set()


@pytest.mark.asyncio
async def test_site_excluded_categories_update(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
        admin: CmsUser):
    inv = await _inventory(db_session, org)
    cat2 = CmsIndustryCategory(id_org=org.id_org, category_name="Boissons")
    db_session.add(cat2)
    await db_session.commit()

    # GET expose les exclusions
    r = await client.get(f"/api/v1/sites/{inv['s1'].id_site}", headers=_headers(admin))
    assert r.json()["campaign_excluded_categories"] == [inv["cat"].id_category]

    # PUT remplace l'ensemble
    r = await client.put(f"/api/v1/sites/{inv['s1'].id_site}", headers=_headers(admin),
                         json={"campaign_excluded_categories": [cat2.id_category]})
    assert r.status_code == 200, r.text
    assert r.json()["campaign_excluded_categories"] == [cat2.id_category]

    # liste vide = tout effacer ; catégorie inconnue = 404
    r = await client.put(f"/api/v1/sites/{inv['s1'].id_site}", headers=_headers(admin),
                         json={"campaign_excluded_categories": []})
    assert r.json()["campaign_excluded_categories"] == []
    r = await client.put(f"/api/v1/sites/{inv['s1'].id_site}", headers=_headers(admin),
                         json={"campaign_excluded_categories": [999_999]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_exclusion_removes_players_from_targeting_and_quote(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
        admin: CmsUser):
    inv = await _inventory(db_session, org)

    # Campagne Peugeot ciblant l'org → seul le player du site NON exclu compte
    r = await client.post("/api/v1/campaigns/", headers=_headers(admin), json={
        "id_advertiser": inv["adv"].id_advertiser, "campaign_name": "Peugeot 208",
        "starts_on": date.today().isoformat(),
        "ends_on": (date.today() + timedelta(days=6)).isoformat(),
        "sov_percent": 20, "targets": [{"target_type": "org"}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["target_player_count"] == 1

    # occupancy-check scopé annonceur : le player exclu n'apparaît pas
    r = await client.post("/api/v1/campaigns/occupancy-check", headers=_headers(admin),
                          json={"starts_on": date.today().isoformat(),
                                "ends_on": (date.today() + timedelta(days=6)).isoformat(),
                                "sov_percent": 20,
                                "targets": [{"target_type": "org"}],
                                "id_advertiser": inv["adv"].id_advertiser})
    assert r.status_code == 200
    pids = [p["id_player"] for p in r.json()["players"]]
    assert pids == [inv["p2"].id_player]
    # ... sans annonceur (pas de contexte) : les 2 players sont dans l'inventaire
    r = await client.post("/api/v1/campaigns/occupancy-check", headers=_headers(admin),
                          json={"starts_on": date.today().isoformat(),
                                "ends_on": (date.today() + timedelta(days=6)).isoformat(),
                                "sov_percent": 20,
                                "targets": [{"target_type": "org"}]})
    assert len(r.json()["players"]) == 2


@pytest.mark.asyncio
async def test_portal_sites_marked_excluded(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization):
    inv = await _inventory(db_session, org)
    portal = await _user(db_session, org, "CMS_ADVERTISER",
                         [("campaigns", "read")],
                         id_advertiser=inv["adv"].id_advertiser)
    r = await client.get("/api/v1/portal/sites", headers=_headers(portal))
    assert r.status_code == 200
    by_name = {s["site_name"]: s for s in r.json()}
    assert by_name["Concession Renault"]["excluded"] is True
    assert by_name["Concession Renault"]["screen_count"] == 0
    assert by_name["Centre commercial"]["excluded"] is False
    assert by_name["Centre commercial"]["screen_count"] == 1


@pytest.mark.asyncio
async def test_delivery_skips_excluded_advertiser(
        db_session: AsyncSession, org: CmsOrganization):
    """La diffusion (player-centrique) écarte les campagnes d'un annonceur dont la
    catégorie est exclue par le SITE du player — jamais de créatif à l'écran."""
    inv = await _inventory(db_session, org)
    media = CmsMedia(id_org=org.id_org, media_name="spot", media_type="video",
                     storage_key=f"t/{uuid.uuid4().hex}.mp4",
                     checksum_sha256="c", transcode_status="done", duration_ms=15_000)
    db_session.add(media)
    await db_session.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=inv["adv"].id_advertiser,
        campaign_name="Peugeot 208", status="approved",
        starts_on=date.today() - timedelta(days=1),
        ends_on=date.today() + timedelta(days=7), sov_percent=20.0)
    db_session.add(camp)
    await db_session.flush()
    db_session.add_all([
        CmsCampaignTarget(id_org=org.id_org, id_campaign=camp.id_campaign,
                          target_type="org", target_id=None),
        CmsCampaignCreative(id_org=org.id_org, id_campaign=camp.id_campaign,
                            id_media=media.id_media, duration_ms=15_000),
    ])
    await db_session.commit()

    now = datetime.now()
    slots_excluded = await campaign_ad_slots(
        db_session, org.id_org, inv["p1"].id_player, now, 60_000)
    slots_ok = await campaign_ad_slots(
        db_session, org.id_org, inv["p2"].id_player, now, 60_000)
    assert slots_excluded == []
    assert len(slots_ok) >= 1
    assert all(s.id_campaign == camp.id_campaign for s in slots_ok)
