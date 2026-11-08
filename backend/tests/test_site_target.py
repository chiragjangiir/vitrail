"""
Régression — cible « site » sur les schedules et les events (audit 2026-07-18).

Le bug : `targeting.players_for_target` gérait `site` (donc l'aperçu « players ciblés »
comptait juste), mais AUCUN chemin player-centrique ne le connaissait — ws.py (sync live),
prefetch, inventaire, simulation de journée, feasibility. Une programmation ciblant un site
était donc enregistrée, comptée… et jamais diffusée, sans la moindre erreur.

Ces tests verrouillent le comportement bout en bout :
  - un schedule ciblant un SITE atteint les players de ce site (et eux seuls)
  - un event ciblant un SITE matche via `event_target_matches`
  - le prefetch et l'inventaire voient la playlist du site
  - un target_type hors vocabulaire est REFUSÉ (422) au lieu d'être ignoré en silence
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.targeting import event_target_matches


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SiteTargetOrg", org_slug=f"st-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org: CmsOrganization) -> dict:
    """Deux sites, un player dans chacun, une playlist programmée sur le SITE A."""
    site_a = CmsSite(id_org=org.id_org, site_name="Site A")
    site_b = CmsSite(id_org=org.id_org, site_name="Site B")
    db_session.add_all([site_a, site_b])
    await db_session.flush()

    p_in = CmsPlayer(
        id_org=org.id_org, id_site=site_a.id_site, player_name="In A", player_os="linux")
    p_out = CmsPlayer(
        id_org=org.id_org, id_site=site_b.id_site, player_name="In B", player_os="linux")
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Site A Loop")
    db_session.add_all([p_in, p_out, playlist])
    await db_session.flush()

    sched = CmsSchedule(
        id_org=org.id_org, schedule_name="Site A Sched", schedule_kind="content",
        id_playlist=playlist.id_playlist, priority=10, is_active=True,
    )
    db_session.add(sched)
    await db_session.flush()
    db_session.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        # ⬇️ LA cible qui était silencieusement ignorée
        CmsScheduleTarget(
            id_schedule=sched.id_schedule, target_type="site", target_id=site_a.id_site),
    ])
    await db_session.commit()
    return {
        "site_a": site_a.id_site, "site_b": site_b.id_site,
        "p_in": p_in.id_player, "p_out": p_out.id_player,
        "playlist": playlist.id_playlist,
    }


async def test_site_scheduled_playlist_reaches_player_of_that_site(
    db_session: AsyncSession, scene: dict, monkeypatch
) -> None:
    """Le cœur du bug : avant le fix, le payload de sync était vide pour le player du site."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    payload = await _resolve_sync_payload(db_session, scene["p_in"])
    assert payload["id_playlist"] == scene["playlist"]


async def test_player_of_another_site_is_not_targeted(
    db_session: AsyncSession, scene: dict, monkeypatch
) -> None:
    """La cible site ne doit pas déborder : le player du site B ne reçoit rien."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    payload = await _resolve_sync_payload(db_session, scene["p_out"])
    assert payload.get("id_playlist") is None


async def test_player_without_site_is_not_targeted(
    db_session: AsyncSession, org: CmsOrganization, scene: dict, monkeypatch
) -> None:
    """id_site NULL ne doit jamais matcher une cible site (garde du `is not None`)."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    orphan = CmsPlayer(
        id_org=org.id_org, id_site=None, player_name="Orphan", player_os="linux")
    db_session.add(orphan)
    await db_session.commit()

    payload = await _resolve_sync_payload(db_session, orphan.id_player)
    assert payload.get("id_playlist") is None


async def test_prefetch_and_inventory_see_the_site_schedule(
    db_session: AsyncSession, scene: dict
) -> None:
    """Les chemins offline-first (look-ahead, inventaire) doivent aussi honorer la cible."""
    from app.services.prefetch import _content_schedule_ids

    sched_ids = await _content_schedule_ids(db_session, 0, scene["p_in"], set())
    assert sched_ids, "le prefetch ignore la cible site → contenu non pré-téléchargé"

    sched_ids_out = await _content_schedule_ids(db_session, 0, scene["p_out"], set())
    assert not sched_ids_out


async def test_event_targeting_a_site_reaches_its_players(
    db_session: AsyncSession, org: CmsOrganization, scene: dict, monkeypatch
) -> None:
    """Bout en bout : un event ciblant un SITE doit primer sur le schedule pour les
    players de ce site, et laisser les autres intacts."""
    import app.api.v1.endpoints.ws as ws
    from app.api.v1.endpoints.ws import _resolve_sync_payload
    from app.models.event import CmsEvent
    from app.models.playlist import CmsPlaylist as PL

    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    ev_playlist = PL(id_org=org.id_org, playlist_name="Event Loop")
    db_session.add(ev_playlist)
    await db_session.flush()
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Site Event", event_type="manual", status="active",
        priority=90, id_playlist=ev_playlist.id_playlist,
        target_config={"target_type": "site", "target_ids": [scene["site_a"]]},
    ))
    await db_session.commit()

    payload_in = await _resolve_sync_payload(db_session, scene["p_in"])
    assert payload_in["id_playlist"] == ev_playlist.id_playlist

    payload_out = await _resolve_sync_payload(db_session, scene["p_out"])
    assert payload_out.get("id_playlist") is None


def test_event_schema_rejects_unknown_target_type() -> None:
    """target_config est un dict libre : sans garde-fou, un type non gere par le
    matcher etait accepte puis ignore a la diffusion."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.event import EventCreate, EventUpdate

    base = dict(event_name="E", event_type="manual", id_playlist=1)
    EventCreate(**base, target_config={"target_type": "site", "target_ids": [1]})
    with pytest.raises(ValidationError):
        EventCreate(**base, target_config={"target_type": "region", "target_ids": [1]})
    with pytest.raises(ValidationError):
        EventUpdate(target_config={"target_type": "region", "target_ids": [1]})


async def test_reports_resolver_supports_site_and_site_group(
    db_session: AsyncSession, org: CmsOrganization, scene: dict
) -> None:
    """Les rapports (PoP + analytics) partagent desormais UN resolveur delegue au
    targeting canonique — ce qui leur apporte `site_group`, jusque-la absent des
    deux clones maison (audit ciblage 2026-07-18)."""
    from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember
    from app.services.analytics import resolve_player_ids

    sg = CmsSiteGroup(id_org=org.id_org, group_name="Region Sud")
    db_session.add(sg)
    await db_session.flush()
    db_session.add(CmsSiteGroupMember(
        id_org=org.id_org, id_site_group=sg.id_site_group, id_site=scene["site_a"]))
    await db_session.commit()

    # Aucun filtre => None (toute l'org).
    assert await resolve_player_ids(db_session, org.id_org, None, None, None) is None
    # Par site.
    assert await resolve_player_ids(
        db_session, org.id_org, None, None, scene["site_a"]) == [scene["p_in"]]
    # Par groupe de sites — c'est ce qui n'existait pas.
    assert await resolve_player_ids(
        db_session, org.id_org, None, None, None, sg.id_site_group) == [scene["p_in"]]


def test_event_target_matches_honours_site() -> None:
    tc = {"target_type": "site", "target_ids": [7]}
    assert event_target_matches(tc, 1, set(), set(), id_site=7)
    assert not event_target_matches(tc, 1, set(), set(), id_site=8)
    # Player sans site → jamais de match (pas de crash).
    assert not event_target_matches(tc, 1, set(), set(), id_site=None)


async def test_unknown_target_type_is_rejected_not_ignored(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Avant : `target_type` était un `str` libre → une valeur non gérée par les chemins
    player-centriques était acceptée puis ignorée. Désormais 422 explicite."""
    user = CmsUser(
        id_org=org.id_org, email=f"st-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    # La base de test ne joue pas le seed 0002 → on crée le rôle et la permission.
    role = CmsRole(
        id_org=org.id_org, role_key=f"CMS_SCHED_{uuid.uuid4().hex[:8]}",
        label="Sched", is_system=False)
    db_session.add(role)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="schedules", operation="create", label="schedules.create")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db_session.flush()
    perm = (await db_session.execute(
        select(CmsPermission).where(
            CmsPermission.module == "schedules", CmsPermission.operation == "create")
    )).scalar_one()
    db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db_session.add(playlist)
    await db_session.commit()

    token = create_access_token(str(user.id_user))
    resp = await client.post(
        "/api/v1/schedules",
        json={
            "schedule_name": "Bogus target",
            "schedule_kind": "content",
            "id_playlist": playlist.id_playlist,
            "rules": [{"rule_type": "always"}],
            "targets": [{"target_type": "region", "target_id": 1}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text
