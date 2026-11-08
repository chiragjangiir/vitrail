"""
Cibles HÉTÉROGÈNES des événements (2026-07-30) — « ce site » + « ces 3 écrans » dans UN
seul événement, comme les campagnes.

La forme nouvelle est `{"targets": [{"target_type": t, "target_ids": [...]}, …]}` (union
des entrées) ; la forme héritée `{"target_type": t, "target_ids": [...]}` reste valide —
aucune migration de données. La zone à risque n'est pas la règle mais la COUVERTURE :
`target_config` est lu par le chemin de diffusion, le résolveur de force_sync, sa copie
dans le worker, la garde de gouvernance, le filtre du calendrier, les purges d'orphelins,
l'inventaire, « où est utilisé »… Tout passe désormais par le normaliseur pur partagé
`targeting.event_target_entries` — ces tests vérifient chaque consommateur.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.event import CmsEvent
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.targeting import (
    event_config_targets,
    event_target_config_without,
    event_target_entries,
    event_target_matches,
)


# ── Unitaires PURS (le normaliseur est la seule définition des deux formes) ────────

def test_entries_legacy_form():
    assert event_target_entries({"target_type": "site", "target_ids": [3, 4]}) == [
        ("site", [3, 4])
    ]
    # Alias historique des schedules, normalisé.
    assert event_target_entries({"target_type": "player_group", "target_ids": [9]}) == [
        ("group", [9])
    ]
    assert event_target_entries(None) == [("player", [])]


def test_entries_hetero_form():
    tc = {"targets": [
        {"target_type": "site", "target_ids": [1]},
        {"target_type": "player", "target_ids": [10, 11]},
    ]}
    assert event_target_entries(tc) == [("site", [1]), ("player", [10, 11])]


def test_matcher_matches_any_entry():
    tc = {"targets": [
        {"target_type": "site", "target_ids": [1]},
        {"target_type": "player", "target_ids": [10]},
    ]}
    # Via l'entrée player…
    assert event_target_matches(tc, 10, set(), set(), id_site=None)
    # …via l'entrée site…
    assert event_target_matches(tc, 99, set(), set(), id_site=1)
    # …et personne d'autre.
    assert not event_target_matches(tc, 99, set(), set(), id_site=2)


def test_config_targets_expands_entries():
    tc = {"targets": [
        {"target_type": "site", "target_ids": [1]},
        {"target_type": "player", "target_ids": [10, 11]},
    ]}
    got = {(t.target_type, t.target_id) for t in event_config_targets(tc)}
    assert got == {("site", 1), ("player", 10), ("player", 11)}


def test_config_without_purges_both_forms():
    # Forme héritée : l'id disparaît, le reste est conservé.
    assert event_target_config_without(
        {"target_type": "player", "target_ids": [1, 2]}, "player", 2
    ) == {"target_type": "player", "target_ids": [1]}
    # Forme hétérogène : l'entrée VIDÉE est retirée (une entrée sans id ne vise rien).
    tc = {"targets": [
        {"target_type": "player", "target_ids": [7]},
        {"target_type": "site", "target_ids": [3]},
    ]}
    assert event_target_config_without(tc, "player", 7) == {
        "targets": [{"target_type": "site", "target_ids": [3]}]
    }
    # Rien à changer → None (l'appelant ne réécrit pas la ligne pour rien).
    assert event_target_config_without(tc, "player", 999) is None


def test_worker_resolver_unions_entries():
    """Le worker (psycopg SYNCHRONE) partage le normaliseur : la lecture du JSON n'est
    plus une copie. On stub le curseur — seul le SQL reste propre au worker."""
    from app.workers.event_worker import _resolve_player_ids

    class FakeCursor:
        def __init__(self):
            self.rows: list[tuple[int]] = []

        def execute(self, sql, params):
            if "id_site = ANY" in sql:
                self.rows = [(1,), (2,)]
            elif "id_player = ANY" in sql:
                self.rows = [(3,)]
            else:
                self.rows = []

        def fetchall(self):
            return self.rows

    got = _resolve_player_ids(FakeCursor(), 1, {"targets": [
        {"target_type": "site", "target_ids": [5]},
        {"target_type": "player", "target_ids": [3]},
    ]})
    assert got == [1, 2, 3]


# ── Fixtures API (patron de test_events.py) ────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="HeteroOrg", org_slug=f"het-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org: CmsOrganization) -> dict:
    """Site à 2 écrans + 1 écran hors site + groupe + playlist."""
    site = CmsSite(id_org=org.id_org, site_name="Magasin")
    playlist = CmsPlaylist(id_org=org.id_org, playlist_name="Boucle")
    db_session.add_all([site, playlist])
    await db_session.flush()
    p1 = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Entree")
    p2 = CmsPlayer(id_org=org.id_org, id_site=site.id_site, player_name="Sortie")
    p3 = CmsPlayer(id_org=org.id_org, player_name="Ailleurs")
    grp = CmsPlayerGroup(id_org=org.id_org, group_name="Vitrines")
    db_session.add_all([p1, p2, p3, grp])
    await db_session.flush()
    db_session.add(CmsPlayerGroupMember(id_group=grp.id_group, id_player=p3.id_player))
    await db_session.commit()
    return {"site": site, "playlist": playlist, "p1": p1, "p2": p2, "p3": p3, "grp": grp}


@pytest_asyncio.fixture
async def token(db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"het-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role_key = f"CMS_HET_{uid}"
    await db_session.execute(
        pg_insert(CmsRole).values(role_key=role_key, label="Het", is_system=False,
                                  is_active=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    for module, op in [("events", "read"), ("events", "create"), ("events", "trigger"),
                       ("events", "edit"), ("events", "delete"), ("players", "read")]:
        await db_session.execute(
            pg_insert(CmsPermission).values(module=module, operation=op)
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == op))).scalar_one()
        await db_session.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing())
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"})


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _body(scene, target_config, name="Ev hétéro") -> dict:
    return {
        "event_name": name,
        "event_type": "manual",
        "id_playlist": scene["playlist"].id_playlist,
        "target_config": target_config,
    }


# ── API : création / validation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_event_with_mixed_targets(client: AsyncClient, scene, token) -> None:
    tc = {"targets": [
        {"target_type": "site", "target_ids": [scene["site"].id_site]},
        {"target_type": "player", "target_ids": [scene["p3"].id_player]},
    ]}
    r = await client.post("/api/v1/events", json=_body(scene, tc), headers=_h(token))
    assert r.status_code == 201, r.text
    # Stocké tel quel : c'est le normaliseur qui interprète, pas une réécriture à l'entrée.
    assert r.json()["target_config"] == tc


@pytest.mark.asyncio
async def test_ambiguous_and_invalid_forms_are_refused(client: AsyncClient, scene, token) -> None:
    # Les deux formes dans le même document = ambigu.
    r = await client.post("/api/v1/events", json=_body(scene, {
        "target_type": "player", "target_ids": [1],
        "targets": [{"target_type": "site", "target_ids": [1]}],
    }), headers=_h(token))
    assert r.status_code == 422
    # `org` dans un mélange : l'union serait un org déguisé — refusé, la forme héritée
    # {"target_type": "org"} reste le seul chemin.
    r = await client.post("/api/v1/events", json=_body(scene, {
        "targets": [{"target_type": "org", "target_ids": []}],
    }), headers=_h(token))
    assert r.status_code == 422
    # Liste vide et entrée sans identifiant : des gestes ratés, nommés plutôt qu'avalés.
    r = await client.post("/api/v1/events", json=_body(scene, {"targets": []}),
                          headers=_h(token))
    assert r.status_code == 422
    r = await client.post("/api/v1/events", json=_body(scene, {
        "targets": [{"target_type": "player", "target_ids": []}],
    }), headers=_h(token))
    assert r.status_code == 422
    # Type inconnu dans une entrée.
    r = await client.post("/api/v1/events", json=_body(scene, {
        "targets": [{"target_type": "galaxy", "target_ids": [1]}],
    }), headers=_h(token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_every_entry_is_validated_for_existence(client: AsyncClient, scene, token) -> None:
    """Une 2ᵉ entrée fautive ne passe pas parce que la 1ʳᵉ est saine (audit 29/07 : les
    identifiants inexistants ou d'une autre org étaient acceptés en 201)."""
    r = await client.post("/api/v1/events", json=_body(scene, {"targets": [
        {"target_type": "site", "target_ids": [scene["site"].id_site]},
        {"target_type": "player", "target_ids": [999999]},
    ]}), headers=_h(token))
    assert r.status_code == 422
    assert "999999" in r.text


# ── Résolution force_sync (API) : l'union des entrées ──────────────────────────────

@pytest.mark.asyncio
async def test_force_sync_resolves_the_union(db_session, scene, org) -> None:
    from app.api.v1.endpoints.events import _resolve_player_ids

    tc = {"targets": [
        {"target_type": "site", "target_ids": [scene["site"].id_site]},
        {"target_type": "group", "target_ids": [scene["grp"].id_group]},
    ]}
    got = await _resolve_player_ids(db_session, org.id_org, tc)
    assert got == {scene["p1"].id_player, scene["p2"].id_player, scene["p3"].id_player}


# ── Filtre du calendrier : un event est retenu dès qu'UNE entrée touche la cible ───

@pytest.mark.asyncio
async def test_calendar_filter_matches_via_second_entry(
    client: AsyncClient, db_session, scene, org, token
) -> None:
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Mixte", event_type="manual", event_kind="content",
        id_playlist=scene["playlist"].id_playlist,
        target_config={"targets": [
            {"target_type": "site", "target_ids": [scene["site"].id_site]},
            {"target_type": "player", "target_ids": [scene["p3"].id_player]},
        ]},
    ))
    await db_session.commit()

    # p3 n'est atteint que par la 2ᵉ entrée (il n'est pas dans le site).
    r = await client.get(
        f"/api/v1/events?target_type=player&target_id={scene['p3'].id_player}",
        headers=_h(token))
    assert r.status_code == 200, r.text
    assert [e["event_name"] for e in r.json()] == ["Mixte"]
    # Un écran étranger à toutes les entrées ne remonte rien.
    ghost = CmsPlayer(id_org=org.id_org, player_name="Fantome")
    db_session.add(ghost)
    await db_session.commit()
    r = await client.get(
        f"/api/v1/events?target_type=player&target_id={ghost.id_player}",
        headers=_h(token))
    assert r.json() == []


# ── Purges d'orphelins : les deux formes sont nettoyées ────────────────────────────

@pytest.mark.asyncio
async def test_player_delete_purges_hetero_targets(
    client: AsyncClient, db_session, scene, org
) -> None:
    """DELETE /players/{id} retirait l'id de la forme héritée seulement — la purge passe
    par le helper partagé et nettoie aussi les entrées hétérogènes (entrée vidée retirée)."""
    uid = uuid.uuid4().hex[:8]
    admin = CmsUser(id_org=org.id_org, email=f"adm-{uid}@test.com",
                    password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(admin)
    await db_session.flush()
    # require_org_admin lit les rôles EN BASE, pas la claim du jeton.
    await db_session.execute(
        pg_insert(CmsRole).values(role_key="CMS_ORG_ADMIN", label="Org Admin",
                                  is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    admin_role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=admin.id_user, id_role=admin_role.id_role))
    await db_session.commit()
    admin_token = create_access_token(
        admin.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"})

    ev = CmsEvent(
        id_org=org.id_org, event_name="Purge", event_type="manual", event_kind="content",
        id_playlist=scene["playlist"].id_playlist,
        target_config={"targets": [
            {"target_type": "player", "target_ids": [scene["p3"].id_player]},
            {"target_type": "site", "target_ids": [scene["site"].id_site]},
        ]},
    )
    db_session.add(ev)
    await db_session.commit()
    id_event = ev.id_event
    id_site = scene["site"].id_site           # avant expire_all : un accès différé sur un
    id_p3 = scene["p3"].id_player             # objet expiré = lazy-load SYNC → MissingGreenlet

    r = await client.delete(f"/api/v1/players/{id_p3}", headers=_h(admin_token))
    assert r.status_code in (200, 204), r.text

    db_session.expire_all()
    ev2 = (await db_session.execute(
        select(CmsEvent).where(CmsEvent.id_event == id_event))).scalar_one()
    assert ev2.target_config == {"targets": [
        {"target_type": "site", "target_ids": [id_site]},
    ]}
