"""Refuser une suppression en NOMMANT ce qui la retient (P3.3).

Le produit savait dire ce qu'une suppression emporterait, mais seulement PAR ENTITÉ
(médias, templates, paniers, flux). Il ne savait rien dire d'une **organisation** ni d'un
**compte** — et pour l'organisation il n'existait même **aucun endpoint de suppression** :
un super-admin pouvait en créer, jamais en retirer une.

Pendant de la ligne d'Ed « quand on efface, on efface » : on efface franchement, ou on
refuse en expliquant. Jamais un bouton qui ne peut qu'échouer.

Ce que ces tests figent :
  1. les listes de tables sont lues DANS LE SCHÉMA — une table neuve est comptée sans que
     personne y pense (c'est la liste écrite à la main qui prend du retard en silence) ;
  2. les TROIS natures de lien sont distinguées : ce qui retient / serait emporté / serait
     délié. Un rapport qui ne dirait que « bloqué » cacherait qu'une suppression d'org
     emporterait une trentaine de tables ;
  3. le refus NOMME les tables et les comptes, et propose l'alternative réversible ;
  4. les portes fermées par construction le sont CÔTÉ SERVEUR (un écran n'est pas une
     sécurité) : sa propre organisation, son propre compte, le dernier administrateur ;
  5. 🔴 le trou du dernier administrateur : `users:delete` s'accorde à un rôle qui n'est PAS
     org-admin ⇒ son porteur pouvait désactiver TOUS les administrateurs et laisser
     l'organisation sans personne pour la rouvrir.
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services import admin_refs


async def _role(db: AsyncSession, key: str) -> CmsRole:
    await db.execute(
        pg_insert(CmsRole).values(role_key=key, label=key, is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    return (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalar_one()


async def _make_org(db: AsyncSession, name: str) -> CmsOrganization:
    o = CmsOrganization(org_name=name, org_slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


async def _make_user(db: AsyncSession, org: CmsOrganization, *, role: str | None) -> CmsUser:
    u = CmsUser(id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@t.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db.add(u)
    await db.flush()
    if role:
        r = await _role(db, role)
        db.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=r.id_role))
    await db.commit()
    await db.refresh(u)
    return u


async def _make_user_with_permission(
    db: AsyncSession, org: CmsOrganization, module: str, operation: str,
) -> CmsUser:
    """Compte porteur d'une permission ATOMIQUE, sans être administrateur.

    ⚠️ Forger un jeton qui NOMME `CMS_ORG_ADMIN` n'accorde rien : les permissions sont lues
    EN BASE (leçon du 05/08). C'est précisément ce qui rend le trou réel — le rôle
    personnalisé, lui, porte vraiment `users:delete`.
    """
    u = CmsUser(id_org=org.id_org, email=f"k-{uuid.uuid4().hex[:8]}@t.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db.add(u)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"TEST_{uuid.uuid4().hex[:8].upper()}",
                   label="Gestionnaire de comptes", is_system=False)
    db.add(role)
    await db.flush()
    await db.execute(
        pg_insert(CmsPermission)
        .values(module=module, operation=operation, label=f"{module}.{operation}")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
    )
    await db.flush()
    perm = (await db.execute(
        select(CmsPermission).where(CmsPermission.module == module,
                                    CmsPermission.operation == operation)
    )).scalar_one()
    db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(u)
    return u


def _token(user: CmsUser, roles: list[str]) -> str:
    return create_access_token(
        user.id_user, extra={"org": user.id_org, "roles": roles, "locale": "en"})


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def home_org(db_session: AsyncSession) -> CmsOrganization:
    """Organisation du super-admin : c'est SA propre org, donc une porte fermée."""
    return await _make_org(db_session, "Home")


@pytest_asyncio.fixture
async def super_admin(db_session: AsyncSession, home_org: CmsOrganization) -> CmsUser:
    return await _make_user(db_session, home_org, role="CMS_SUPER_ADMIN")


@pytest_asyncio.fixture
async def empty_org(db_session: AsyncSession) -> CmsOrganization:
    """Organisation SANS aucune référence : c'est le cas où l'on efface franchement."""
    return await _make_org(db_session, "Empty")


# ── Le service lit le schéma, pas une liste écrite à la main ───────────────────

async def test_reference_lists_come_from_the_schema(db_session: AsyncSession) -> None:
    """Les colonnes référençantes sont découvertes, pas énumérées.

    Le contrôle porte sur l'ORDRE DE GRANDEUR et sur la présence de tables qu'aucune liste
    écrite à la main n'aurait pensé à inclure — pas sur un nombre exact, qui deviendrait
    rouge à la prochaine migration sans rien signaler d'utile.
    """
    cols = await admin_refs._referencing_columns(db_session, admin_refs.ORG_COLUMNS)
    tables = {t for t, _, _ in cols}
    assert len(tables) > 40, f"seulement {len(tables)} tables — la découverte ne marche pas"
    # Des tables arrivées bien après le premier jet du module.
    for late in ("cms_promo_templates", "cms_generation_jobs", "cms_messaging_identities"):
        assert late in tables, f"{late} n'est pas découverte"
    # ⛔ La clé de la ligne visée n'est pas une référence VERS elle.
    assert ("cms_organizations", "id_org", "blocking") not in cols


async def test_the_three_kinds_of_link_are_distinguished(db_session: AsyncSession) -> None:
    """Retient / serait emporté / serait délié — sinon on cacherait le vrai danger."""
    cols = await admin_refs._referencing_columns(db_session, admin_refs.ORG_COLUMNS)
    kinds = {k for _, _, k in cols}
    assert kinds == {"blocking", "cascade", "detach"}, kinds
    by = {(t, c): k for t, c, k in cols}
    # Le journal d'audit SURVIT à l'organisation, sa référence est vidée.
    assert by[("cms_audit_log", "id_org")] == "detach"
    # Les comptes RETIENNENT leur organisation — c'est ce qui bloque en premier.
    assert by[("cms_users", "id_org")] == "blocking"
    # Les campagnes partiraient AVEC elle.
    assert by[("cms_campaigns", "id_org")] == "cascade"


# ── Organisation ───────────────────────────────────────────────────────────────

async def test_org_deletion_impact_names_what_holds_it(
    client: AsyncClient, db_session: AsyncSession, super_admin: CmsUser,
    empty_org: CmsOrganization,
) -> None:
    """Un média suffit à retenir l'organisation, et il est NOMMÉ."""
    db_session.add(CmsMedia(
        id_org=empty_org.id_org, media_name="clip", media_type="video",
        storage_key=f"k/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex * 2))
    await db_session.commit()

    h = {"Authorization": f"Bearer {_token(super_admin, ['CMS_SUPER_ADMIN'])}"}
    r = await client.get(f"/api/v1/orgs/{empty_org.id_org}/deletion-impact", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["can_delete"] is False
    held = {b["table"]: b["count"] for b in body["blocking"]}
    assert held.get("cms_media") == 1, held
    # L'alternative réversible est proposée, pas laissée à deviner.
    assert body["suspend_available"] is True


async def test_org_delete_refuses_and_names(
    client: AsyncClient, db_session: AsyncSession, super_admin: CmsUser,
    empty_org: CmsOrganization,
) -> None:
    db_session.add(CmsMedia(
        id_org=empty_org.id_org, media_name="clip", media_type="video",
        storage_key=f"k/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex * 2))
    await db_session.commit()

    h = {"Authorization": f"Bearer {_token(super_admin, ['CMS_SUPER_ADMIN'])}"}
    r = await client.delete(f"/api/v1/orgs/{empty_org.id_org}", headers=h)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "org_has_references"
    assert any(b["table"] == "cms_media" for b in d["blocking"]), d
    # L'organisation est TOUJOURS là : un refus ne détruit rien à moitié.
    still = (await db_session.execute(
        select(CmsOrganization).where(CmsOrganization.id_org == empty_org.id_org)
    )).scalar_one_or_none()
    assert still is not None


async def test_org_without_references_is_really_deleted(
    client: AsyncClient, db_session: AsyncSession, super_admin: CmsUser,
    empty_org: CmsOrganization,
) -> None:
    """Quand rien ne retient, on efface FRANCHEMENT — pas un `is_deleted` invisible."""
    h = {"Authorization": f"Bearer {_token(super_admin, ['CMS_SUPER_ADMIN'])}"}
    r = await client.delete(f"/api/v1/orgs/{empty_org.id_org}", headers=h)
    assert r.status_code == 204, r.text
    gone = (await db_session.execute(
        select(CmsOrganization).where(CmsOrganization.id_org == empty_org.id_org)
    )).scalar_one_or_none()
    assert gone is None, "la ligne doit avoir disparu de la base"


async def test_own_org_is_a_closed_door(
    client: AsyncClient, super_admin: CmsUser, home_org: CmsOrganization,
) -> None:
    """Porte fermée par construction, et refermée CÔTÉ SERVEUR."""
    h = {"Authorization": f"Bearer {_token(super_admin, ['CMS_SUPER_ADMIN'])}"}
    imp = await client.get(f"/api/v1/orgs/{home_org.id_org}/deletion-impact", headers=h)
    assert imp.json()["closed_reason"] == "own_org"
    assert imp.json()["can_delete"] is False
    r = await client.delete(f"/api/v1/orgs/{home_org.id_org}", headers=h)
    assert r.status_code == 400


# ── Comptes ────────────────────────────────────────────────────────────────────

async def test_delete_without_purge_still_deactivates(
    client: AsyncClient, db_session: AsyncSession, empty_org: CmsOrganization,
) -> None:
    """Le geste NORMAL reste la désactivation : l'email reste pris, le compte revient.

    Non-régression : c'est le contrat de la ré-invitation d'annonceur (get-or-link).
    """
    admin = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    other = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    h = {"Authorization": f"Bearer {_token(admin, ['CMS_ORG_ADMIN'])}"}

    r = await client.delete(f"/api/v1/users/{other.id_user}", headers=h)
    assert r.status_code == 204
    await db_session.refresh(other)
    assert other.is_active is False
    assert other.email is not None, "le compte existe toujours (email pris, trace lisible)"


async def test_purge_removes_a_never_used_account(
    client: AsyncClient, db_session: AsyncSession, empty_org: CmsOrganization,
) -> None:
    """Compte créé par erreur, qui n'a rien fait : on l'efface pour de vrai."""
    admin = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    typo = await _make_user(db_session, empty_org, role=None)
    h = {"Authorization": f"Bearer {_token(admin, ['CMS_ORG_ADMIN'])}"}

    r = await client.delete(f"/api/v1/users/{typo.id_user}?purge=true", headers=h)
    assert r.status_code == 204, r.text
    gone = (await db_session.execute(
        select(CmsUser).where(CmsUser.id_user == typo.id_user)
    )).scalar_one_or_none()
    assert gone is None


async def test_purge_refuses_and_names_what_holds_the_account(
    client: AsyncClient, db_session: AsyncSession, empty_org: CmsOrganization,
) -> None:
    admin = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    author = await _make_user(db_session, empty_org, role=None)
    db_session.add(CmsMedia(
        id_org=empty_org.id_org, media_name="son media", media_type="video",
        storage_key=f"k/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex * 2,
        created_by=author.id_user))
    await db_session.commit()

    h = {"Authorization": f"Bearer {_token(admin, ['CMS_ORG_ADMIN'])}"}
    r = await client.delete(f"/api/v1/users/{author.id_user}?purge=true", headers=h)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "user_has_references"
    assert any(b["table"] == "cms_media" and b["column"] == "created_by"
               for b in d["blocking"]), d
    assert d["deactivate_available"] is True, "l'alternative réversible est proposée"
    # Le compte est intact : un refus ne laisse pas les choses à moitié faites.
    await db_session.refresh(author)
    assert author.is_active is True


async def test_last_org_admin_cannot_be_removed(
    client: AsyncClient, db_session: AsyncSession, empty_org: CmsOrganization,
) -> None:
    """🔴 Le trou : `users:delete` s'accorde à un rôle qui n'est PAS administrateur.

    Son porteur pouvait désactiver le dernier administrateur — plus personne pour rouvrir
    l'organisation. La garde « pas son propre compte » ne l'attrape pas : il ne se supprime
    pas lui-même, il supprime l'autre.
    """
    lone_admin = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    # L'acteur est org-admin d'une AUTRE org (il en faut un pour passer la dépendance),
    # mais on le rattache à l'org visée pour reproduire le geste réel.
    actor = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    h = {"Authorization": f"Bearer {_token(actor, ['CMS_ORG_ADMIN'])}"}

    # Deux administrateurs : retirer l'un des deux est permis.
    r = await client.delete(f"/api/v1/users/{lone_admin.id_user}", headers=h)
    assert r.status_code == 204

    # `actor` est maintenant le DERNIER. Un compte tiers porteur de `users:delete` — et qui
    # n'est PAS administrateur — ne doit pas pouvoir le retirer. C'est LE cas du trou :
    # l'endpoint accepte `users:delete` OU l'org-admin.
    killer = await _make_user_with_permission(db_session, empty_org, "users", "delete")
    hk = {"Authorization": f"Bearer {_token(killer, [])}"}
    r = await client.delete(f"/api/v1/users/{actor.id_user}", headers=hk)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "last_org_admin"
    await db_session.refresh(actor)
    assert actor.is_active is True, "l'organisation garde un administrateur"


async def test_user_impact_reports_the_closed_door(
    client: AsyncClient, db_session: AsyncSession, empty_org: CmsOrganization,
) -> None:
    """L'écran doit pouvoir GRISER et expliquer, pas laisser cliquer pour échouer."""
    admin = await _make_user(db_session, empty_org, role="CMS_ORG_ADMIN")
    h = {"Authorization": f"Bearer {_token(admin, ['CMS_ORG_ADMIN'])}"}
    r = await client.get(f"/api/v1/users/{admin.id_user}/deletion-impact", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["closed_reason"] == "self"
    assert body["can_delete"] is False
