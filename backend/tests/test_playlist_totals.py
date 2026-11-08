"""Durées visibles des playlists (demande Ed 2026-08-15).

- `media_duration_ms` sur chaque item (durée NATIVE vidéo/audio extraite à l'upload) :
  chemin publié ET chemin brouillon — avant, l'éditeur affichait « — » pour une vidéo
  sans override alors que la donnée était déjà SELECTée par l'endpoint.
- `item_count` + `total_duration_ms` sur la liste (vignettes) : total = même repli
  que le wall-clock du player (item.duration_ms → media.duration_ms → 10 s).
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="TotOrg", org_slug=f"tot-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def headers(client: AsyncClient, db_session: AsyncSession, org) -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"tot-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_TOT_{uid}", label="Tot", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("playlists", "read"), ("playlists", "edit")]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _mk_media(db: AsyncSession, org, media_type: str,
                    dur: int | None) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name=f"m-{uuid.uuid4().hex[:8]}",
                 media_type=media_type, storage_key=f"t/{uuid.uuid4().hex}",
                 checksum_sha256="x", transcode_status="done", duration_ms=dur)
    db.add(m)
    await db.flush()
    return m


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_published_items_expose_media_duration_and_totals(
    client: AsyncClient, db_session: AsyncSession, org, headers,
) -> None:
    """Chemin PUBLIÉ : une vidéo sans override expose sa durée native, et la liste
    porte item_count + total (42 s vidéo + 5 s image + 10 s repli url = 57 s)."""
    video = await _mk_media(db_session, org, "video", 42_000)
    image = await _mk_media(db_session, org, "image", None)
    url = await _mk_media(db_session, org, "url_display", None)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name=f"Tot-{uuid.uuid4().hex[:6]}")
    db_session.add(pl)
    await db_session.flush()
    for i, (m, override) in enumerate([(video, None), (image, 5_000), (url, None)]):
        db_session.add(CmsPlaylistItem(
            id_playlist=pl.id_playlist, id_media=m.id_media,
            sort_order=i, duration_ms=override))
    await db_session.commit()

    resp = await client.get(f"/api/v1/playlists/{pl.id_playlist}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    by_media = {it["id_media"]: it for it in data["items"]}
    assert by_media[video.id_media]["duration_ms"] is None
    assert by_media[video.id_media]["media_duration_ms"] == 42_000
    assert by_media[image.id_media]["duration_ms"] == 5_000
    assert data["total_duration_ms"] == 42_000 + 5_000 + 10_000

    resp = await client.get("/api/v1/playlists/", headers=headers)
    assert resp.status_code == 200
    row = next(p for p in resp.json() if p["id_playlist"] == pl.id_playlist)
    assert row["item_count"] == 3
    assert row["total_duration_ms"] == 42_000 + 5_000 + 10_000


async def test_draft_items_expose_media_duration(
    client: AsyncClient, db_session: AsyncSession, org, headers,
) -> None:
    """Chemin BROUILLON : un ajout d'item par l'API crée le draft ; la relecture
    du détail doit exposer la durée native exactement comme le publié."""
    video = await _mk_media(db_session, org, "video", 33_000)
    pl = CmsPlaylist(id_org=org.id_org, playlist_name=f"Tot-{uuid.uuid4().hex[:6]}")
    db_session.add(pl)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/playlists/{pl.id_playlist}/items",
        json={"id_media": video.id_media, "sort_order": 0}, headers=headers)
    assert resp.status_code == 201, resp.text

    resp = await client.get(f"/api/v1/playlists/{pl.id_playlist}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_draft_changes"] is True
    assert data["items"][0]["duration_ms"] is None
    assert data["items"][0]["media_duration_ms"] == 33_000
    assert data["total_duration_ms"] == 33_000
