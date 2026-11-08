"""Tests « SOV réalisable » (demande Ed 2026-07-12, suite anti-martèlement).

Formule : boucle maison de B items / H ms + créatif de d ms → SOV max ≈
B×d / (H + B×d) (au plus 1 pub par frontière de boucle et par cycle).

- formule pure + garde zéro ;
- résolution de la boucle courante : schedule always > rien ; event actif prime ;
- d = durée moyenne PONDÉRÉE des créatifs (weight, même rotation que la diffusion) ;
- endpoint CMS /campaigns/occupancy-check → champ `achievable` complet ;
- endpoint /portal/occupancy-check → `achievable_sov_pct` agrégé STRIPPÉ ;
- player sans boucle courante → achievable null (pas de conseil faux).
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignCreative
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.campaign_feasibility import (
    _max_sov_pct,
    creative_avg_ms,
    feasibility_for_players,
)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="FEAS", org_slug=f"feas-{uuid.uuid4().hex[:8]}")
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


async def _role(db: AsyncSession, key: str, perms: list[tuple[str, str]]) -> CmsRole:
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalars().first()
    if role is None:
        role = CmsRole(id_org=None, role_key=key, label=key, is_system=True)
        db.add(role)
        await db.flush()
    for module, op in perms:
        await _grant(db, role, module, op)
    return role


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    role = await _role(db_session, "CMS_ORG_ADMIN",
                       [("campaigns", op) for op in ("read", "create", "edit", "publish")])
    user = CmsUser(id_org=org.id_org, email=f"adm-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return user


def _headers(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


async def _scene(db: AsyncSession, org: CmsOrganization, *, items=((30_000,), (30_000,))):
    """Player + playlist maison (durées passées) + schedule always ciblant le player."""
    site = CmsSite(id_org=org.id_org, site_name=f"S-{uuid.uuid4().hex[:6]}")
    db.add(site)
    await db.flush()
    player = CmsPlayer(id_org=org.id_org, player_name=f"P-{uuid.uuid4().hex[:6]}",
                       player_os="linux", id_site=site.id_site)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL", sync_mode="wall_clock")
    db.add_all([player, pl])
    await db.flush()
    for i, (dur,) in enumerate(items):
        m = CmsMedia(id_org=org.id_org, media_name=f"home{i}", media_type="video",
                     storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="a",
                     transcode_status="done", duration_ms=dur)
        db.add(m)
        await db.flush()
        db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media,
                               sort_order=i, duration_ms=dur))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist, is_active=True)
    db.add(sched)
    await db.flush()
    db.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player.id_player),
    ])
    await db.commit()
    return player, site, pl


# ── Formule pure ──────────────────────────────────────────────────────────────


def test_formula():
    # Cas NUC : 6 items de 150 s, spot 10 s → 60/(900+60) = 6.2 %
    assert _max_sov_pct(6, 900_000, 10_000) == 6.2
    # 2 items de 30 s, spot 10 s → 20/(60+20) = 25 %
    assert _max_sov_pct(2, 60_000, 10_000) == 25.0
    assert _max_sov_pct(0, 60_000, 10_000) == 0.0
    assert _max_sov_pct(2, 0, 10_000) == 0.0


# ── Service ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_loop_resolved(db_session: AsyncSession, org: CmsOrganization):
    player, _, _ = await _scene(db_session, org)
    feas = await feasibility_for_players(db_session, org.id_org, {player.id_player})
    assert feas is not None
    assert feas["max_sov_pct"] == 25.0
    assert feas["creative_duration_ms"] == 10_000
    assert feas["players"][0]["home_items"] == 2
    assert feas["players"][0]["home_duration_ms"] == 60_000
    assert feas["unresolved_players"] == 0


@pytest.mark.asyncio
async def test_event_takes_precedence(db_session: AsyncSession, org: CmsOrganization):
    """Un event content ACTIF prime sur le schedule (même préséance que le sync) :
    mono-média 60 s → B=1, max = 10/(60+10) = 14.3 %."""
    player, _, _ = await _scene(db_session, org)
    m = CmsMedia(id_org=org.id_org, media_name="takeover", media_type="video",
                 storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="e",
                 transcode_status="done", duration_ms=60_000)
    db_session.add(m)
    await db_session.flush()
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="EV", event_type="manual", event_kind="content",
        status="active", id_media=m.id_media,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
    ))
    await db_session.commit()
    feas = await feasibility_for_players(db_session, org.id_org, {player.id_player})
    assert feas["players"][0]["home_items"] == 1
    assert feas["max_sov_pct"] == 14.3


@pytest.mark.asyncio
async def test_no_current_loop_returns_none(db_session: AsyncSession, org: CmsOrganization):
    p = CmsPlayer(id_org=org.id_org, player_name="idle", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    assert await feasibility_for_players(db_session, org.id_org, {p.id_player}) is None


@pytest.mark.asyncio
async def test_creative_avg_weighted(db_session: AsyncSession, org: CmsOrganization):
    """d = moyenne pondérée par weight (10 s ×1 + 20 s ×3 → 17.5 s), même rotation
    que la diffusion. Une campagne sans créatif → None (l'appelant retombe sur 10 s)."""
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Acme")
    db_session.add(adv)
    await db_session.flush()
    camp = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                       campaign_name="C", status="draft",
                       starts_on=date.today(), ends_on=date.today() + timedelta(days=5),
                       sov_percent=10)
    db_session.add(camp)
    await db_session.flush()
    assert await creative_avg_ms(db_session, camp.id_campaign) is None
    for dur, weight in ((10_000, 1), (20_000, 3)):
        m = CmsMedia(id_org=org.id_org, media_name=f"cr{weight}", media_type="video",
                     storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="c",
                     transcode_status="done", duration_ms=dur)
        db_session.add(m)
        await db_session.flush()
        db_session.add(CmsCampaignCreative(
            id_org=org.id_org, id_campaign=camp.id_campaign, id_media=m.id_media,
            duration_ms=dur, weight=weight))
    await db_session.commit()
    assert await creative_avg_ms(db_session, camp.id_campaign) == 17_500


@pytest.mark.asyncio
async def test_reviewer_context_includes_achievable(
        db_session: AsyncSession, org: CmsOrganization):
    """Le contexte reviewer §21 expose {max_sov_pct, worst_player_name}."""
    from app.models.campaign import CmsCampaignTarget
    from app.services.approvals import resource_details

    player, _, _ = await _scene(db_session, org)
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Rev")
    db_session.add(adv)
    await db_session.flush()
    camp = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                       campaign_name="CR", status="draft",
                       starts_on=date.today(), ends_on=date.today() + timedelta(days=5),
                       sov_percent=40)
    db_session.add(camp)
    await db_session.flush()
    db_session.add(CmsCampaignTarget(id_org=org.id_org, id_campaign=camp.id_campaign,
                                     target_type="player", target_id=player.id_player))
    await db_session.commit()
    det = await resource_details(db_session, org.id_org, "campaign", camp.id_campaign)
    assert det["campaign"]["achievable"] == {
        "max_sov_pct": 25.0, "worst_player_name": player.player_name}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_occupancy_check_exposes_achievable(
        client: AsyncClient, db_session: AsyncSession,
        org: CmsOrganization, admin: CmsUser):
    player, _, _ = await _scene(db_session, org)
    r = await client.post(
        "/api/v1/campaigns/occupancy-check", headers=_headers(admin),
        json={"starts_on": date.today().isoformat(),
              "ends_on": (date.today() + timedelta(days=5)).isoformat(),
              "sov_percent": 40,
              "targets": [{"target_type": "player", "target_id": player.id_player}]})
    assert r.status_code == 200
    feas = r.json()["achievable"]
    assert feas is not None
    assert feas["max_sov_pct"] == 25.0
    assert feas["players"][0]["player_name"] == player.player_name


@pytest.mark.asyncio
async def test_occupancy_check_achievable_null_without_loop(
        client: AsyncClient, db_session: AsyncSession,
        org: CmsOrganization, admin: CmsUser):
    p = CmsPlayer(id_org=org.id_org, player_name="idle2", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    r = await client.post(
        "/api/v1/campaigns/occupancy-check", headers=_headers(admin),
        json={"starts_on": date.today().isoformat(),
              "ends_on": (date.today() + timedelta(days=5)).isoformat(),
              "sov_percent": 40,
              "targets": [{"target_type": "player", "target_id": p.id_player}]})
    assert r.status_code == 200
    assert r.json()["achievable"] is None


@pytest.mark.asyncio
async def test_portal_occupancy_stripped_aggregate(
        client: AsyncClient, db_session: AsyncSession, org: CmsOrganization):
    """Le portail ne reçoit QUE l'agrégat (achievable_sov_pct) — jamais le détail
    des players (règle de stripping §3.2)."""
    _, site, _ = await _scene(db_session, org)
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Brand")
    db_session.add(adv)
    await db_session.flush()
    role = await _role(db_session, "CMS_ADVERTISER",
                       [("campaigns", "read"), ("approvals", "submit")])
    user = CmsUser(id_org=org.id_org, email=f"adv-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True,
                   id_advertiser=adv.id_advertiser)
    db_session.add(user)
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()

    r = await client.post(
        "/api/v1/portal/occupancy-check", headers=_headers(user),
        json={"starts_on": date.today().isoformat(),
              "ends_on": (date.today() + timedelta(days=5)).isoformat(),
              "sov_percent": 40, "site_ids": [site.id_site]})
    assert r.status_code == 200
    body = r.json()
    assert body["achievable_sov_pct"] == 25.0
    assert "players" not in body and "achievable" not in body
