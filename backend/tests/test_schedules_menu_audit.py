"""Audit menu ⑧ Programmes/Calendrier (2026-07-31) — sondes de sécurité et de cohérence.

Chaque test affirme le comportement ATTENDU. Au moment de l'audit, les rouges sont la
MESURE des défauts (rouge-avant prouvé) ; après correctifs, le fichier reste comme filet.

Constats visés :
  · validation d'existence/org des CIBLES à la création et au remplacement (comme les
    événements depuis l'audit du 29/07 — ici, 201 sur un écran inexistant ou étranger) ;
  · validation de la PLAYLIST à l'update (PUT id_playlist n'était soumis à AUCUN contrôle :
    ni existence, ni is_deleted, ni org) et de l'org à la création ;
  · le DÉTAIL par identifiant contourne le filtre de gouvernance de la liste (G4) ;
  · /players/{id}/current-schedule et /simulate-day ignorent le périmètre N8 ET l'org
    de l'appelant (simulate-day travaille avec l'org DU PLAYER) ;
  · aucune trace d'audit sur les 4 mutations ; updated_at figé (16/16 en prod).
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.governance import (
    CmsGovernanceAssignment,
    CmsGovernanceNode,
    CmsGovernanceNodeAdmin,
)
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.schedule import CmsSchedule
from app.models.user import CmsUser

_PERMS = [
    ("schedules", "create"), ("schedules", "read"),
    ("schedules", "edit"), ("schedules", "delete"),
    ("players", "read"),
]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SchedAudit", org_slug=f"sca-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SchedAuditB", org_slug=f"scb-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(
    db: AsyncSession, org: CmsOrganization, *, role_key: str | None = None
) -> CmsUser:
    """Utilisateur porteur des permissions schedules:* + players:read.

    `role_key` permet de donner un rôle SYSTÈME précis (ex. CMS_SITE_PROGRAMMER, dont la
    clé porte la sémantique de périmètre G4) au lieu d'un rôle custom jetable.
    """
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"sca-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db.add(user)
    await db.flush()
    key = role_key or f"CMS_SCA_{uid}"
    await db.execute(
        pg_insert(CmsRole)
        .values(role_key=key, label=key, is_system=role_key is not None, is_active=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalar_one()
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
        await db.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing()
        )
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def playlist(db_session: AsyncSession, org: CmsOrganization) -> CmsPlaylist:
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL-A")
    db_session.add(pl)
    await db_session.commit()
    await db_session.refresh(pl)
    return pl


@pytest_asyncio.fixture
async def playlist_b(db_session: AsyncSession, org_b: CmsOrganization) -> CmsPlaylist:
    pl = CmsPlaylist(id_org=org_b.id_org, playlist_name="PL-B")
    db_session.add(pl)
    await db_session.commit()
    await db_session.refresh(pl)
    return pl


def _payload(playlist_id: int, **overrides) -> dict:
    base = {
        "schedule_name": "Sonde", "schedule_kind": "content",
        "id_playlist": playlist_id, "priority": 10,
        "rules": [{"rule_type": "always"}], "targets": [],
    }
    base.update(overrides)
    return base


# ── Validation des cibles (création + remplacement) ───────────────────────────

@pytest.mark.asyncio
async def test_create_rejects_unknown_target(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """Un écran inexistant dans une cible doit être refusé, pas enregistré en silence."""
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user), json=_payload(
        playlist.id_playlist,
        targets=[{"target_type": "player", "target_id": 99999999}],
    ))
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_create_rejects_cross_org_target(
    client: AsyncClient, db_session: AsyncSession, org, org_b, playlist
) -> None:
    """Cibler le site d'une AUTRE organisation doit répondre 404/422, jamais 201."""
    site_b = CmsSite(id_org=org_b.id_org, site_name="SiteB")
    db_session.add(site_b)
    await db_session.commit()
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user), json=_payload(
        playlist.id_playlist,
        targets=[{"target_type": "site", "target_id": site_b.id_site}],
    ))
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_replace_targets_rejects_unknown_target(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201, r.text
    sid = r.json()["id_schedule"]
    r2 = await client.put(f"/api/v1/schedules/{sid}/targets", headers=_h(user),
                          json=[{"target_type": "player_group", "target_id": 99999999}])
    assert r2.status_code in (404, 422), r2.text


# ── Validation de la playlist ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_rejects_cross_org_playlist(
    client: AsyncClient, db_session: AsyncSession, org, playlist_b
) -> None:
    """La playlist d'une autre org est invisible : la programmer doit répondre 404."""
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist_b.id_playlist))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_update_rejects_unknown_playlist(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """PUT id_playlist ne subissait AUCUN contrôle (ni existence, ni is_deleted, ni org)."""
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201, r.text
    sid = r.json()["id_schedule"]
    r2 = await client.put(f"/api/v1/schedules/{sid}", headers=_h(user),
                          json={"id_playlist": 99999999})
    assert r2.status_code == 404, r2.text


@pytest.mark.asyncio
async def test_update_rejects_cross_org_playlist(
    client: AsyncClient, db_session: AsyncSession, org, playlist, playlist_b
) -> None:
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201, r.text
    sid = r.json()["id_schedule"]
    r2 = await client.put(f"/api/v1/schedules/{sid}", headers=_h(user),
                          json={"id_playlist": playlist_b.id_playlist})
    assert r2.status_code == 404, r2.text


@pytest.mark.asyncio
async def test_update_rejects_deleted_playlist(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """Une playlist SUPPRIMÉE acceptée à l'update = écran qui casse en silence plus tard."""
    user = await _mk_user(db_session, org)
    deleted = CmsPlaylist(id_org=org.id_org, playlist_name="PL-del", is_deleted=True)
    db_session.add(deleted)
    await db_session.commit()
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201, r.text
    sid = r.json()["id_schedule"]
    r2 = await client.put(f"/api/v1/schedules/{sid}", headers=_h(user),
                          json={"id_playlist": deleted.id_playlist})
    assert r2.status_code == 404, r2.text


# ── Détail vs filtre de gouvernance (G4) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_detail_hidden_for_governance_scoped_sibling(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """Le détail par identifiant ne doit pas montrer ce que la LISTE cache (nœud frère)."""
    root_a = CmsGovernanceNode(id_org=org.id_org, node_name="A", node_level=0,
                               node_type="national", requires_approval=False, path="")
    root_b = CmsGovernanceNode(id_org=org.id_org, node_name="B", node_level=0,
                               node_type="national", requires_approval=False, path="")
    db_session.add_all([root_a, root_b])
    await db_session.flush()
    root_a.path, root_b.path = str(root_a.id_node), str(root_b.id_node)
    sched_b = CmsSchedule(id_org=org.id_org, schedule_name="Prog-B",
                          schedule_kind="content", id_playlist=playlist.id_playlist,
                          id_governance_node=root_b.id_node)
    db_session.add(sched_b)
    await db_session.flush()
    scoped = await _mk_user(db_session, org, role_key="CMS_SITE_PROGRAMMER")
    db_session.add(CmsGovernanceNodeAdmin(id_node=root_a.id_node, id_user=scoped.id_user))
    await db_session.commit()

    # La liste le cache déjà (G4, livré le 27/07)…
    r_list = await client.get("/api/v1/schedules", headers=_h(scoped))
    assert r_list.status_code == 200
    assert sched_b.id_schedule not in [s["id_schedule"] for s in r_list.json()]
    # …le détail doit répondre 404, pas servir règles + cibles du programme du nœud frère.
    r_detail = await client.get(f"/api/v1/schedules/{sched_b.id_schedule}", headers=_h(scoped))
    assert r_detail.status_code == 404, r_detail.text


# ── Périmètre N8 sur les routes player-centriques du menu ─────────────────────

@pytest_asyncio.fixture
async def gov_scene(db_session: AsyncSession, org):
    """Nœud « Site » administré par un admin ; p_in dans le périmètre, p_out dehors."""
    site_row = CmsSite(id_org=org.id_org, site_name="Mag")
    db_session.add(site_row)
    await db_session.flush()
    p_in = CmsPlayer(id_org=org.id_org, id_site=site_row.id_site, player_name="P-in")
    p_out = CmsPlayer(id_org=org.id_org, id_site=site_row.id_site, player_name="P-out")
    db_session.add_all([p_in, p_out])
    await db_session.flush()
    node = CmsGovernanceNode(id_org=org.id_org, node_name="N", node_level=0,
                             node_type="national", requires_approval=False, path="")
    db_session.add(node)
    await db_session.flush()
    node.path = str(node.id_node)
    db_session.add(CmsGovernanceAssignment(
        id_node=node.id_node, target_type="player", target_id=p_in.id_player))
    admin = await _mk_user(db_session, org)
    db_session.add(CmsGovernanceNodeAdmin(id_node=node.id_node, id_user=admin.id_user))
    await db_session.commit()
    return {"admin": admin, "p_in": p_in, "p_out": p_out}


@pytest.mark.asyncio
async def test_current_schedule_respects_player_scope(
    client: AsyncClient, gov_scene
) -> None:
    """Un admin de nœud ne lit pas la programmation d'un écran HORS périmètre (N8)."""
    ok = await client.get(
        f"/api/v1/players/{gov_scene['p_in'].id_player}/current-schedule",
        headers=_h(gov_scene["admin"]))
    assert ok.status_code == 200
    out = await client.get(
        f"/api/v1/players/{gov_scene['p_out'].id_player}/current-schedule",
        headers=_h(gov_scene["admin"]))
    assert out.status_code == 404, out.text


@pytest.mark.asyncio
async def test_simulate_day_respects_player_scope(
    client: AsyncClient, gov_scene
) -> None:
    ok = await client.post(
        f"/api/v1/players/{gov_scene['p_in'].id_player}/simulate-day",
        headers=_h(gov_scene["admin"]), json={"date": "2026-07-31"})
    assert ok.status_code == 200
    out = await client.post(
        f"/api/v1/players/{gov_scene['p_out'].id_player}/simulate-day",
        headers=_h(gov_scene["admin"]), json={"date": "2026-07-31"})
    assert out.status_code == 404, out.text


@pytest.mark.asyncio
async def test_simulate_day_rejects_cross_org_player(
    client: AsyncClient, db_session: AsyncSession, org, org_b
) -> None:
    """simulate-day travaille avec l'org DU PLAYER : un player étranger doit être 404
    au niveau du CODE (la RLS est un filet, pas la garde — leçon des installs client)."""
    site_b = CmsSite(id_org=org_b.id_org, site_name="SiteB")
    db_session.add(site_b)
    await db_session.flush()
    p_b = CmsPlayer(id_org=org_b.id_org, id_site=site_b.id_site, player_name="P-B")
    db_session.add(p_b)
    await db_session.commit()
    user = await _mk_user(db_session, org)
    r = await client.post(f"/api/v1/players/{p_b.id_player}/simulate-day",
                          headers=_h(user), json={"date": "2026-07-31"})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_current_schedule_rejects_cross_org_player(
    client: AsyncClient, db_session: AsyncSession, org, org_b
) -> None:
    site_b = CmsSite(id_org=org_b.id_org, site_name="SiteB2")
    db_session.add(site_b)
    await db_session.flush()
    p_b = CmsPlayer(id_org=org_b.id_org, id_site=site_b.id_site, player_name="P-B2")
    db_session.add(p_b)
    await db_session.commit()
    user = await _mk_user(db_session, org)
    r = await client.get(f"/api/v1/players/{p_b.id_player}/current-schedule",
                         headers=_h(user))
    assert r.status_code == 404, r.text


# ── Traçabilité + updated_at ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mutations_write_audit(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """create / update / delete d'un programme doivent laisser une trace (prod : les 4
    seules lignes « schedule » du journal viennent de l'ASSISTANT, jamais du menu)."""
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201
    sid = r.json()["id_schedule"]
    await client.put(f"/api/v1/schedules/{sid}", headers=_h(user),
                     json={"schedule_name": "Sonde 2"})
    await client.delete(f"/api/v1/schedules/{sid}", headers=_h(user))
    n = (await db_session.execute(
        select(func.count()).select_from(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == "schedule",
            CmsAuditLog.resource_id == str(sid),
        )
    )).scalar_one()
    assert n >= 3, f"{n} ligne(s) d'audit pour create+update+delete"


@pytest.mark.asyncio
async def test_schedules_activate_permission_is_gone() -> None:
    """`schedules:activate` était seedée (0002) et vérifiée NULLE PART — 3 rôles la
    portaient en prod. Décision d'Ed (31/07) : retrait, patron `templates:publish` (0115).
    On vérifie les DEUX bouts — la migration la supprime, et le code ne la réclame nulle
    part (sinon le retrait l'aurait cassé)."""
    import pathlib
    import re

    migr = pathlib.Path("alembic/versions/0120_drop_schedules_activate.py").read_text(encoding="utf-8")
    assert "DELETE FROM cms_permissions WHERE module = 'schedules' AND operation = 'activate'" in migr

    used = set()
    for f in pathlib.Path("app").rglob("*.py"):
        used |= set(re.findall(r'"schedules"\s*,\s*"(\w+)"', f.read_text(encoding="utf-8")))
    assert "activate" not in used, f"schedules:activate est encore exigé quelque part : {used}"


@pytest.mark.asyncio
async def test_updated_at_moves_on_update(
    client: AsyncClient, db_session: AsyncSession, org, playlist
) -> None:
    """updated_at doit bouger à la modification (prod : 16/16 figés à created_at)."""
    user = await _mk_user(db_session, org)
    r = await client.post("/api/v1/schedules", headers=_h(user),
                          json=_payload(playlist.id_playlist))
    assert r.status_code == 201
    sid = r.json()["id_schedule"]
    r2 = await client.put(f"/api/v1/schedules/{sid}", headers=_h(user),
                          json={"schedule_name": "Renommé"})
    assert r2.status_code == 200
    row = (await db_session.execute(
        select(CmsSchedule).where(CmsSchedule.id_schedule == sid)
    )).scalar_one()
    assert row.updated_at > row.created_at, "updated_at figé à created_at"
