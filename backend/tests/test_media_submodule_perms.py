"""Séparation ADDITIVE des sous-modules de la médiathèque + 2 gardes de nœud manquantes.

Audit du menu Média (2026-07-28), points tranchés par Ed :
  · flux / pages web / tags / génération IA ont enfin des permissions PROPRES — mais
    l'ancienne `media:*` continue de fonctionner (16 comptes la portent en production,
    via des rôles dont certains sont personnalisés côté client) ;
  · rattacher un panier audio à un nœud exige d'ADMINISTRER ce nœud ;
  · appliquer un tag à un média est une mutation de ce média.

⚠️ La base de test est bâtie par `create_all`, SANS migrations : les permissions de la
migration 0114 n'y existent donc pas. Les tests créent explicitement celles dont ils ont
besoin — et `test_migration_0114_declares_every_module_used_by_the_code` lit la migration
elle-même pour garantir qu'elle ne dérive pas du code (même garde anti-dérive que 0111).
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.governance import CmsGovernanceNode, CmsGovernanceNodeAdmin
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Sub", org_slug=f"sub-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _user_with(db: AsyncSession, org, perms: list[tuple[str, str]]) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"s-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_S_{uid}", label="S", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in perms:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db.flush()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


# ── Séparation additive ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_permission_alone_grants_access(client: AsyncClient, db_session, org) -> None:
    """C'est TOUT l'intérêt : un « gestionnaire de flux » sans la médiathèque.

    Constat d'Ed : « tu ne peux pas confier la gestion des flux à quelqu'un sans lui ouvrir
    toute la médiathèque en écriture — suppression de vidéos comprise. »
    """
    u = await _user_with(db_session, org, [("feeds", "read"), ("feeds", "create")])
    assert (await client.get("/api/v1/feeds", headers=_h(u))).status_code == 200
    # …et il n'a toujours PAS la médiathèque : c'est la séparation qu'on cherchait.
    assert (await client.get("/api/v1/media/", headers=_h(u))).status_code == 403


@pytest.mark.asyncio
async def test_legacy_media_permission_still_works(client: AsyncClient, db_session, org) -> None:
    """ADDITIF : les 16 comptes qui portent `media:*` ne perdent RIEN.

    C'est la raison du choix d'Ed contre une bascule sèche — des rôles personnalisés
    créés côté client portent `media:edit` et nous sont inconnus.
    """
    u = await _user_with(db_session, org, [("media", "read")])
    for path in ("/api/v1/feeds", "/api/v1/url-display", "/api/v1/tags/namespaces"):
        assert (await client.get(path, headers=_h(u))).status_code == 200, path


@pytest.mark.asyncio
async def test_neither_permission_is_refused(client: AsyncClient, db_session, org) -> None:
    """Et le message nomme la permission SPÉCIFIQUE, celle qu'on veut voir accorder."""
    u = await _user_with(db_session, org, [("players", "read")])
    r = await client.get("/api/v1/feeds", headers=_h(u))
    assert r.status_code == 403
    assert "feeds:read" in r.json()["detail"]


@pytest.mark.asyncio
async def test_migration_0114_declares_every_module_used_by_the_code() -> None:
    """Garde anti-dérive : la base de test n'exécute PAS les migrations, donc rien ne
    garantit que 0114 déclare bien ce que le code exige. On lit la migration."""
    import pathlib
    import re

    src = pathlib.Path("alembic/versions/0114_split_media_submodules.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'^\s{4}"(\w+)": \{', src, re.M))
    assert declared == {"feeds", "url_display", "tags", "generation"}, declared

    # Chaque couple réellement exigé par une route doit exister dans la migration.
    endpoints = pathlib.Path("app/api/v1/endpoints")
    used: set[tuple[str, str]] = set()
    for f in endpoints.glob("*.py"):
        for mod, op in re.findall(r'require_any_permission\(\("(\w+)", "(\w+)"\)', f.read_text(encoding="utf-8")):
            used.add((mod, op))
    for mod, op in used:
        block = re.search(rf'"{mod}": \{{([^}}]*)\}}', src)
        assert block and f'"{op}"' in block.group(1), f"{mod}:{op} absent de la migration 0114"


# ── Gardes de nœud (les 2 « petits ») ────────────────────────────────────────

@pytest_asyncio.fixture
async def nodes(db_session: AsyncSession, org):
    """National → Magasin. `local` administre le magasin, pas le national."""
    nat = CmsGovernanceNode(id_org=org.id_org, node_name="National", node_level=0,
                            node_type="national", requires_approval=False, path="")
    db_session.add(nat)
    await db_session.flush()
    nat.path = str(nat.id_node)
    store = CmsGovernanceNode(id_org=org.id_org, parent_id=nat.id_node, node_name="Magasin",
                              node_level=1, node_type="store", requires_approval=False,
                              path=f"{nat.id_node}.")
    db_session.add(store)
    await db_session.flush()
    store.path = f"{nat.id_node}.{store.id_node}"
    await db_session.commit()
    return {"nat": nat, "store": store}


@pytest.mark.asyncio
async def test_audio_basket_node_must_be_administered(
    client: AsyncClient, db_session, org, nodes
) -> None:
    """Rattacher un panier à un nœud, c'est décider qui le pilotera."""
    local = await _user_with(db_session, org, [
        ("audio_baskets", "read"), ("audio_baskets", "configure")])
    db_session.add(CmsGovernanceNodeAdmin(id_node=nodes["store"].id_node, id_user=local.id_user))
    await db_session.commit()

    # Son propre nœud : accepté.
    r = await client.post("/api/v1/audio-baskets",
                          json={"basket_name": "Ambiance", "basket_type": "music",
                                "id_node": nodes["store"].id_node},
                          headers=_h(local))
    assert r.status_code == 201, r.text
    # Le nœud NATIONAL, qu'il n'administre pas : refusé (avant : accepté).
    r = await client.post("/api/v1/audio-baskets",
                          json={"basket_name": "Pirate", "basket_type": "music",
                                "id_node": nodes["nat"].id_node},
                          headers=_h(local))
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_tagging_a_media_respects_its_node(
    client: AsyncClient, db_session, org, nodes
) -> None:
    """Appliquer un tag à un média national depuis un magasin = mutation refusée."""
    local = await _user_with(db_session, org, [
        ("media", "read"), ("media", "edit"), ("tags", "edit")])
    db_session.add(CmsGovernanceNodeAdmin(id_node=nodes["store"].id_node, id_user=local.id_user))
    ns_owner = await _user_with(db_session, org, [("tags", "edit"), ("tags", "read")])
    nat_media = CmsMedia(id_org=org.id_org, media_name="National.mp4", media_type="video",
                         storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                         id_governance_node=nodes["nat"].id_node)
    mine = CmsMedia(id_org=org.id_org, media_name="Local.mp4", media_type="video",
                    storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256=uuid.uuid4().hex,
                    id_governance_node=nodes["store"].id_node)
    db_session.add_all([nat_media, mine])
    await db_session.commit()

    ns = (await client.post("/api/v1/tags/namespaces",
                            json={"namespace_key": f"ns{uuid.uuid4().hex[:6]}", "label": "Saison"},
                            headers=_h(ns_owner))).json()
    val = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values",
                             json={"tag_value": "ete"}, headers=_h(ns_owner))).json()

    r = await client.put(f"/api/v1/media/{nat_media.id_media}/tags",
                         json={"id_tags": [val["id_tag"]]}, headers=_h(local))
    assert r.status_code == 403, r.text
    assert "National.mp4" in r.json()["detail"]

    # Son propre média : accepté.
    r = await client.put(f"/api/v1/media/{mine.id_media}/tags",
                         json={"id_tags": [val["id_tag"]]}, headers=_h(local))
    assert r.status_code == 200, r.text

    # En MASSE : un lot contenant un média interdit est refusé EN ENTIER.
    r = await client.post("/api/v1/media/bulk-tag",
                          json={"id_media": [mine.id_media, nat_media.id_media],
                                "id_tags": [val["id_tag"]], "mode": "add"},
                          headers=_h(local))
    assert r.status_code == 403, r.text
