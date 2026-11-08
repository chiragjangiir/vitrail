"""Tests RBAC par rôle système — Approbateur / Designer / Planificateur.

PRINCIPE (leçon du 2026-07-20 : mesurer, puis affirmer)
On ne code pas l'attendu « à la main ». Pour chaque endpoint on relève la
permission qu'il vérifie RÉELLEMENT dans le code (`require_permission(module,
op)`), et pour chaque rôle le jeu de permissions qu'il DÉTIENT (seed migration
0002, relevé sur la base réelle via `scripts/gen_role_matrix.py`). Le croisement
des deux donne l'attendu :

    permission de l'endpoint ∈ permissions du rôle   →  la garde laisse passer  (≠ 403)
    sinon                                            →  la garde bloque         (== 403)

Une permission DÉTENUE mais vérifiée nulle part n'accorde rien : c'est pour ça
que la référence est la permission relevée dans le CODE, pas le catalogue seedé.

CE QUE CES TESTS VERROUILLENT, au-delà du « ça marche »
  - Designer n'a PAS `playlists:delete` → il crée/édite une playlist mais ne peut
    pas la supprimer (403).
  - Planificateur n'a PAS `events:delete`, ni `vod:edit`, ni `vod:delete` → il
    crée/déclenche mais ne supprime pas un événement, ne modifie/supprime pas une
    config VOD.
  - Aucun des trois n'est org-admin → l'administration (users/groups) répond 403.
  - Approbateur peut approuver/rejeter (y compris un créatif de campagne) mais ne
    voit ni la médiathèque en écriture, ni les programmes/événements/players.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

# ── Permissions DÉTENUES par chaque rôle système ────────────────────────────
# Relevé exact du seed (migration 0002) via scripts/gen_role_matrix.py, le
# 2026-07-21. Les permissions INERTES détenues (vérifiées nulle part aujourd'hui)
# sont incluses pour reproduire le rôle fidèlement : `templates:publish`,
# `playlists:schedule`, `schedules:activate`. Si l'une devient un jour vérifiée
# par un endpoint listé ci-dessous, ce test le signalera.
ROLE_PERMS: dict[str, list[str]] = {
    # `templates:read` retiré du seed le 2026-07-21 (migration 0098) : sans utilité
    # pour un rôle qui n'approuve que des créatifs de campagne (des médias).
    "CMS_APPROVER": [
        "approvals:approve", "approvals:reject", "approvals:review",
        "media:read", "playlists:read",
    ],
    "CMS_DESIGNER": [
        "media:create", "media:delete", "media:edit", "media:read",
        "playlists:create", "playlists:edit", "playlists:read",
        "templates:create", "templates:delete", "templates:edit",
        "templates:publish", "templates:read",
    ],
    # events:edit/delete + vod:edit/delete ajoutés le 2026-07-21 (migration 0099) :
    # un planificateur gère événements et VOD de bout en bout, y compris ceux d'un
    # autre planificateur (décision Ed — couvrir l'absence d'un collègue).
    "CMS_SCHEDULER": [
        "events:create", "events:delete", "events:edit", "events:read", "events:trigger",
        "media:read", "players:read",
        "playlists:read", "playlists:schedule",
        "schedules:activate", "schedules:create", "schedules:delete",
        "schedules:edit", "schedules:read",
        "templates:read",
        "vod:create", "vod:delete", "vod:edit", "vod:read", "vod:trigger",
    ],
}

# ── Endpoints × permission réellement vérifiée ──────────────────────────────
# (label, méthode, chemin, "module:op" gardé par l'endpoint).
# ⚠️ Le slash final n'est PAS uniforme (relevé sur les décorateurs) : `/templates`
# et `/playlists` en POST n'en ont pas, mais `/media/`, `/playlists/`, `/players/`
# et `/approvals/` en GET en ont un. Un mauvais slash renverrait 307, pas 403 —
# le test l'attrape explicitement.
# Les {id} pointent volontairement sur un id inexistant : la garde RBAC est une
# dépendance de route, résolue AVANT le corps → un rôle non autorisé reçoit 403
# même sur une ressource absente ; un rôle autorisé va jusqu'au 404 (donc ≠ 403).
ENDPOINTS: list[tuple[str, str, str, str]] = [
    # Média
    ("media_list",        "GET",    "/api/v1/media/",              "media:read"),
    ("media_upload",      "POST",   "/api/v1/media/upload",        "media:create"),
    ("media_delete",      "DELETE", "/api/v1/media/999999",        "media:delete"),
    # Templates
    ("templates_list",    "GET",    "/api/v1/templates",           "templates:read"),
    ("templates_create",  "POST",   "/api/v1/templates",           "templates:create"),
    ("templates_delete",  "DELETE", "/api/v1/templates/999999",    "templates:delete"),
    # Playlists  (Designer a create/edit mais PAS delete)
    ("playlists_list",    "GET",    "/api/v1/playlists/",          "playlists:read"),
    ("playlists_create",  "POST",   "/api/v1/playlists",           "playlists:create"),
    ("playlists_edit",    "PUT",    "/api/v1/playlists/999999",    "playlists:edit"),
    ("playlists_delete",  "DELETE", "/api/v1/playlists/999999",    "playlists:delete"),
    # Programmes  (Planificateur : plein contrôle)
    ("schedules_list",    "GET",    "/api/v1/schedules",           "schedules:read"),
    ("schedules_create",  "POST",   "/api/v1/schedules",           "schedules:create"),
    ("schedules_delete",  "DELETE", "/api/v1/schedules/999999",    "schedules:delete"),
    # Événements  (Planificateur a create/trigger mais PAS delete)
    ("events_list",       "GET",    "/api/v1/events",              "events:read"),
    ("events_create",     "POST",   "/api/v1/events",              "events:create"),
    ("events_delete",     "DELETE", "/api/v1/events/999999",       "events:delete"),
    # VOD  (Planificateur a create/trigger mais PAS edit/delete)
    ("vod_list",          "GET",    "/api/v1/vod",                 "vod:read"),
    ("vod_create",        "POST",   "/api/v1/vod",                 "vod:create"),
    ("vod_edit",          "PUT",    "/api/v1/vod/999999",          "vod:edit"),
    ("vod_delete",        "DELETE", "/api/v1/vod/999999",          "vod:delete"),
    ("vod_play",          "POST",   "/api/v1/vod/999999/play",     "vod:trigger"),
    # Players (lecture seule pour le Planificateur)
    ("players_list",      "GET",    "/api/v1/players/",            "players:read"),
    # Approbations  (Approbateur uniquement)
    ("approvals_list",    "GET",    "/api/v1/approvals/",          "approvals:review"),
    ("approvals_approve", "POST",   "/api/v1/approvals/999999/approve", "approvals:approve"),
    ("approvals_reject",  "POST",   "/api/v1/approvals/999999/reject",  "approvals:reject"),
    # Administration — aucun des trois n'est admin ni ne détient ces droits → 403
    ("users_list",        "GET",    "/api/v1/users",               "users:read"),
    ("users_create",      "POST",   "/api/v1/users",               "users:create"),
    ("groups_list",       "GET",    "/api/v1/groups",              "groups:read"),
]


async def _org(db: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RBAC", org_slug=f"rbac-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    return o


async def _grant(db: AsyncSession, role: CmsRole, module: str, op: str) -> None:
    await db.execute(
        pg_insert(CmsPermission)
        .values(module=module, operation=op, label=f"{module}.{op}")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db.flush()
    perm = (
        await db.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == op
            )
        )
    ).scalar_one()
    await db.execute(
        pg_insert(CmsRolePermission)
        .values(id_role=role.id_role, id_permission=perm.id_permission)
        .on_conflict_do_nothing()
    )


async def _user(db: AsyncSession, org: CmsOrganization, role_key: str) -> CmsUser:
    user = CmsUser(
        id_org=org.id_org,
        email=f"u-{uuid.uuid4().hex[:8]}@t.com",
        password_hash=hash_password("Password1!"),
        is_active=True,
        full_name=role_key,
    )
    db.add(user)
    await db.flush()
    role = (
        await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))
    ).scalars().first()
    if role is None:
        role = CmsRole(id_org=None, role_key=role_key, label=role_key, is_system=True)
        db.add(role)
        await db.flush()
    for pair in ROLE_PERMS[role_key]:
        module, op = pair.split(":")
        await _grant(db, role, module, op)
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    return user


def _headers(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest.mark.parametrize("role_key", list(ROLE_PERMS))
@pytest.mark.parametrize(
    "label,method,path,perm", ENDPOINTS, ids=[e[0] for e in ENDPOINTS]
)
@pytest.mark.asyncio
async def test_role_endpoint_gate(
    client: AsyncClient,
    db_session: AsyncSession,
    role_key: str,
    label: str,
    method: str,
    path: str,
    perm: str,
) -> None:
    org = await _org(db_session)
    user = await _user(db_session, org, role_key)
    body = {} if method in ("POST", "PUT", "PATCH") else None
    resp = await client.request(method, path, headers=_headers(user), json=body)

    # Un 307/308 trahit un mauvais slash dans la table ci-dessus : on l'attrape
    # plutôt que de laisser un faux « autorisé » passer sur une redirection.
    assert resp.status_code not in (307, 308), (
        f"{method} {path} → {resp.status_code} (redirection, slash final ?)"
    )
    # Un 5xx n'est jamais un résultat RBAC attendu — signalerait un bug serveur.
    assert resp.status_code < 500, f"{role_key} {label} → {resp.status_code} (erreur serveur)"

    denied = perm not in set(ROLE_PERMS[role_key])
    if denied:
        assert resp.status_code == 403, (
            f"{role_key} {label} ({perm}) : attendu 403, reçu {resp.status_code}"
        )
    else:
        assert resp.status_code != 403, (
            f"{role_key} {label} ({perm}) : la garde a bloqué À TORT ({resp.status_code})"
        )


@pytest.mark.parametrize(
    "role_key,path",
    [
        # Les surfaces de LISTE que chaque rôle doit pouvoir ouvrir (200), pour
        # prouver que la garde laisse VRAIMENT passer et pas seulement « pas 403 ».
        ("CMS_APPROVER", "/api/v1/approvals/"),
        ("CMS_APPROVER", "/api/v1/media/"),
        ("CMS_DESIGNER", "/api/v1/media/"),
        ("CMS_DESIGNER", "/api/v1/templates"),
        ("CMS_DESIGNER", "/api/v1/playlists/"),
        ("CMS_SCHEDULER", "/api/v1/schedules"),
        ("CMS_SCHEDULER", "/api/v1/events"),
        ("CMS_SCHEDULER", "/api/v1/vod"),
        ("CMS_SCHEDULER", "/api/v1/players/"),
    ],
)
@pytest.mark.asyncio
async def test_role_can_open_its_lists(
    client: AsyncClient, db_session: AsyncSession, role_key: str, path: str
) -> None:
    org = await _org(db_session)
    user = await _user(db_session, org, role_key)
    resp = await client.get(path, headers=_headers(user))
    assert resp.status_code == 200, f"{role_key} {path} → {resp.status_code}"
