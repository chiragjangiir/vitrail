"""
Tests Sprint 2.7 — Gouvernance §XVIII Phase 2 — Moteur de compilation (lot 2a).

Deux niveaux :
- **Pur** : `governance_engine.compile_program` (ordre national→local, item_count, préemption,
  time_budget soft/hard = volume absolu par cycle) — sans DB.
- **Endpoints** : `/players/{id}/compiled-schedule` (couches concaténées national→local) et
  `/governance/nodes/{id}/budget-status` (consommation planifiée), + 404 cross-tenant.
"""

import uuid
from datetime import datetime, time

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.governance import CmsDelegationRule, CmsGovernanceAssignment, CmsGovernanceNode
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule, CmsScheduleRule
from app.models.user import CmsUser
from app.services.governance_engine import (
    CompiledItem,
    DelegationConstraints,
    LayerInput,
    compile_program,
    node_budget_status,
    parse_constraints,
)
from app.services.scheduling import TimeRule


# ── Helpers purs ──────────────────────────────────────────────────────────────

def _items(node, sched, specs):
    """specs = [(id_media, duration_ms), ...] → list[CompiledItem]."""
    return [
        CompiledItem(id_media=m, media_name=f"M{m}", media_type="video",
                     duration_ms=d, id_node=node, id_schedule=sched)
        for m, d in specs
    ]


def _layer(*, node, level, sched, prio=0, constraints=None, items):
    return LayerInput(
        id_node=node, node_name=f"N{node}", node_level=level, id_schedule=sched,
        priority=prio, constraints=constraints or DelegationConstraints(), items=items,
    )


NOW = datetime(2026, 6, 8, 12, 0, 0)  # lundi midi


# ── Tests purs ────────────────────────────────────────────────────────────────

def test_empty():
    prog = compile_program([], NOW)
    assert prog.items == [] and prog.layers == [] and prog.cycle_duration_ms == 0


def test_order_national_then_local():
    national = _layer(node=1, level=0, sched=10, prio=5, items=_items(1, 10, [(1, 1000)]))
    local = _layer(node=2, level=2, sched=20, prio=99, items=_items(2, 20, [(2, 1000)]))
    prog = compile_program([local, national], NOW)
    assert [it.id_media for it in prog.items] == [1, 2]  # national d'abord malgré prio locale
    assert prog.cycle_duration_ms == 2000


def test_item_count_rotates_instead_of_truncating():
    """`item_count` = N items PAR TOUR, **en rotation** (décision Ed 2026-07-26).

    Avant, c'était `items[:N]` : toujours les N MÊMES items, le reste du contenu du nœud ne
    passait JAMAIS. Ed : « il faut passer TOUS ses contenus, pas seulement les 2 premiers ».
    N=3, K=2 → T = 3 tours, et chaque contenu passe exactement T*K/N = 2 fois par cycle.
    """
    layer = _layer(
        node=1, level=0, sched=10,
        constraints=DelegationConstraints(item_count=2),
        items=_items(1, 10, [(1, 1000), (2, 1000), (3, 1000)]),
    )
    prog = compile_program([layer], NOW)
    assert prog.turns == 3
    assert [it.id_media for it in prog.items] == [1, 2, 3, 1, 2, 3]
    from collections import Counter
    assert all(c == 2 for c in Counter(it.id_media for it in prog.items).values())
    # Chaque tour ne diffuse bien que 2 items — le nœud ne déborde pas son quota.
    assert len(prog.items) == prog.turns * 2
    rep = prog.layers[0]
    assert rep.item_count == 6   # contributions cumulées sur tout le cycle


def test_item_count_without_rotation_when_it_covers_everything():
    """N ≥ nombre d'items : rien à faire tourner, un seul tour (comportement d'origine)."""
    layer = _layer(
        node=1, level=0, sched=10,
        constraints=DelegationConstraints(item_count=5),
        items=_items(1, 10, [(1, 1000), (2, 1000)]),
    )
    prog = compile_program([layer], NOW)
    assert prog.turns == 1
    assert [it.id_media for it in prog.items] == [1, 2]


def test_toto_three_levels_rotate_together():
    """Scénario TOTO : national 1 vidéo (tout), département 8 par 2, site 10 par 1.

    Le cycle enchaîne T = ppcm(4, 10) = 20 tours ; chaque tour diffuse national + 2 du
    département + 1 du site. Sur le cycle, chaque vidéo de département passe 5 fois et
    chaque contenu de site 2 fois — c'est ce que l'indicateur de taux doit annoncer.
    """
    from collections import Counter

    national = _layer(node=1, level=0, sched=10, constraints=DelegationConstraints(),
                      items=_items(1, 10, [(100, 30_000)]))
    dept = _layer(node=2, level=1, sched=20,
                  constraints=DelegationConstraints(item_count=2),
                  items=_items(2, 20, [(200 + i, 20_000) for i in range(8)]))
    site = _layer(node=3, level=2, sched=30,
                  constraints=DelegationConstraints(item_count=1),
                  items=_items(3, 30, [(300 + i, 10_000) for i in range(10)]))

    prog = compile_program([national, dept, site], NOW)
    assert prog.turns == 20            # ppcm(8/gcd(8,2)=4, 10/gcd(10,1)=10)
    assert prog.truncated is False
    assert len(prog.items) == 20 * (1 + 2 + 1)

    counts = Counter(it.id_media for it in prog.items)
    assert counts[100] == 20                                   # national à chaque tour
    assert all(counts[200 + i] == 5 for i in range(8))         # 20 tours x 2 / 8
    assert all(counts[300 + i] == 2 for i in range(10))        # 20 tours x 1 / 10
    # Tous les contenus passent — c'était la demande d'Ed.
    assert len(counts) == 19


def test_cycle_truncation_is_reported():
    """Cardinalités premières entre elles → PPCM au-delà du garde-fou : le cycle est réduit
    ET SIGNALÉ (`truncated`). Sans ce drapeau, un contenu passerait moins souvent que ce que
    la configuration annonce, sans que personne ne le sache."""
    a = _layer(node=1, level=0, sched=10, constraints=DelegationConstraints(item_count=1),
               items=_items(1, 10, [(100 + i, 1000) for i in range(11)]))
    b = _layer(node=2, level=1, sched=20, constraints=DelegationConstraints(item_count=1),
               items=_items(2, 20, [(200 + i, 1000) for i in range(13)]))
    prog = compile_program([a, b], NOW)
    assert prog.truncated is True      # ppcm(11, 13) = 143 > garde-fou
    assert prog.turns < 143


def test_time_budget_applies_per_turn_not_per_unrolled_cycle():
    """Le budget est un volume PAR BOUCLE (D1). L'appliquer au cycle déroulé le diluerait par
    un nombre de tours qui dépend des AUTRES nœuds — exactement le défaut R13 qu'on a corrigé."""
    dept = _layer(node=2, level=1, sched=20,
                  constraints=DelegationConstraints(item_count=2, time_budget_sec_per_cycle=30,
                                                    soft_cut=False),
                  items=_items(2, 20, [(200 + i, 20_000) for i in range(4)]))
    # Un autre nœud force le cycle à 3 tours sans rien changer au budget du département.
    other = _layer(node=3, level=2, sched=30, constraints=DelegationConstraints(item_count=1),
                   items=_items(3, 30, [(300 + i, 1000) for i in range(3)]))
    prog = compile_program([dept, other], NOW)
    dept_items = [it for it in prog.items if it.id_schedule == 20]
    # 30 s de budget, items de 20 s, hard cut → 1 item par tour, sur chacun des tours.
    assert len(dept_items) == prog.turns
    assert prog.layers[0].budget_trimmed is True


def test_oversized_content_is_dropped_and_reported():
    """L'attaque décrite par Ed : « je fais une compil de toutes mes pubs en une seule qui
    dure 3 h et je nique tout le monde ».

    Le « N par tour » compte des ITEMS, pas du temps : un seul fichier de 3 h respecte
    « 1 par tour » et rafle la boucle. Le plafond de durée PAR CONTENU l'écarte — et le
    NOMME dans le rapport, parce qu'un contenu qui disparaît en silence est précisément le
    défaut qu'on passe la journée à corriger.
    """
    layer = _layer(
        node=2, level=1, sched=20,
        constraints=DelegationConstraints(item_count=1, max_item_sec=90),
        items=_items(2, 20, [(1, 30_000), (2, 3 * 3600 * 1000), (3, 45_000)]),
    )
    prog = compile_program([layer], NOW)
    passed = {it.id_media for it in prog.items}
    assert 2 not in passed                       # la compil de 3 h ne passe pas
    assert passed == {1, 3}
    assert prog.layers[0].dropped_too_long == ["M2"]


def test_time_budget_alone_does_not_stop_the_three_hour_compilation():
    """Pourquoi le plafond par contenu était nécessaire : `time_budget` seul ne suffit PAS.

    Son mode par défaut (`soft_cut` = terminer l'item qui déborde) laisse passer les 3 h
    entières. C'est ce trou que le plafond de durée ferme.
    """
    layer = _layer(
        node=2, level=1, sched=20,
        constraints=DelegationConstraints(item_count=1, time_budget_sec_per_cycle=60),
        items=_items(2, 20, [(2, 3 * 3600 * 1000)]),
    )
    prog = compile_program([layer], NOW)
    assert [it.id_media for it in prog.items] == [2]        # elle passe malgré le budget
    assert prog.cycle_duration_ms == 3 * 3600 * 1000
    assert prog.layers[0].budget_overflow is True           # signalé, mais diffusé


def test_preemptive_national_suppresses_lower():
    national = _layer(node=1, level=0, sched=10,
                      constraints=DelegationConstraints(preemptive=True),
                      items=_items(1, 10, [(1, 1000)]))
    local = _layer(node=2, level=2, sched=20, items=_items(2, 20, [(2, 1000)]))
    prog = compile_program([national, local], NOW)
    assert [it.id_media for it in prog.items] == [1]
    statuses = {r.id_schedule: r.status for r in prog.layers}
    assert statuses[10] == "active" and statuses[20] == "preempted"


def test_time_budget_soft_cut_keeps_overflow_item():
    # Volume ABSOLU (D1) : budget 15 s/cycle → allowed = 15000 ms.
    # 1er item (10s) tient (acc=10s), 2e déborde (20s>15s) → soft_cut garde le 2e (overflow),
    # coupe le 3e.
    layer = _layer(
        node=1, level=0, sched=10,
        constraints=DelegationConstraints(time_budget_sec_per_cycle=15, soft_cut=True),
        items=_items(1, 10, [(1, 10000), (2, 10000), (3, 10000)]),
    )
    prog = compile_program([layer], NOW)
    assert [it.id_media for it in prog.items] == [1, 2]
    rep = prog.layers[0]
    assert rep.budget_trimmed is True and rep.budget_overflow is True


def test_time_budget_hard_cut_drops_overflow_item():
    layer = _layer(
        node=1, level=0, sched=10,
        constraints=DelegationConstraints(time_budget_sec_per_cycle=15, soft_cut=False),
        items=_items(1, 10, [(1, 10000), (2, 10000), (3, 10000)]),
    )
    prog = compile_program([layer], NOW)
    assert [it.id_media for it in prog.items] == [1]
    rep = prog.layers[0]
    assert rep.budget_trimmed is True and rep.budget_overflow is False


def test_time_budget_absolute_is_independent_of_other_layers():
    """R13 (décision D1) : le volume gardé d'une couche ne dépend QUE de son budget, jamais du
    contenu des autres couches. Avec l'ancienne formule (part du cycle total), ajouter la couche
    enfant aurait grossi la référence et dé-rogné la couche parente (3 items gardés au lieu de 1).
    """
    parent = _layer(
        node=1, level=0, sched=10,
        constraints=DelegationConstraints(time_budget_sec_per_cycle=15, soft_cut=False),
        items=_items(1, 10, [(1, 10000), (2, 10000), (3, 10000)]),
    )
    parent_alone = [it.id_media for it in compile_program([parent], NOW).items if it.id_node == 1]

    child = _layer(
        node=2, level=1, sched=20,
        constraints=DelegationConstraints(),  # aucun budget, gros contenu
        items=_items(50, 100, [(50, 60000), (51, 60000)]),
    )
    parent_with_child = [
        it.id_media for it in compile_program([parent, child], NOW).items if it.id_node == 1
    ]

    assert parent_alone == parent_with_child == [1]


def test_time_window_excludes_layer_outside():
    # fenêtre 14:00–18:00 un lundi midi (12:00) → couche exclue.
    tw = TimeRule(rule_type="weekly", days_of_week=[0], time_start=time(14, 0), time_end=time(18, 0))
    layer = _layer(node=1, level=0, sched=10,
                   constraints=DelegationConstraints(time_window=tw),
                   items=_items(1, 10, [(1, 1000)]))
    prog = compile_program([layer], NOW)
    assert prog.items == []
    assert prog.layers[0].status == "outside_time_window"


def test_parse_constraints_aggregates_rules():
    class _R:
        def __init__(self, rule_type, params, soft_cut=True, is_active=True):
            self.rule_type, self.params, self.soft_cut, self.is_active = rule_type, params, soft_cut, is_active

    rules = [
        _R("preemptive", {}),
        _R("item_count", {"max_per_cycle": 3}),
        _R("time_budget", {"sec_per_cycle": 600}, soft_cut=False),
        _R("time_window", {"start": "09:00", "end": "18:00", "days": [1, 2, 3]}),
        _R("item_count", {"max_per_cycle": 99}, is_active=False),  # inactive → ignorée
        _R("priority_band", {"min": 50, "max": 79}),  # type retiré (D3) → ignoré sans effet
    ]
    c = parse_constraints(rules)
    assert c.preemptive is True
    assert c.item_count == 3  # la règle inactive n'écrase pas
    assert c.time_budget_sec_per_cycle == 600 and c.soft_cut is False
    assert c.time_window is not None and c.time_window.time_start == time(9, 0)


def test_node_budget_status_planned():
    items = _items(1, 10, [(1, 10000), (2, 10000), (3, 10000)])
    c = DelegationConstraints(time_budget_sec_per_cycle=25, item_count=2)
    st = node_budget_status(c, items)
    assert st["items_used"] == 2 and st["items_budget"] == 2
    assert st["used_sec"] == 20.0  # cap item_count=2 → 20s
    assert st["budget_sec"] == 25 and st["remaining_sec"] == 5.0


# ── Fixtures endpoints ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="GovEng", org_slug=f"goveng-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"goveng-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_GOVE_{uid}", label="GovE", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("governance", "read"), ("governance", "edit"), ("governance", "delegate"),
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
    # N1 (2026-07-27) : créer des nœuds RACINE et nommer les premiers admins sont des actes
    # d'org-admin. Ces tests exercent le MOTEUR (compilation), pas le contrôle d'accès —
    # le user de la fixture devient donc org-admin (token forgé : login org-admin = 2FA).
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    oa = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=oa.id_role))
    await db_session.commit()

    return create_access_token(user.id_user)


async def _playlist_with_item(
    db: AsyncSession, id_org: int, dur_ms: int
) -> int:
    """Crée média + playlist + 1 item ; retourne id_playlist."""
    uid = uuid.uuid4().hex[:6]
    media = CmsMedia(
        id_org=id_org, media_name=f"vid-{uid}", media_type="video",
        storage_key=f"k/{uid}", checksum_sha256=uid * 4, duration_ms=dur_ms,
    )
    db.add(media)
    await db.flush()
    pl = CmsPlaylist(id_org=id_org, playlist_name=f"pl-{uid}")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media, sort_order=0))
    await db.flush()
    return pl.id_playlist


async def _governed_schedule(
    db: AsyncSession, id_org: int, id_node: int, id_playlist: int, prio: int
) -> int:
    s = CmsSchedule(
        id_org=id_org, schedule_name=f"sch-{uuid.uuid4().hex[:6]}", schedule_kind="content",
        id_playlist=id_playlist, id_governance_node=id_node, priority=prio,
    )
    db.add(s)
    await db.flush()
    db.add(CmsScheduleRule(id_schedule=s.id_schedule, rule_type="always"))
    await db.flush()
    return s.id_schedule


# ── Tests endpoints ───────────────────────────────────────────────────────────

async def test_compiled_schedule_layers_national_then_local(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}

    # Arbre national → local
    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "National"}, headers=headers,
    )).json()
    local = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Magasin", "parent_id": national["id_node"]}, headers=headers,
    )).json()

    # Player rattaché au nœud local
    player = CmsPlayer(id_org=org.id_org, player_name="P-gov")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=local["id_node"], target_type="player", target_id=player.id_player
    ))

    pl_nat = await _playlist_with_item(db_session, org.id_org, 5000)
    pl_loc = await _playlist_with_item(db_session, org.id_org, 3000)
    await _governed_schedule(db_session, org.id_org, national["id_node"], pl_nat, prio=80)
    await _governed_schedule(db_session, org.id_org, local["id_node"], pl_loc, prio=10)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/players/{player.id_player}/compiled-schedule", headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 2 couches, items concaténés national (5s) puis local (3s)
    assert len(data["items"]) == 2
    assert data["items"][0]["id_node"] == national["id_node"]
    assert data["items"][1]["id_node"] == local["id_node"]
    assert data["cycle_duration_ms"] == 8000
    assert {l["status"] for l in data["layers"]} == {"active"}


async def test_compiled_schedule_empty_for_ungoverned_player(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    player = CmsPlayer(id_org=org.id_org, player_name="P-free")
    db_session.add(player)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/players/{player.id_player}/compiled-schedule", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == [] and data["layers"] == []


async def test_compiled_schedule_cross_tenant_404(
    client: AsyncClient, auth_token: str, db_session: AsyncSession
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    # Player d'une AUTRE org
    other = CmsOrganization(org_name="Other", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    p = CmsPlayer(id_org=other.id_org, player_name="P-other")
    db_session.add(p)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/players/{p.id_player}/compiled-schedule", headers=headers
    )
    assert resp.status_code == 404


async def test_budget_status_planned(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Budgeted"}, headers=headers,
    )).json()

    pl = await _playlist_with_item(db_session, org.id_org, 4000)  # 1 item de 4s
    await _governed_schedule(db_session, org.id_org, node["id_node"], pl, prio=0)
    db_session.add(CmsDelegationRule(
        id_node=node["id_node"], rule_type="time_budget", params={"sec_per_cycle": 600}
    ))
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/governance/nodes/{node['id_node']}/budget-status", headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id_node"] == node["id_node"]
    assert data["used_sec"] == 4.0
    assert data["budget_sec"] == 600 and data["remaining_sec"] == 596.0


# ── Tests lot 2b — branchement dans le sync live (_resolve_sync_payload) ──────

async def test_sync_payload_uses_compiled_program_for_governed_player(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization,
    monkeypatch,
) -> None:
    """Un player gouverné reçoit le programme COMPILÉ (couches national→local) via le sync live."""
    import app.api.v1.endpoints.ws as ws
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    headers = {"Authorization": f"Bearer {auth_token}"}

    national = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "National"}, headers=headers,
    )).json()
    local = (await client.post(
        "/api/v1/governance/nodes",
        json={"node_name": "Magasin", "parent_id": national["id_node"]}, headers=headers,
    )).json()

    player = CmsPlayer(id_org=org.id_org, player_name="P-gov-live", player_os="linux")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=local["id_node"], target_type="player", target_id=player.id_player
    ))
    pl_nat = await _playlist_with_item(db_session, org.id_org, 5000)
    pl_loc = await _playlist_with_item(db_session, org.id_org, 3000)
    await _governed_schedule(db_session, org.id_org, national["id_node"], pl_nat, prio=80)
    await _governed_schedule(db_session, org.id_org, local["id_node"], pl_loc, prio=10)
    await db_session.commit()

    payload = await ws._resolve_sync_payload(db_session, player.id_player)
    assert payload.get("id_governance") is True
    assert payload["id_playlist"] is None and payload["id_schedule"] is None
    # 2 items, national (5s) puis local (3s)
    assert [it["duration_ms"] for it in payload["items"]] == [5000, 3000]


async def test_governed_schedule_ignores_classic_targets(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization,
    monkeypatch,
) -> None:
    """D2 : un programme rattaché à un nœud NE diffuse PAS par ses cibles classiques.

    Player non assigné au nœud + cible classique sur ce player → la gouvernance ne produit
    rien (player hors nœud) ET le chemin classique exclut le programme gouverné → payload vide.
    Avant le fix, le chemin classique rejouait la playlist SANS aucune règle de délégation.
    """
    import app.api.v1.endpoints.ws as ws
    from app.models.schedule import CmsScheduleTarget
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    headers = {"Authorization": f"Bearer {auth_token}"}

    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "NodeD2"}, headers=headers,
    )).json()
    player = CmsPlayer(id_org=org.id_org, player_name="P-d2", player_os="linux")
    db_session.add(player)
    await db_session.flush()
    pl = await _playlist_with_item(db_session, org.id_org, 4000)
    sid = await _governed_schedule(db_session, org.id_org, node["id_node"], pl, prio=0)
    db_session.add(CmsScheduleTarget(
        id_schedule=sid, target_type="player", target_id=player.id_player,
    ))
    await db_session.commit()

    payload = await ws._resolve_sync_payload(db_session, player.id_player)
    assert "id_governance" not in payload   # player hors nœud → aucune couche gouvernée
    assert payload["items"] == []           # et le chemin classique ne le rejoue pas


async def test_sync_payload_ungoverned_player_unaffected(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization,
    monkeypatch,
) -> None:
    """Player non assigné à un nœud → pas de couche gouvernée → payload empty (chemin legacy)."""
    import app.api.v1.endpoints.ws as ws
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")

    player = CmsPlayer(id_org=org.id_org, player_name="P-free-live", player_os="linux")
    db_session.add(player)
    await db_session.commit()

    payload = await ws._resolve_sync_payload(db_session, player.id_player)
    assert "id_governance" not in payload
    assert payload["items"] == []


async def test_governance_rule_change_pushes_force_sync(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization,
    monkeypatch,
) -> None:
    """R12 : muter une règle pousse player:force_sync aux écrans du nœud (recompilation live)."""
    import app.api.v1.endpoints.governance as gov
    calls: list[set[int]] = []

    async def _capture(pids):
        calls.append(set(pids))

    monkeypatch.setattr(gov, "_push_force_sync", _capture)
    headers = {"Authorization": f"Bearer {auth_token}"}

    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "N-r12"}, headers=headers,
    )).json()
    # Écrire une règle exige d'administrer le nœud ET que la DÉLÉGATION soit accordée
    # (décision Ed 2026-07-26) — cf. test_governance.py::test_rules_delegation_is_monotone.
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    await client.post(f"/api/v1/governance/nodes/{node['id_node']}/admins",
                      json={"id_user": me["id_user"]}, headers=headers)
    row = (await db_session.execute(
        select(CmsGovernanceNode).where(CmsGovernanceNode.id_node == node["id_node"])
    )).scalar_one()
    row.rules_locked = {f: False for f in ("item_count", "time_budget", "time_window", "preemptive")}
    await db_session.commit()
    player = CmsPlayer(id_org=org.id_org, player_name="P-r12")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player,
    ))
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/governance/nodes/{node['id_node']}/rules",
        json={"rule_type": "time_budget", "params": {"sec_per_cycle": 60}}, headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert calls and player.id_player in calls[-1]


# ── R10 : « aucune couche active » doit dire LAQUELLE des cinq causes ─────────
# Vécu le 2026-07-25 : tout était en place SAUF le rattachement du programme au nœud,
# et le message ne le disait pas. On remonte la chaîne maillon par maillon.

async def test_compiled_schedule_names_the_real_cause(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    url = lambda p: f"/api/v1/players/{p}/compiled-schedule"  # noqa: E731

    # 1. Player hors de toute gouvernance.
    player = CmsPlayer(id_org=org.id_org, player_name="P-diag")
    db_session.add(player)
    await db_session.flush()
    await db_session.commit()
    data = (await client.get(url(player.id_player), headers=headers)).json()
    assert data["layers"] == [] and data["empty_reason"] == "no_node"

    # 2. Rattaché à un nœud, mais aucun programme sur ce nœud.
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Diag"}, headers=headers)).json()
    db_session.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player))
    await db_session.commit()
    data = (await client.get(url(player.id_player), headers=headers)).json()
    assert data["empty_reason"] == "no_schedule"

    # 3. Programme rattaché mais DÉSACTIVÉ.
    sched = CmsSchedule(
        id_org=org.id_org, schedule_name="Diag SC", schedule_kind="content",
        id_governance_node=node["id_node"], is_active=False,
    )
    db_session.add(sched)
    await db_session.commit()
    data = (await client.get(url(player.id_player), headers=headers)).json()
    assert data["empty_reason"] == "schedule_inactive"
    assert data["empty_detail"] == "Diag SC"

    # 4. Activé, mais sans playlist.
    sched.is_active = True
    await db_session.commit()
    data = (await client.get(url(player.id_player), headers=headers)).json()
    assert data["empty_reason"] == "no_playlist"

    # 5. Avec playlist, mais AUCUNE règle → un programme sans règle n'est jamais actif.
    sched.id_playlist = await _playlist_with_item(db_session, org.id_org, 4000)
    await db_session.commit()
    data = (await client.get(url(player.id_player), headers=headers)).json()
    assert data["empty_reason"] == "no_rule"

    # 6. Règle posée mais hors fenêtre à l'instant demandé (créneau 02:00–03:00, on regarde à midi).
    #    ⚠️ `date_range` = type RÉEL du moteur. Un rule_type inventé n'est jamais actif : le test
    #    passerait alors pour la mauvaise raison (constaté en écrivant ce test avec « daily »).
    db_session.add(CmsScheduleRule(
        id_schedule=sched.id_schedule, rule_type="date_range",
        time_start=time(2, 0), time_end=time(3, 0),
    ))
    await db_session.commit()
    data = (await client.get(
        url(player.id_player) + "?at=2026-07-25T12:00", headers=headers)).json()
    assert data["empty_reason"] == "outside_window"
    assert data["empty_detail"] == "Diag SC"

    # 7. Dans la fenêtre : la couche apparaît et le diagnostic disparaît.
    data = (await client.get(
        url(player.id_player) + "?at=2026-07-25T02:30", headers=headers)).json()
    assert len(data["layers"]) == 1 and data["layers"][0]["status"] == "active"
    assert data.get("empty_reason") is None


# ── Clé de synchro LAN d'un programme gouverné (retour Ed ①, 2026-07-26) ──────
# Un payload gouverné n'a ni id_playlist ni id_event ; la clé de synchro du renderer valait
# donc null, et le leader LAN n'émettait AUCUN `sync_play` ⇒ aucune correction UDP, les
# écrans ne tenaient que par leur wall-clock et dérivaient (constat d'Ed sur RPi + NUC).

def _report(id_node: int, id_schedule: int, status: str = "active", item_count: int = 1):
    from app.services.governance_engine import LayerReport
    return LayerReport(
        id_node=id_node, node_name=f"n{id_node}", node_level=0, id_schedule=id_schedule,
        priority=0, status=status, item_count=item_count,
    )


def _program(layers):
    from app.services.governance_engine import CompiledProgram
    return CompiledProgram(items=[], layers=layers, cycle_duration_ms=0)


def test_governance_sync_key_is_deterministic_and_int32_safe():
    from app.api.v1.endpoints.ws import _governance_sync_key

    prog = _program([_report(3, 7), _report(1, 4)])
    key = _governance_sync_key(prog)

    # Déterministe : même programme → même clé (deux players, deux requêtes, deux workers).
    assert _governance_sync_key(_program([_report(3, 7), _report(1, 4)])) == key
    # …indépendamment de l'ordre des couches.
    assert _governance_sync_key(_program([_report(1, 4), _report(3, 7)])) == key
    # Plage réservée : jamais un id_playlist réel (positif) ni un -id_event (petite magnitude).
    assert -2_000_000_000 <= key <= -1_000_000_000
    # Tient dans un entier 32 bits signé — la chaîne LAN traverse l'autorun BrightScript.
    assert key >= -2_147_483_648
    # Un programme différent → clé différente (sinon deux groupes se synchroniseraient entre eux).
    assert _governance_sync_key(_program([_report(3, 7), _report(2, 4)])) != key
    # Les couches inactives ne comptent pas : elles ne produisent aucun item diffusé.
    assert _governance_sync_key(_program([
        _report(3, 7), _report(1, 4), _report(9, 9, status="preempted", item_count=0),
    ])) == key


async def test_governed_payload_carries_a_shared_sync_key(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Deux players du même nœud reçoivent la MÊME clé ; un player d'un autre nœud non."""
    from app.api.v1.endpoints.ws import _resolve_sync_payload

    headers = {"Authorization": f"Bearer {auth_token}"}
    node_a = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Site A"}, headers=headers)).json()
    node_b = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Site B"}, headers=headers)).json()

    players = []
    for name, node in (("P-a1", node_a), ("P-a2", node_a), ("P-b1", node_b)):
        p = CmsPlayer(id_org=org.id_org, player_name=name)
        db_session.add(p)
        await db_session.flush()
        db_session.add(CmsGovernanceAssignment(
            id_node=node["id_node"], target_type="player", target_id=p.id_player))
        players.append(p)

    for node in (node_a, node_b):
        pl = await _playlist_with_item(db_session, org.id_org, 5000)
        await _governed_schedule(db_session, org.id_org, node["id_node"], pl, prio=10)
    await db_session.commit()

    pa1, pa2, pb1 = [
        await _resolve_sync_payload(db_session, p.id_player) for p in players
    ]

    # La couche gouvernée est bien servie…
    assert pa1["id_governance"] is True
    # …avec une clé de synchro exploitable par le leader LAN.
    assert pa1["sync_key"] is not None
    assert -2_000_000_000 <= pa1["sync_key"] <= -1_000_000_000
    # ⛔ id_playlist reste NUL : il alimente le Proof of Play, qui est facturable.
    assert pa1["id_playlist"] is None

    # Même nœud, même programme compilé → même groupe de synchro.
    assert pa1["sync_key"] == pa2["sync_key"]
    # Nœud différent → programme différent → surtout pas le même groupe.
    assert pb1["sync_key"] != pa1["sync_key"]


# ── Relais de deux programmes gouvernés dans le temps (question d'Ed, 2026-07-26) ──
# « Un programme du 5 avril au 31 juillet, un autre à partir du 1er août sans date de fin :
#   la bascule se fait-elle toute seule, chacun avec SA playlist ? » — prouvé ici plutôt
#   qu'affirmé. Les bornes sont INCLUSIVES des deux côtés et `date_to` NULL = sans fin.

async def test_two_governed_programs_hand_over_on_their_dates(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    from datetime import date as date_cls

    from app.api.v1.endpoints.governance import gather_layers
    from app.services.governance_engine import compile_program

    headers = {"Authorization": f"Bearer {auth_token}"}
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Enseigne"}, headers=headers)).json()

    player = CmsPlayer(id_org=org.id_org, player_name="P-relais")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player))

    # Deux playlists distinctes, une par programme.
    pl_printemps = await _playlist_with_item(db_session, org.id_org, 5000)
    pl_rentree = await _playlist_with_item(db_session, org.id_org, 7000)

    async def _dated_schedule(id_playlist: int, dfrom: date_cls, dto: date_cls | None) -> int:
        s = CmsSchedule(
            id_org=org.id_org, schedule_name=f"prog-{uuid.uuid4().hex[:6]}",
            schedule_kind="content", id_playlist=id_playlist,
            id_governance_node=node["id_node"], priority=10,
        )
        db_session.add(s)
        await db_session.flush()
        db_session.add(CmsScheduleRule(
            id_schedule=s.id_schedule, rule_type="date_range", date_from=dfrom, date_to=dto))
        await db_session.flush()
        return s.id_schedule

    sched_a = await _dated_schedule(pl_printemps, date_cls(2026, 4, 5), date_cls(2026, 7, 31))
    sched_b = await _dated_schedule(pl_rentree, date_cls(2026, 8, 1), None)
    await db_session.commit()

    async def _layers_at(moment: datetime) -> set[int]:
        layers = await gather_layers(db_session, org.id_org, player.id_player, moment)
        program = compile_program(layers, moment)
        return {i.id_schedule for i in program.items}

    # Avant le 5 avril : aucun des deux.
    assert await _layers_at(datetime(2026, 4, 4, 23, 59)) == set()
    # Premier jour du programme A (borne de début INCLUSIVE, dès minuit).
    assert await _layers_at(datetime(2026, 4, 5, 0, 0)) == {sched_a}
    # En plein milieu.
    assert await _layers_at(datetime(2026, 6, 15, 12, 0)) == {sched_a}
    # DERNIER jour de A : actif toute la journée (borne de fin INCLUSIVE).
    assert await _layers_at(datetime(2026, 7, 31, 23, 59, 59)) == {sched_a}
    # Bascule à minuit : B seul, sans trou ni recouvrement.
    assert await _layers_at(datetime(2026, 8, 1, 0, 0)) == {sched_b}
    # Sans date de fin, B reste actif indéfiniment.
    assert await _layers_at(datetime(2027, 3, 9, 8, 0)) == {sched_b}
    assert await _layers_at(datetime(2030, 1, 1, 0, 0)) == {sched_b}

    # Et chacun diffuse bien SA playlist (durées distinctes = preuve du contenu servi).
    layers_a = await gather_layers(db_session, org.id_org, player.id_player,
                                   datetime(2026, 6, 15, 12, 0))
    layers_b = await gather_layers(db_session, org.id_org, player.id_player,
                                   datetime(2026, 9, 1, 12, 0))
    assert compile_program(layers_a, datetime(2026, 6, 15, 12, 0)).cycle_duration_ms == 5000
    assert compile_program(layers_b, datetime(2026, 9, 1, 12, 0)).cycle_duration_ms == 7000


async def test_overlapping_governed_programs_stack_instead_of_replacing(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """⚠️ Piège de modèle : deux programmes gouvernés qui se CHEVAUCHENT s'ADDITIONNENT
    (couches concaténées), ils ne se remplacent pas. Une date de fin posée au 1er août au
    lieu du 31 juillet ferait donc jouer les deux ce jour-là."""
    from datetime import date as date_cls

    from app.api.v1.endpoints.governance import gather_layers
    from app.services.governance_engine import compile_program

    headers = {"Authorization": f"Bearer {auth_token}"}
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Chevauchement"}, headers=headers)).json()
    player = CmsPlayer(id_org=org.id_org, player_name="P-overlap")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player))

    for dfrom, dto, dur in ((date_cls(2026, 4, 5), date_cls(2026, 8, 1), 5000),
                            (date_cls(2026, 8, 1), None, 7000)):
        pl = await _playlist_with_item(db_session, org.id_org, dur)
        s = CmsSchedule(
            id_org=org.id_org, schedule_name=f"ov-{uuid.uuid4().hex[:6]}",
            schedule_kind="content", id_playlist=pl,
            id_governance_node=node["id_node"], priority=10,
        )
        db_session.add(s)
        await db_session.flush()
        db_session.add(CmsScheduleRule(
            id_schedule=s.id_schedule, rule_type="date_range", date_from=dfrom, date_to=dto))
    await db_session.commit()

    moment = datetime(2026, 8, 1, 12, 0)
    program = compile_program(
        await gather_layers(db_session, org.id_org, player.id_player, moment), moment)
    # Le 1er août, les DEUX jouent : cycle = 5 s + 7 s.
    assert len({i.id_schedule for i in program.items}) == 2
    assert program.cycle_duration_ms == 12_000


# ── Rotation et sous-playlists SOUS GOUVERNANCE (retour Ed ②, 2026-07-25) ─────
# `_layer_items` lisait `cms_playlist_items` BRUT : aucune rotation, et tout item
# `sub_playlist` était sauté en silence (son id_media est NULL). Résultat : l'essai
# d'Ed (« 3 vidéos en shuffle, 1 par tour ») ne pouvait pas marcher, et une playlist
# gouvernée contenant une sous-playlist perdait ces contenus sans aucun message.

async def _sub_playlist(
    db: AsyncSession, org, names: list[str], *, mode: str = "all",
    k: int = 1, no_ads_inside: bool = False,
) -> CmsPlaylist:
    child = CmsPlaylist(id_org=org.id_org, playlist_name=f"child-{uuid.uuid4().hex[:6]}",
                        rotation_mode=mode, items_per_turn=k, no_ads_inside=no_ads_inside)
    db.add(child)
    await db.flush()
    for i, name in enumerate(names):
        m = CmsMedia(id_org=org.id_org, media_name=name, media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     duration_ms=10_000)
        db.add(m)
        await db.flush()
        db.add(CmsPlaylistItem(id_playlist=child.id_playlist, id_media=m.id_media,
                               sort_order=i, duration_ms=10_000))
    await db.flush()
    return child


async def _governed_player_with_playlist(
    client: AsyncClient, headers: dict, db: AsyncSession, org, id_playlist: int
) -> CmsPlayer:
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": f"N-{uuid.uuid4().hex[:5]}"},
        headers=headers)).json()
    player = CmsPlayer(id_org=org.id_org, player_name=f"P-{uuid.uuid4().hex[:5]}")
    db.add(player)
    await db.flush()
    db.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player))
    await _governed_schedule(db, org.id_org, node["id_node"], id_playlist, prio=10)
    await db.commit()
    return player


async def _governed_items(db: AsyncSession, org, player: CmsPlayer) -> list:
    from app.api.v1.endpoints.governance import gather_layers
    from app.services.governance_engine import compile_program

    now = datetime(2026, 7, 26, 12, 0)
    return compile_program(
        await gather_layers(db, org.id_org, player.id_player, now), now).items


async def test_governed_layer_applies_sub_playlist_rotation(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Le scénario d'Ed : 3 vidéos dans une sous-playlist, 1 par tour."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    child = await _sub_playlist(db_session, org, ["v1", "v2", "v3"],
                                mode="one_sequential", k=1)
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent gouverné")
    db_session.add(parent)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(
        id_playlist=parent.id_playlist, id_media=None, item_type="sub_playlist",
        id_child_playlist=child.id_playlist, sort_order=0))
    player = await _governed_player_with_playlist(
        client, headers, db_session, org, parent.id_playlist)

    items = await _governed_items(db_session, org, player)
    # Le cycle est DÉROULÉ par le serveur : 3 tours de 1 item (N=3, K=1).
    assert [i.media_name for i in items] == ["v1", "v2", "v3"]


async def test_governed_layer_rotation_two_per_turn(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """N=5, K=2 → 5 tours de 2 items, chacun diffusé exactement 2 fois par cycle."""
    from collections import Counter

    headers = {"Authorization": f"Bearer {auth_token}"}
    child = await _sub_playlist(db_session, org, ["a", "b", "c", "d", "e"],
                                mode="one_sequential", k=2)
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent K2")
    db_session.add(parent)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(
        id_playlist=parent.id_playlist, id_media=None, item_type="sub_playlist",
        id_child_playlist=child.id_playlist, sort_order=0))
    player = await _governed_player_with_playlist(
        client, headers, db_session, org, parent.id_playlist)

    names = [i.media_name for i in await _governed_items(db_session, org, player)]
    assert names == ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"]
    assert all(c == 2 for c in Counter(names).values())


async def test_governed_layer_keeps_sub_playlist_content(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Sans rotation (mode « tous les items »), la sous-playlist était PERDUE en silence :
    seul le média direct survivait. Elle doit être inlinée à sa place."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    child = await _sub_playlist(db_session, org, ["promo1", "promo2"], mode="all")
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent inline")
    db_session.add(parent)
    await db_session.flush()
    home = CmsMedia(id_org=org.id_org, media_name="home", media_type="video",
                    storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                    duration_ms=30_000)
    db_session.add(home)
    await db_session.flush()
    db_session.add_all([
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    player = await _governed_player_with_playlist(
        client, headers, db_session, org, parent.id_playlist)

    items = await _governed_items(db_session, org, player)
    assert [i.media_name for i in items] == ["home", "promo1", "promo2"]


async def test_governed_layer_marks_protected_block(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """« Pas de publicité entre les contenus » doit aussi tenir sous gouvernance : tout le
    bloc sauf son 1er item porte `no_ad_before` (frontière interdite à l'injection)."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    child = await _sub_playlist(db_session, org, ["p1", "p2", "p3"],
                                mode="all", no_ads_inside=True)
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent protege")
    db_session.add(parent)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(
        id_playlist=parent.id_playlist, id_media=None, item_type="sub_playlist",
        id_child_playlist=child.id_playlist, sort_order=0))
    player = await _governed_player_with_playlist(
        client, headers, db_session, org, parent.id_playlist)

    items = await _governed_items(db_session, org, player)
    assert [i.no_ad_before for i in items] == [False, True, True]


async def test_compiled_schedule_exposes_content_rates(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """L'écran de configuration doit MONTRER le taux de passage (demande d'Ed 2026-07-26) :
    combien de fois par cycle, à quel intervalle, combien par jour."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    node = (await client.post(
        "/api/v1/governance/nodes", json={"node_name": "Taux"}, headers=headers)).json()
    player = CmsPlayer(id_org=org.id_org, player_name="P-taux")
    db_session.add(player)
    await db_session.flush()
    db_session.add(CmsGovernanceAssignment(
        id_node=node["id_node"], target_type="player", target_id=player.id_player))

    # 3 contenus de 10 s, 1 par tour → 3 tours, chacun 1 fois par cycle de 30 s.
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL-taux")
    db_session.add(pl)
    await db_session.flush()
    for i in range(3):
        m = CmsMedia(id_org=org.id_org, media_name=f"clip{i}", media_type="video",
                     storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                     duration_ms=10_000)
        db_session.add(m)
        await db_session.flush()
        db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media,
                                       sort_order=i, duration_ms=10_000))
    await _governed_schedule(db_session, org.id_org, node["id_node"], pl.id_playlist, prio=10)
    db_session.add(CmsDelegationRule(
        id_node=node["id_node"], rule_type="item_count", params={"max_per_cycle": 1}))
    await db_session.commit()

    data = (await client.get(
        f"/api/v1/players/{player.id_player}/compiled-schedule", headers=headers)).json()
    assert data["turns"] == 3
    assert data["truncated"] is False
    rates = {c["media_name"]: c for c in data["contents"]}
    assert set(rates) == {"clip0", "clip1", "clip2"}
    for c in rates.values():
        assert c["plays_per_cycle"] == 1
        assert c["interval_ms"] == 30_000          # cycle de 30 s / 1 passage
        assert c["airtime_pct"] == 33.3
    # Sans horaires déclarés on annonce 24 h — et on le dit, plutôt que de laisser croire
    # à une mesure : 24 h / 30 s = 2880 passages par jour.
    assert data["open_hours_per_day"] == 24.0
    assert rates["clip0"]["plays_per_day"] == 2880.0
