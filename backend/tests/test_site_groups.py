"""
Tests S6 Retail Media — Groupes de SITES (cible « région » canonique).

Covers:
  - CRUD /site-groups + membership (idempotent)
  - résolution targeting : site_group → sites membres → players (players_for_target +
    player_matches_target), y compris un player posé APRÈS la création du groupe
  - purge des cibles génériques à la suppression (schedules + events + campagnes)
  - cible de campagne target_type=site_group acceptée (422 sans target_id)
"""

import uuid
from datetime import date

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.targeting import Target, player_matches_target, players_for_target


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"sg-org-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="SiteGroupOrg", org_slug=slug)
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
        email=f"admin-{uid}@sgtest.com",
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
    # Permissions campaigns:* explicites (la base de test n'a pas le seed 0002) —
    # nécessaires au test de cible de campagne site_group.
    from app.models.role import CmsPermission, CmsRolePermission
    camp_role = CmsRole(id_org=org.id_org, role_key=f"CMS_CAMP_{uid}", label="Camp", is_system=False)
    db_session.add(camp_role)
    await db_session.flush()
    for op in ("create", "read", "edit", "delete", "publish", "report"):
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module="campaigns", operation=op, label=f"campaigns.{op}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == "campaigns", CmsPermission.operation == op)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=camp_role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=camp_role.id_role))
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_token(org_admin: CmsUser, org: CmsOrganization) -> str:
    return create_access_token(
        org_admin.id_user,
        extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"},
    )


@pytest_asyncio.fixture
async def site_id(db_session: AsyncSession, org: CmsOrganization) -> int:
    s = CmsSite(id_org=org.id_org, site_name=f"Site-{uuid.uuid4().hex[:8]}")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s.id_site


@pytest_asyncio.fixture
async def group_id(client: AsyncClient, admin_token: str) -> int:
    resp = await client.post(
        "/api/v1/site-groups/",
        json={"group_name": f"Region-{uuid.uuid4().hex[:8]}", "description": "Sud-Ouest"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_site_group"]


async def _make_player(db_session: AsyncSession, id_org: int, id_site: int | None) -> int:
    p = CmsPlayer(
        id_org=id_org, player_name=f"P-{uuid.uuid4().hex[:8]}",
        player_os="linux", id_site=id_site,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p.id_player


# ── CRUD + membership ──────────────────────────────────────────────────────────

async def test_create_and_list(client: AsyncClient, admin_token: str, group_id: int) -> None:
    resp = await client.get(
        "/api/v1/site-groups/", headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    ids = [g["id_site_group"] for g in rows]
    assert group_id in ids
    me = next(g for g in rows if g["id_site_group"] == group_id)
    assert me["site_count"] == 0
    assert me["player_count"] == 0


async def test_update_group(client: AsyncClient, admin_token: str, group_id: int) -> None:
    new_name = f"Nord-Est-{uuid.uuid4().hex[:8]}"
    resp = await client.put(
        f"/api/v1/site-groups/{group_id}",
        json={"group_name": new_name},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["group_name"] == new_name


async def test_membership_and_counts(
    client: AsyncClient, admin_token: str, group_id: int, site_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    # Ajout idempotent
    for _ in range(2):
        resp = await client.post(
            f"/api/v1/site-groups/{group_id}/sites",
            json={"id_site": site_id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

    await _make_player(db_session, org.id_org, site_id)

    resp = await client.get(
        f"/api/v1/site-groups/{group_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    body = resp.json()
    assert body["site_count"] == 1
    assert body["player_count"] == 1

    listed = await client.get(
        f"/api/v1/site-groups/{group_id}/sites",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert [s["id_site"] for s in listed.json()] == [site_id]

    # Retrait
    resp = await client.delete(
        f"/api/v1/site-groups/{group_id}/sites/{site_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204
    listed = await client.get(
        f"/api/v1/site-groups/{group_id}/sites",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.json() == []


async def test_add_foreign_site_404(
    client: AsyncClient, admin_token: str, group_id: int, db_session: AsyncSession,
) -> None:
    """Un site d'une AUTRE org ne peut pas rejoindre le groupe (cross-tenant = 404)."""
    other = CmsOrganization(org_name="OtherOrg", org_slug=f"sg-other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    foreign = CmsSite(id_org=other.id_org, site_name="Foreign")
    db_session.add(foreign)
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/site-groups/{group_id}/sites",
        json={"id_site": foreign.id_site},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


# ── Résolution targeting ───────────────────────────────────────────────────────

async def test_targeting_resolution(
    client: AsyncClient, admin_token: str, group_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    """site_group → sites membres → players ; un player posé APRÈS la création du
    groupe dans un site membre est adressé automatiquement (l'avantage clé vs
    groupes de players)."""
    s1 = CmsSite(id_org=org.id_org, site_name=f"S1-{uuid.uuid4().hex[:6]}")
    s2 = CmsSite(id_org=org.id_org, site_name=f"S2-{uuid.uuid4().hex[:6]}")
    db_session.add_all([s1, s2])
    await db_session.commit()

    await client.post(
        f"/api/v1/site-groups/{group_id}/sites",
        json={"id_site": s1.id_site},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    p_in = await _make_player(db_session, org.id_org, s1.id_site)      # après l'ajout du site
    p_out = await _make_player(db_session, org.id_org, s2.id_site)
    p_nosite = await _make_player(db_session, org.id_org, None)

    tgt = Target(target_type="site_group", target_id=group_id)
    resolved = await players_for_target(db_session, org.id_org, tgt)
    assert resolved == {p_in}

    assert await player_matches_target(db_session, org.id_org, p_in, tgt) is True
    assert await player_matches_target(db_session, org.id_org, p_out, tgt) is False
    assert await player_matches_target(db_session, org.id_org, p_nosite, tgt) is False

    # target_id absent → personne
    assert await players_for_target(
        db_session, org.id_org, Target(target_type="site_group")) == set()


# ── Purge des cibles orphelines à la suppression ───────────────────────────────

async def test_delete_group_cleans_generic_targets(
    client: AsyncClient, admin_token: str, group_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    """La suppression purge les cibles génériques sans FK : cms_schedule_targets +
    target_ids JSONB des events + cms_campaign_targets (même règle que les groupes
    de players, fix f5ac283)."""
    from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignTarget
    from app.models.event import CmsEvent
    from app.models.schedule import CmsSchedule, CmsScheduleTarget

    sched = CmsSchedule(id_org=org.id_org, schedule_name="S-ghost-sg", schedule_kind="content")
    ev = CmsEvent(
        id_org=org.id_org, event_name="E-ghost-sg", event_type="manual", event_kind="content",
        target_config={"target_type": "site_group", "target_ids": [group_id, 777777]},
    )
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name=f"Adv-{uuid.uuid4().hex[:6]}")
    db_session.add_all([sched, ev, adv])
    await db_session.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser,
        campaign_name="C-ghost-sg", starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 31),
    )
    db_session.add(camp)
    await db_session.flush()
    db_session.add(CmsScheduleTarget(
        id_schedule=sched.id_schedule, target_type="site_group", target_id=group_id))
    db_session.add(CmsCampaignTarget(
        id_org=org.id_org, id_campaign=camp.id_campaign,
        target_type="site_group", target_id=group_id))
    await db_session.commit()
    ev_id, sched_id, camp_id = ev.id_event, sched.id_schedule, camp.id_campaign

    del_resp = await client.delete(
        f"/api/v1/site-groups/{group_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    db_session.expire_all()
    ev2 = (await db_session.execute(
        select(CmsEvent).where(CmsEvent.id_event == ev_id))).scalar_one()
    ids = (ev2.target_config or {}).get("target_ids", [])
    assert group_id not in ids
    assert 777777 in ids
    left_sched = (await db_session.execute(select(CmsScheduleTarget).where(
        CmsScheduleTarget.id_schedule == sched_id))).scalars().all()
    assert left_sched == []
    left_camp = (await db_session.execute(select(CmsCampaignTarget).where(
        CmsCampaignTarget.id_campaign == camp_id))).scalars().all()
    assert left_camp == []


# ── Cible de campagne site_group ───────────────────────────────────────────────

async def test_campaign_accepts_site_group_target(
    client: AsyncClient, admin_token: str, group_id: int, site_id: int,
    db_session: AsyncSession, org: CmsOrganization,
) -> None:
    await client.post(
        f"/api/v1/site-groups/{group_id}/sites",
        json={"id_site": site_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    adv = await client.post(
        "/api/v1/advertisers/",
        json={"advertiser_name": f"Adv-{uuid.uuid4().hex[:6]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adv.status_code == 201
    body = {
        "campaign_name": f"Camp-{uuid.uuid4().hex[:6]}",
        "id_advertiser": adv.json()["id_advertiser"],
        "starts_on": "2026-07-01", "ends_on": "2026-07-31",
        "sov_percent": 10,
        "targets": [{"target_type": "site_group", "target_id": group_id}],
    }
    resp = await client.post(
        "/api/v1/campaigns/", json=body,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    tgts = resp.json()["targets"]
    assert [(t["target_type"], t["target_id"]) for t in tgts] == [("site_group", group_id)]

    # site_group sans target_id = 422 (validation Pydantic)
    bad = {**body, "campaign_name": "Camp-bad", "targets": [{"target_type": "site_group"}]}
    resp = await client.post(
        "/api/v1/campaigns/", json=bad,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422
