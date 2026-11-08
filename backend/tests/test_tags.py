"""
Tests Sprint 2.6 — Tags & filtrage de contenu §XVII.

- Algorithme de matching (fonctions pures) : universel / incompatible / override
- API : namespaces/valeurs, tagging média, filtres player, simulate-tags
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.media import CmsMedia
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.tags import compute_effective_tags, item_matches_player


# ── Tests unitaires de l'algorithme (§XVII.4) ───────────────────────────────────

def test_universal_content_matches_all_players():
    # Contenu sans tag = universel → match quel que soit le filtre player
    assert item_matches_player({}, {"region": ["FR"]}) is True
    # Player sans filtre = accepte tout
    assert item_matches_player({"region": ["DE"]}, {}) is True
    # Namespace non filtré sur le player → ignoré
    assert item_matches_player({"region": ["DE"]}, {"language": ["fr"]}) is True


def test_tagged_content_not_sent_to_incompatible_player():
    # Contenu taggé region:DE, player region:FR → bloqué (aucun tag commun)
    assert item_matches_player({"region": ["DE"]}, {"region": ["FR"]}) is False
    # Au moins un tag commun → passe
    assert item_matches_player({"region": ["DE", "FR"]}, {"region": ["FR"]}) is True


def test_override_mode_replaces_media_tags():
    media = {"region": ["DE"]}
    item = {"region": ["FR"]}
    # Additif : union DE+FR
    eff_add = compute_effective_tags(media, item, set())
    assert set(eff_add["region"]) == {"DE", "FR"}
    # Override : l'item remplace le média → FR seul
    eff_ovr = compute_effective_tags(media, item, {"region"})
    assert eff_ovr["region"] == ["FR"]
    # Conséquence : un player DE ne reçoit plus le contenu en mode override
    assert item_matches_player(eff_ovr, {"region": ["DE"]}) is False
    assert item_matches_player(eff_add, {"region": ["DE"]}) is True


# ── Fixtures API ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="TagOrg", org_slug=f"tag-{uuid.uuid4().hex[:8]}")
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
        id_org=org.id_org, email=f"tag-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_TAG_{uid}", label="Tag", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, op in [
        ("media", "read"), ("media", "edit"),
        ("players", "read"), ("players", "edit"),
        ("playlists", "read"), ("playlists", "edit"),
    ]:
        await db_session.execute(
            pg_insert(CmsPermission).values(module=module, operation=op, label=f"{module}.{op}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(CmsPermission.module == module, CmsPermission.operation == op)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── Tests API ───────────────────────────────────────────────────────────────────

async def test_namespace_value_crud(client: AsyncClient, auth_token: str) -> None:
    h = {"Authorization": f"Bearer {auth_token}"}
    ns = (await client.post("/api/v1/tags/namespaces",
        json={"namespace_key": "region", "label": "Région", "applies_to": []}, headers=h)).json()
    assert ns["namespace_key"] == "region"
    # doublon → 409
    dup = await client.post("/api/v1/tags/namespaces", json={"namespace_key": "region"}, headers=h)
    assert dup.status_code == 409
    val = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values",
        json={"tag_value": "FR", "color": "#3B82F6"}, headers=h)).json()
    assert val["tag_value"] == "FR"
    listed = (await client.get("/api/v1/tags/namespaces", headers=h)).json()
    reg = next(n for n in listed if n["namespace_key"] == "region")
    assert len(reg["values"]) == 1


async def test_simulation_endpoint_returns_correct_items_per_player(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    h = {"Authorization": f"Bearer {auth_token}"}

    # Taxonomie : region {FR, DE}
    ns = (await client.post("/api/v1/tags/namespaces", json={"namespace_key": "region"}, headers=h)).json()
    fr = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values",
        json={"tag_value": "FR"}, headers=h)).json()
    de = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values",
        json={"tag_value": "DE"}, headers=h)).json()

    # 2 médias (FR, DE) + 1 universel, dans une playlist
    media_fr = CmsMedia(id_org=org.id_org, media_name="FR clip", media_type="video",
                        storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex, transcode_status="done")
    media_de = CmsMedia(id_org=org.id_org, media_name="DE clip", media_type="video",
                        storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex, transcode_status="done")
    media_all = CmsMedia(id_org=org.id_org, media_name="Universal", media_type="video",
                         storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex, transcode_status="done")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db_session.add_all([media_fr, media_de, media_all, pl])
    await db_session.flush()
    it_fr = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_fr.id_media, sort_order=0, duration_ms=5000)
    it_de = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_de.id_media, sort_order=1, duration_ms=5000)
    it_all = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media_all.id_media, sort_order=2, duration_ms=5000)
    player_fr = CmsPlayer(id_org=org.id_org, player_name="Player FR")
    db_session.add_all([it_fr, it_de, it_all, player_fr])
    await db_session.commit()

    # Tag médias FR/DE
    await client.put(f"/api/v1/media/{media_fr.id_media}/tags", json={"id_tags": [fr["id_tag"]]}, headers=h)
    await client.put(f"/api/v1/media/{media_de.id_media}/tags", json={"id_tags": [de["id_tag"]]}, headers=h)
    # Filtre player = FR
    await client.put(f"/api/v1/players/{player_fr.id_player}/tag-filters", json={"id_tags": [fr["id_tag"]]}, headers=h)

    sim = (await client.post(f"/api/v1/playlists/{pl.id_playlist}/simulate-tags",
        json={"player_ids": [player_fr.id_player]}, headers=h)).json()
    assert len(sim) == 1
    by_media = {i["id_media"]: i["matched"] for i in sim[0]["items"]}
    assert by_media[media_fr.id_media] is True    # FR ↔ FR
    assert by_media[media_de.id_media] is False   # DE bloqué
    assert by_media[media_all.id_media] is True    # universel


async def test_item_override_via_api(
    client: AsyncClient, auth_token: str, db_session: AsyncSession, org: CmsOrganization
) -> None:
    h = {"Authorization": f"Bearer {auth_token}"}
    ns = (await client.post("/api/v1/tags/namespaces", json={"namespace_key": "region"}, headers=h)).json()
    fr = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values", json={"tag_value": "FR"}, headers=h)).json()
    de = (await client.post(f"/api/v1/tags/namespaces/{ns['id_namespace']}/values", json={"tag_value": "DE"}, headers=h)).json()

    media = CmsMedia(id_org=org.id_org, media_name="m", media_type="video",
                     storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex, transcode_status="done")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL2")
    db_session.add_all([media, pl])
    await db_session.flush()
    item = CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media, sort_order=0, duration_ms=5000)
    db_session.add(item)
    await db_session.commit()

    await client.put(f"/api/v1/media/{media.id_media}/tags", json={"id_tags": [de["id_tag"]]}, headers=h)
    # item override region = FR
    res = (await client.put(f"/api/v1/playlist-items/{item.id_item}/tags",
        json={"tags": [fr["id_tag"]], "ns_overrides": [ns["id_namespace"]]}, headers=h)).json()
    # effectif = FR seul (override remplace DE du média)
    assert res["effective"]["region"] == ["FR"]
