"""
Tests du noyau Targeting (services/targeting.py) — DB-backed.

Couvre la résolution canonique player|group|site|tags|org, l'alias player_group,
la garde org (isolation cross-tenant), et le chemin player-centrique
(player_matches_target / player_has_tags).
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import CmsOrganization, CmsSite
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
from app.models.tag import CmsPlayerTagFilter, CmsTagNamespace, CmsTagValue
from app.services.targeting import (
    Target,
    player_has_tags,
    player_matches_target,
    players_for_target,
    players_for_targets,
)


@pytest_asyncio.fixture
async def fixt(db_session: AsyncSession):
    """Deux orgs ; org A : 3 players, 1 groupe (p1+p2), 1 site (p3), tags region sur p1/p2."""
    org_a = CmsOrganization(org_name="A", org_slug=f"a-{uuid.uuid4().hex[:8]}")
    org_b = CmsOrganization(org_name="B", org_slug=f"b-{uuid.uuid4().hex[:8]}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    site = CmsSite(id_org=org_a.id_org, site_name="Paris")
    db_session.add(site)
    await db_session.flush()

    p1 = CmsPlayer(id_org=org_a.id_org, player_name="p1")
    p2 = CmsPlayer(id_org=org_a.id_org, player_name="p2")
    p3 = CmsPlayer(id_org=org_a.id_org, player_name="p3", id_site=site.id_site)
    p_b = CmsPlayer(id_org=org_b.id_org, player_name="pB")  # autre org
    db_session.add_all([p1, p2, p3, p_b])
    await db_session.flush()

    grp = CmsPlayerGroup(id_org=org_a.id_org, group_name="grp")
    db_session.add(grp)
    await db_session.flush()
    db_session.add_all([
        CmsPlayerGroupMember(id_group=grp.id_group, id_player=p1.id_player),
        CmsPlayerGroupMember(id_group=grp.id_group, id_player=p2.id_player),
    ])

    # Taxonomie region : PACA sur p1, IDF sur p2 (via cms_player_tag_filters)
    ns = CmsTagNamespace(id_org=org_a.id_org, namespace_key="region")
    db_session.add(ns)
    await db_session.flush()
    paca = CmsTagValue(id_namespace=ns.id_namespace, tag_value="PACA")
    idf = CmsTagValue(id_namespace=ns.id_namespace, tag_value="IDF")
    db_session.add_all([paca, idf])
    await db_session.flush()
    db_session.add_all([
        CmsPlayerTagFilter(id_player=p1.id_player, id_namespace=ns.id_namespace, id_tag=paca.id_tag),
        CmsPlayerTagFilter(id_player=p2.id_player, id_namespace=ns.id_namespace, id_tag=idf.id_tag),
    ])
    await db_session.commit()

    return {
        "org_a": org_a.id_org, "org_b": org_b.id_org,
        "p1": p1.id_player, "p2": p2.id_player, "p3": p3.id_player, "p_b": p_b.id_player,
        "grp": grp.id_group, "site": site.id_site,
    }


@pytest.mark.asyncio
async def test_player_target(db_session, fixt):
    assert await players_for_target(db_session, fixt["org_a"], Target("player", fixt["p1"])) == {fixt["p1"]}


@pytest.mark.asyncio
async def test_player_target_cross_org_blocked(db_session, fixt):
    # un id_player d'une autre org ne doit pas fuir
    assert await players_for_target(db_session, fixt["org_a"], Target("player", fixt["p_b"])) == set()


@pytest.mark.asyncio
async def test_group_and_player_group_alias(db_session, fixt):
    expected = {fixt["p1"], fixt["p2"]}
    assert await players_for_target(db_session, fixt["org_a"], Target("group", fixt["grp"])) == expected
    # alias historique des schedules → même résultat, zéro migration de données
    assert await players_for_target(db_session, fixt["org_a"], Target("player_group", fixt["grp"])) == expected


@pytest.mark.asyncio
async def test_site_target(db_session, fixt):
    assert await players_for_target(db_session, fixt["org_a"], Target("site", fixt["site"])) == {fixt["p3"]}


@pytest.mark.asyncio
async def test_org_target(db_session, fixt):
    res = await players_for_target(db_session, fixt["org_a"], Target("org"))
    assert res == {fixt["p1"], fixt["p2"], fixt["p3"]}
    assert fixt["p_b"] not in res


@pytest.mark.asyncio
async def test_tags_target(db_session, fixt):
    paca = await players_for_target(db_session, fixt["org_a"], Target("tags", tag_expr={"region": ["PACA"]}))
    assert paca == {fixt["p1"]}
    both = await players_for_target(db_session, fixt["org_a"], Target("tags", tag_expr={"region": ["PACA", "IDF"]}))
    assert both == {fixt["p1"], fixt["p2"]}
    empty = await players_for_target(db_session, fixt["org_a"], Target("tags", tag_expr={}))
    assert empty == set()


@pytest.mark.asyncio
async def test_players_for_targets_union(db_session, fixt):
    res = await players_for_targets(db_session, fixt["org_a"],
                                    [Target("player", fixt["p3"]), Target("group", fixt["grp"])])
    assert res == {fixt["p1"], fixt["p2"], fixt["p3"]}


@pytest.mark.asyncio
async def test_player_matches_target(db_session, fixt):
    assert await player_matches_target(db_session, fixt["org_a"], fixt["p1"], Target("group", fixt["grp"]))
    assert not await player_matches_target(db_session, fixt["org_a"], fixt["p3"], Target("group", fixt["grp"]))
    assert await player_matches_target(db_session, fixt["org_a"], fixt["p3"], Target("site", fixt["site"]))
    assert await player_matches_target(db_session, fixt["org_a"], fixt["p2"], Target("org"))
    assert await player_matches_target(db_session, fixt["org_a"], fixt["p1"],
                                       Target("tags", tag_expr={"region": ["PACA"]}))
    assert not await player_matches_target(db_session, fixt["org_a"], fixt["p2"],
                                           Target("tags", tag_expr={"region": ["PACA"]}))


@pytest.mark.asyncio
async def test_player_has_tags(db_session, fixt):
    assert await player_has_tags(db_session, fixt["p1"], {"region": ["PACA"]})
    assert not await player_has_tags(db_session, fixt["p1"], {"region": ["IDF"]})
    assert not await player_has_tags(db_session, fixt["p1"], {})  # expr vide = False
