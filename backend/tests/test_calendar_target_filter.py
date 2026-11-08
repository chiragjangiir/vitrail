"""
Tests — filtre cible du calendrier unifié /schedules (retours beta testeurs 2026-07).

Les 3 listes (GET /schedules, GET /events, GET /campaigns/) acceptent
`target_type` + `target_id` (player | site | site_group | player_group) et ne
renvoient que les entités dont les cibles résolues (targeting canonique)
intersectent la cible-filtre.
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignTarget
from app.models.event import CmsEvent
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule, CmsScheduleTarget
from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    slug = f"caltf-{uuid.uuid4().hex[:8]}"
    o = CmsOrganization(org_name="CalTFOrg", org_slug=slug)
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def reader(db_session: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org,
        email=f"caltf-{uid}@test.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_CALTF_{uid}", label="Reader",
                   is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("schedules", "read"), ("events", "read"), ("campaigns", "read"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation
            )
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user, user.email


@pytest_asyncio.fixture
async def headers(client: AsyncClient, reader) -> dict[str, str]:
    _, email = reader
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password1!"}
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def topo(db_session: AsyncSession, org: CmsOrganization) -> dict:
    """2 sites, 1 groupe de sites (site1), 1 player par site."""
    s1 = CmsSite(id_org=org.id_org, site_name="Site A")
    s2 = CmsSite(id_org=org.id_org, site_name="Site B")
    db_session.add_all([s1, s2])
    await db_session.flush()
    sg = CmsSiteGroup(id_org=org.id_org, group_name="Region A")
    db_session.add(sg)
    await db_session.flush()
    db_session.add(CmsSiteGroupMember(
        id_org=org.id_org, id_site_group=sg.id_site_group, id_site=s1.id_site))
    p1 = CmsPlayer(id_org=org.id_org, player_name="P1", id_site=s1.id_site)
    p2 = CmsPlayer(id_org=org.id_org, player_name="P2", id_site=s2.id_site)
    db_session.add_all([p1, p2])
    await db_session.commit()
    return {"s1": s1, "s2": s2, "sg": sg, "p1": p1, "p2": p2}


# ── Schedules ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedules_target_filter(client: AsyncClient, headers, db_session, org, topo):
    sa = CmsSchedule(id_org=org.id_org, schedule_name="Sched-P1")
    sb = CmsSchedule(id_org=org.id_org, schedule_name="Sched-P2")
    db_session.add_all([sa, sb])
    await db_session.flush()
    db_session.add(CmsScheduleTarget(
        id_schedule=sa.id_schedule, target_type="player", target_id=topo["p1"].id_player))
    db_session.add(CmsScheduleTarget(
        id_schedule=sb.id_schedule, target_type="player", target_id=topo["p2"].id_player))
    await db_session.commit()

    # Sans filtre : les deux.
    r = await client.get("/api/v1/schedules", headers=headers)
    assert r.status_code == 200
    names = {s["schedule_name"] for s in r.json()}
    assert {"Sched-P1", "Sched-P2"} <= names

    # Par player : un seul.
    r = await client.get(
        f"/api/v1/schedules?target_type=player&target_id={topo['p1'].id_player}",
        headers=headers)
    assert [s["schedule_name"] for s in r.json()] == ["Sched-P1"]

    # Par site : résolution site → players du site.
    r = await client.get(
        f"/api/v1/schedules?target_type=site&target_id={topo['s2'].id_site}",
        headers=headers)
    assert [s["schedule_name"] for s in r.json()] == ["Sched-P2"]

    # Par groupe de sites : site1 ∈ Region A → Sched-P1.
    r = await client.get(
        f"/api/v1/schedules?target_type=site_group&target_id={topo['sg'].id_site_group}",
        headers=headers)
    assert [s["schedule_name"] for s in r.json()] == ["Sched-P1"]


# ── Events ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_target_filter(client: AsyncClient, headers, db_session, org, topo):
    e1 = CmsEvent(
        id_org=org.id_org, event_name="Ev-P1", event_type="manual", event_kind="content",
        status="inactive",
        target_config={"target_type": "player", "target_ids": [topo["p1"].id_player]},
    )
    e2 = CmsEvent(
        id_org=org.id_org, event_name="Ev-Org", event_type="manual", event_kind="content",
        status="inactive", target_config={"target_type": "org"},
    )
    db_session.add_all([e1, e2])
    await db_session.commit()

    # Par player p2 : l'event org matche (il touche tout le parc), pas Ev-P1.
    r = await client.get(
        f"/api/v1/events?target_type=player&target_id={topo['p2'].id_player}",
        headers=headers)
    assert r.status_code == 200
    names = {e["event_name"] for e in r.json()}
    assert "Ev-Org" in names and "Ev-P1" not in names

    # Par groupe de sites (site1) : les deux (Ev-P1 via p1, Ev-Org car org).
    r = await client.get(
        f"/api/v1/events?target_type=site_group&target_id={topo['sg'].id_site_group}",
        headers=headers)
    names = {e["event_name"] for e in r.json()}
    assert {"Ev-P1", "Ev-Org"} <= names


# ── Campagnes ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_campaigns_target_filter(client: AsyncClient, headers, db_session, org, topo):
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="AdvTF")
    db_session.add(adv)
    await db_session.flush()
    today = date.today()
    c1 = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                     campaign_name="Camp-SiteA", starts_on=today,
                     ends_on=today + timedelta(days=7))
    c2 = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                     campaign_name="Camp-P2", starts_on=today,
                     ends_on=today + timedelta(days=7))
    db_session.add_all([c1, c2])
    await db_session.flush()
    db_session.add(CmsCampaignTarget(
        id_org=org.id_org, id_campaign=c1.id_campaign,
        target_type="site", target_id=topo["s1"].id_site))
    db_session.add(CmsCampaignTarget(
        id_org=org.id_org, id_campaign=c2.id_campaign,
        target_type="player", target_id=topo["p2"].id_player))
    await db_session.commit()

    # Par groupe de sites (site1) : Camp-SiteA seulement.
    r = await client.get(
        f"/api/v1/campaigns/?target_type=site_group&target_id={topo['sg'].id_site_group}",
        headers=headers)
    assert r.status_code == 200
    assert [c["campaign_name"] for c in r.json()] == ["Camp-SiteA"]

    # Par player p2 : Camp-P2 seulement.
    r = await client.get(
        f"/api/v1/campaigns/?target_type=player&target_id={topo['p2'].id_player}",
        headers=headers)
    assert [c["campaign_name"] for c in r.json()] == ["Camp-P2"]

    # target_type invalide → 422.
    r = await client.get(
        "/api/v1/campaigns/?target_type=bogus&target_id=1", headers=headers)
    assert r.status_code == 422
