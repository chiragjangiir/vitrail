"""Tests Feed Display (§XXV.3) — tranche 1 : RSS/Atom, modes ticker & card_carousel.

Un feed = source pollable (cms_datafeeds, porte display_mode/config) + média feed_display pointeur
(cms_media, metadata.id_feed) schedulable. Couvre : CRUD `/feeds` (source + média créés ensemble),
la normalisation feedparser, et le bloc media émis au sync (display_mode + items courants).
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.feed import CmsDatafeed, CmsFeedItem
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.user import CmsUser

_MEDIA_PERMS = [("media", "create"), ("media", "read"), ("media", "edit"), ("media", "delete")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Feed", org_slug=f"feed-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def auth(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"feed-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_FEED_{uid}", label="Feed", is_system=False)
    db_session.add_all([user, role])
    await db_session.flush()
    for module, operation in _MEDIA_PERMS:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
    await db_session.flush()
    for module, operation in _MEDIA_PERMS:
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_feed_creates_source_and_media(client, db_session, org, auth):
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "Le Monde Une",
        "feed_type": "rss",
        "config": {"url": "https://www.lemonde.fr/rss/une.xml"},
        "display_mode": "card_carousel",
        "display_config": {"item_duration_s": 6, "show_image": True},
        "max_items": 5,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["feed_type"] == "rss"
    assert body["display_mode"] == "card_carousel"
    assert body["display_config"]["item_duration_s"] == 6
    assert body["url"] == "https://www.lemonde.fr/rss/une.xml"
    assert body["item_count"] == 0
    assert body["id_media"] is not None
    # Média feed_display sous-jacent : sans fichier, directement diffusable.
    media = (await db_session.execute(
        select(CmsMedia).where(CmsMedia.id_media == body["id_media"]))).scalar_one()
    assert media.media_type == "feed_display"
    assert media.storage_key == ""
    assert media.transcode_status == "done"
    assert media.media_metadata["id_feed"] == body["id_feed"]


@pytest.mark.asyncio
async def test_create_feed_rejects_bad_url(client, org, auth):
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "Bad", "feed_type": "rss", "config": {"url": "ftp://nope"}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_and_delete_feed(client, db_session, org, auth):
    rid = (await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "F", "feed_type": "rss", "config": {"url": "https://e.com/f.xml"},
        "display_mode": "ticker"})).json()["id_feed"]

    upd = await client.put(f"/api/v1/feeds/{rid}", headers=_h(auth),
                           json={"display_mode": "card_carousel", "polling_interval_s": 600})
    assert upd.status_code == 200, upd.text
    assert upd.json()["display_mode"] == "card_carousel"
    assert upd.json()["polling_interval_s"] == 600

    # L'impact est consultable avant suppression (mêmes règles que les autres contenus).
    impact = await client.get(f"/api/v1/feeds/{rid}/deletion-impact", headers=_h(auth))
    assert impact.status_code == 200, impact.text
    assert "summary" in impact.json()

    dele = await client.delete(f"/api/v1/feeds/{rid}", headers=_h(auth))
    assert dele.status_code == 200, dele.text
    assert "summary" in dele.json()
    # Feed soft-deleted → 404 ensuite.
    assert (await client.get(f"/api/v1/feeds/{rid}", headers=_h(auth))).status_code == 404
    feed = (await db_session.execute(
        select(CmsDatafeed).where(CmsDatafeed.id_feed == rid))).scalar_one()
    assert feed.is_deleted is True
    # Le média pointeur feed_display est aussi soft-deleté (plus d'orphelin en médiathèque).
    from app.models.media import CmsMedia
    ptr = (await db_session.execute(
        select(CmsMedia).where(
            CmsMedia.media_type == "feed_display",
            CmsMedia.media_metadata["id_feed"].astext == str(rid),
        ))).scalars().first()
    assert ptr is not None and ptr.is_deleted is True


@pytest.mark.asyncio
async def test_create_feed_accepts_tranche2_modes(client, auth):
    """Tranche 2 : card_grid / full_item / split_layout / compact_list + leur config."""
    body = {
        "feed_name": "Grid", "feed_type": "rss", "config": {"url": "https://e.com/g.xml"},
        "display_mode": "card_grid",
        "display_config": {"grid_columns": 4, "grid_rows": 3, "show_description": False,
                           "split_side": "right"},
    }
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json=body)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["display_mode"] == "card_grid"
    assert out["display_config"]["grid_columns"] == 4
    assert out["display_config"]["grid_rows"] == 3
    assert out["display_config"]["show_description"] is False
    assert out["display_config"]["split_side"] == "right"
    # Les autres modes tranche 2 sont acceptés à l'update.
    for m in ("full_item", "split_layout", "compact_list"):
        upd = await client.put(f"/api/v1/feeds/{out['id_feed']}", headers=_h(auth),
                               json={"display_mode": m})
        assert upd.status_code == 200, upd.text
        assert upd.json()["display_mode"] == m


@pytest.mark.asyncio
async def test_create_feed_rejects_bad_grid_dims(client, auth):
    """Les bornes de la grille sont validées (422)."""
    body = {
        "feed_name": "G", "feed_type": "rss", "config": {"url": "https://e.com/g.xml"},
        "display_mode": "card_grid", "display_config": {"grid_columns": 9},
    }
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json=body)
    assert resp.status_code == 422


# ── YouTube channel + video_feed (§25.3 suite) ──────────────────────────────────

def test_youtube_rss_url_resolution():
    """Résout les formes sans réseau (RSS direct, /channel/UC…, ID brut, playlist)."""
    from app.workers.feed_worker import _youtube_rss_url
    rss = "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefgh1234567890ABCD"
    assert _youtube_rss_url(rss) == rss   # déjà une URL RSS → inchangée
    assert _youtube_rss_url("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv") == \
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv"
    assert _youtube_rss_url("UCabcdefghijklmnopqrstuv") == \
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv"
    assert _youtube_rss_url("https://www.youtube.com/playlist?list=PL1234abcd") == \
        "https://www.youtube.com/feeds/videos.xml?playlist_id=PL1234abcd"


@pytest.mark.asyncio
async def test_create_youtube_feed_video_mode(client, db_session, org, auth):
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "Ma chaîne",
        "feed_type": "youtube_channel",
        "config": {"url": "https://www.youtube.com/@kriss_drummer"},
        "display_mode": "video_feed",
    })
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["feed_type"] == "youtube_channel"
    assert out["display_mode"] == "video_feed"
    assert out["id_media"] is not None


@pytest.mark.asyncio
async def test_video_feed_requires_youtube_channel(client, auth):
    """video_feed sur un feed non-YouTube = 422 (création ET update)."""
    bad = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "X", "feed_type": "rss", "config": {"url": "https://e.com/f.xml"},
        "display_mode": "video_feed"})
    assert bad.status_code == 422

    rid = (await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "Y", "feed_type": "rss", "config": {"url": "https://e.com/f.xml"},
        "display_mode": "ticker"})).json()["id_feed"]
    upd = await client.put(f"/api/v1/feeds/{rid}", headers=_h(auth),
                           json={"display_mode": "video_feed"})
    assert upd.status_code == 422


@pytest.mark.asyncio
async def test_cross_org_feed_is_404(client, db_session, auth):
    """Un feed d'une autre org → 404 (jamais 403)."""
    other = CmsOrganization(org_name="Other", org_slug=f"o-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    feed = CmsDatafeed(id_org=other.id_org, feed_name="X", feed_type="rss",
                       config={"url": "https://e.com/x.xml"}, display_mode="ticker")
    db_session.add(feed)
    await db_session.commit()
    assert (await client.get(f"/api/v1/feeds/{feed.id_feed}", headers=_h(auth))).status_code == 404


# ── Normalisation feedparser (pur) ───────────────────────────────────────────

def test_normalize_entry():
    from app.workers.feed_worker import _normalize_entry
    entry = {
        "id": "guid-123",
        "title": "  Titre  ",
        "summary": "Résumé de l'article",
        "link": "https://news.example.com/a/article-1",
        "author": "Jane",
        "published_parsed": (2026, 6, 15, 9, 30, 0, 0, 0, 0),
        "media_thumbnail": [{"url": "https://img.example.com/1.jpg"}],
        "tags": [{"term": "tech"}, {"term": "ai"}],
    }
    n = _normalize_entry(entry)
    assert n["guid"] == "guid-123"
    assert n["title"] == "Titre"
    assert n["image_url"] == "https://img.example.com/1.jpg"
    assert n["link_url"] == "https://news.example.com/a/article-1"
    assert n["categories"] == ["tech", "ai"]
    assert n["published_at"].year == 2026 and n["published_at"].hour == 9
    # Sans guid exploitable → None.
    assert _normalize_entry({"summary": "x"}) is None


# ── Résolution au sync (bloc media feed_display) ─────────────────────────────

@pytest.mark.asyncio
async def test_feed_display_media_dict_embeds_items(db_session, org):
    from app.api.v1.endpoints.ws import _feed_display_media_dict, _feed_source_label

    feed = CmsDatafeed(id_org=org.id_org, feed_name="News", feed_type="rss",
                       config={"url": "https://e.com/n.xml"}, display_mode="ticker",
                       display_config={"scroll_speed_px_s": 100}, max_items=2)
    db_session.add(feed)
    await db_session.flush()
    # 3 items dont un 'pending' (ne doit pas remonter) — max_items=2 borne à 2 approuvés.
    db_session.add_all([
        CmsFeedItem(id_feed=feed.id_feed, item_guid="g1", title="A",
                    link_url="https://www.lemonde.fr/x", moderation_status="approved",
                    published_at=datetime(2026, 6, 15, 8, tzinfo=timezone.utc)),
        CmsFeedItem(id_feed=feed.id_feed, item_guid="g2", title="B",
                    link_url="https://site.fr/y", moderation_status="approved",
                    published_at=datetime(2026, 6, 15, 9, tzinfo=timezone.utc)),
        CmsFeedItem(id_feed=feed.id_feed, item_guid="g3", title="C",
                    moderation_status="pending",
                    published_at=datetime(2026, 6, 15, 10, tzinfo=timezone.utc)),
    ])
    media = CmsMedia(id_org=org.id_org, media_name="News", media_type="feed_display",
                     mime_type="application/rss+xml", storage_key="", checksum_sha256="",
                     source="feed", media_metadata={"id_feed": feed.id_feed},
                     transcode_status="done", conformance_status="ready")
    db_session.add(media)
    await db_session.commit()

    block = await _feed_display_media_dict(db_session, media)
    assert block["media_type"] == "feed_display"
    fc = block["feed_config"]
    assert fc["display_mode"] == "ticker"
    assert fc["display_config"]["scroll_speed_px_s"] == 100
    titles = [i["title"] for i in fc["items"]]
    assert "C" not in titles          # pending exclu
    assert len(fc["items"]) == 2      # borné par max_items
    assert titles[0] == "B"           # plus récent d'abord
    assert fc["items"][0]["source"] == "site.fr"
    assert _feed_source_label("https://www.lemonde.fr/a") == "lemonde.fr"


# ── Modération §XXI ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_moderation_approve_reject_flow(client, db_session, org, auth):
    """Items pending → POST /moderate approve les rend diffusables ; reject les retire."""
    from app.api.v1.endpoints.ws import _feed_display_media_dict

    feed = CmsDatafeed(id_org=org.id_org, feed_name="Mod", feed_type="rss",
                       config={"url": "https://e.com/m.xml"}, display_mode="ticker",
                       moderation_enabled=True, max_items=10)
    db_session.add(feed)
    await db_session.flush()
    db_session.add_all([
        CmsFeedItem(id_feed=feed.id_feed, item_guid="m1", title="P1", moderation_status="pending"),
        CmsFeedItem(id_feed=feed.id_feed, item_guid="m2", title="P2", moderation_status="pending"),
    ])
    media = CmsMedia(id_org=org.id_org, media_name="Mod", media_type="feed_display",
                     mime_type="application/rss+xml", storage_key="", checksum_sha256="",
                     source="feed", media_metadata={"id_feed": feed.id_feed},
                     transcode_status="done", conformance_status="ready")
    db_session.add(media)
    await db_session.commit()

    # Au départ : rien d'approuvé → 0 item diffusé.
    block = await _feed_display_media_dict(db_session, media)
    assert block["feed_config"]["items"] == []

    # Filtre pending = les 2 items en attente.
    pending = (await client.get(f"/api/v1/feeds/{feed.id_feed}/items?status_filter=pending",
                                headers=_h(auth))).json()
    assert len(pending) == 2
    ids = [i["id_item"] for i in pending]

    # Approuver le 1er → diffusé ; l'autre reste pending.
    resp = await client.post(f"/api/v1/feeds/{feed.id_feed}/moderate", headers=_h(auth),
                             json={"item_ids": [ids[0]], "action": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 1, "status": "approved"}
    block = await _feed_display_media_dict(db_session, media)
    assert [i["title"] for i in block["feed_config"]["items"]] == [pending[0]["title"]]

    # Rejeter ce même item → de nouveau retiré de la diffusion.
    resp = await client.post(f"/api/v1/feeds/{feed.id_feed}/moderate", headers=_h(auth),
                             json={"item_ids": [ids[0]], "action": "reject"})
    assert resp.status_code == 200
    block = await _feed_display_media_dict(db_session, media)
    assert block["feed_config"]["items"] == []


# ── Re-hébergement vignettes MinIO + anti-SSRF (§25.6) ───────────────────────

def test_host_is_safe_blocks_private_ranges():
    from app.workers.feed_worker import _host_is_safe
    # IP littérales → getaddrinfo ne fait pas de DNS réseau.
    assert _host_is_safe("127.0.0.1") is False     # loopback
    assert _host_is_safe("10.1.2.3") is False      # privé
    assert _host_is_safe("192.168.1.1") is False   # privé
    assert _host_is_safe("169.254.1.1") is False   # link-local
    assert _host_is_safe("8.8.8.8") is True        # public


def test_fetch_image_rejects_unsafe_without_network():
    from app.workers.feed_worker import _fetch_image
    assert _fetch_image("http://127.0.0.1/x.jpg") is None       # SSRF (loopback)
    assert _fetch_image("http://10.0.0.5/p.png") is None        # SSRF (privé)
    assert _fetch_image("ftp://example.com/a.jpg") is None      # schéma non http(s)
    assert _fetch_image("notaurl") is None


@pytest.mark.asyncio
async def test_sync_emits_signed_thumbnail_when_rehosted(db_session, org):
    """Item avec thumbnail_s3 → le sync sert une URL signée MinIO (pas l'URL distante)."""
    from app.api.v1.endpoints.ws import _feed_display_media_dict

    feed = CmsDatafeed(id_org=org.id_org, feed_name="T", feed_type="rss",
                       config={"url": "https://e.com/t.xml"}, display_mode="card_carousel",
                       max_items=10)
    db_session.add(feed)
    await db_session.flush()
    db_session.add_all([
        CmsFeedItem(id_feed=feed.id_feed, item_guid="t1", title="Rehosted",
                    image_url="https://remote.example/pic.jpg",
                    thumbnail_s3=f"feed_thumbs/{feed.id_feed}/1.jpg",
                    moderation_status="approved"),
        CmsFeedItem(id_feed=feed.id_feed, item_guid="t2", title="Remote",
                    image_url="https://remote.example/other.jpg",
                    moderation_status="approved"),
    ])
    media = CmsMedia(id_org=org.id_org, media_name="T", media_type="feed_display",
                     mime_type="application/rss+xml", storage_key="", checksum_sha256="",
                     source="feed", media_metadata={"id_feed": feed.id_feed},
                     transcode_status="done", conformance_status="ready")
    db_session.add(media)
    await db_session.commit()

    block = await _feed_display_media_dict(db_session, media)
    items = {i["title"]: i for i in block["feed_config"]["items"]}
    assert "feed_thumbs" in items["Rehosted"]["image_url"]              # URL signée MinIO
    assert items["Rehosted"]["image_url"] != "https://remote.example/pic.jpg"
    assert items["Rehosted"]["image_cache_key"] == f"feed_thumbs/{feed.id_feed}/1.jpg"  # offline-first
    assert items["Remote"]["image_url"] == "https://remote.example/other.jpg"  # repli distant
    assert items["Remote"]["image_cache_key"] is None                  # pas re-hébergé → pas de cache


# ── Proxy feeds + social_wall / data_chart §25.3 ─────────────────────────────

@pytest.mark.asyncio
async def test_create_data_chart_crypto(client, db_session, org, auth):
    """Feed crypto + mode data_chart accepté ; la config proxy (coins/currency) est exposée."""
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "BTC", "feed_type": "crypto",
        "config": {"coins": ["bitcoin", "ethereum"], "currency": "EUR"},
        "display_mode": "data_chart", "display_config": {"chart_type": "bars"},
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["feed_type"] == "crypto"
    assert body["display_mode"] == "data_chart"
    assert body["config"]["coins"] == ["bitcoin", "ethereum"]
    assert body["url"] is None


@pytest.mark.asyncio
async def test_mode_compatibility_enforced(client, auth):
    """data_chart réservé aux feeds numériques, social_wall aux socials, matrice §25.3 appliquée."""
    base = {"config": {"url": "https://e.com/a.xml"}}
    bad_chart = await client.post("/api/v1/feeds", headers=_h(auth),
                                  json={"feed_name": "x", "feed_type": "rss", "display_mode": "data_chart", **base})
    assert bad_chart.status_code == 422
    bad_wall = await client.post("/api/v1/feeds", headers=_h(auth),
                                 json={"feed_name": "x", "feed_type": "rss", "display_mode": "social_wall", **base})
    assert bad_wall.status_code == 422
    # social_wall OK pour instagram
    ok = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "ig", "feed_type": "instagram", "config": {"account": "@brand"},
        "display_mode": "social_wall"})
    assert ok.status_code == 201, ok.text
    # ticker n'est pas dans la matrice instagram → 422
    bad_mode = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "ig2", "feed_type": "instagram", "config": {"account": "@brand"},
        "display_mode": "ticker"})
    assert bad_mode.status_code == 422


@pytest.mark.asyncio
async def test_sync_emits_numeric_for_data_chart(db_session, org):
    """Un item numérique (crypto) → le sync émet value_num/value_unit/change_pct/series."""
    from app.api.v1.endpoints.ws import _feed_display_media_dict

    feed = CmsDatafeed(id_org=org.id_org, feed_name="C", feed_type="crypto",
                       config={"coins": ["bitcoin"]}, display_mode="data_chart", max_items=10)
    db_session.add(feed)
    await db_session.flush()
    db_session.add(CmsFeedItem(
        id_feed=feed.id_feed, item_guid="crypto:bitcoin", title="Bitcoin",
        value_num=61000.5, value_unit="EUR", change_pct=2.3, series=[60000, 61000, 61000.5],
        moderation_status="approved", published_at=datetime(2026, 6, 17, 9, tzinfo=timezone.utc)))
    media = CmsMedia(id_org=org.id_org, media_name="C", media_type="feed_display",
                     mime_type="application/rss+xml", storage_key="", checksum_sha256="",
                     source="feed", media_metadata={"id_feed": feed.id_feed},
                     transcode_status="done", conformance_status="ready")
    db_session.add(media)
    await db_session.commit()

    it = (await _feed_display_media_dict(db_session, media))["feed_config"]["items"][0]
    assert it["value_num"] == 61000.5
    assert it["value_unit"] == "EUR"
    assert it["change_pct"] == 2.3
    assert it["series"] == [60000, 61000, 61000.5]


def test_fetch_via_proxy_parses(monkeypatch):
    """_fetch_via_proxy POST au microservice et normalise les items (incl. valeurs numériques)."""
    from app.workers import feed_worker

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"status": "ok", "items": [{
                "guid": "crypto:btc", "title": "Bitcoin", "value_num": 61000.0,
                "value_unit": "EUR", "change_pct": 1.2, "series": [1, 2, 3],
                "published_at": "2026-06-17T09:00:00Z",
            }]}

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **k): return _Resp()

    monkeypatch.setattr(feed_worker.httpx, "Client", _Client)
    items, status, note = feed_worker._fetch_via_proxy("crypto", 1, {"coins": ["bitcoin"]})
    assert status == "ok"
    assert items[0]["value_num"] == 61000.0
    assert items[0]["value_unit"] == "EUR"
    assert items[0]["published_at"] is not None      # ISO parsé en datetime


# ── Résumé IA §XXV.3 (LiteLLM) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_feed_with_ai_summary(client, db_session, org, auth):
    """ai_summary_enabled accepté à la création et reflété dans FeedRead + en base."""
    resp = await client.post("/api/v1/feeds", headers=_h(auth), json={
        "feed_name": "Smart", "feed_type": "rss",
        "config": {"url": "https://e.com/s.xml"}, "display_mode": "full_item",
        "ai_summary_enabled": True,
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["ai_summary_enabled"] is True
    feed = (await db_session.execute(
        select(CmsDatafeed).where(CmsDatafeed.id_feed == resp.json()["id_feed"]))).scalar_one()
    assert feed.ai_summary_enabled is True


@pytest.mark.asyncio
async def test_sync_emits_ai_summary(db_session, org):
    """Un item porteur de summary_ai → le sync émet le champ `summary` (le player le préfère
    à la description en mode full_item / split_layout)."""
    from app.api.v1.endpoints.ws import _feed_display_media_dict

    feed = CmsDatafeed(id_org=org.id_org, feed_name="AI", feed_type="rss",
                       config={"url": "https://e.com/ai.xml"}, display_mode="full_item",
                       ai_summary_enabled=True, max_items=10)
    db_session.add(feed)
    await db_session.flush()
    db_session.add_all([
        CmsFeedItem(id_feed=feed.id_feed, item_guid="a1", title="Titre", description="<p>Longue desc HTML</p>",
                    summary_ai="Une phrase concise.", moderation_status="approved",
                    published_at=datetime(2026, 6, 17, 9, tzinfo=timezone.utc)),
        CmsFeedItem(id_feed=feed.id_feed, item_guid="a2", title="Sans résumé", description="desc",
                    moderation_status="approved",
                    published_at=datetime(2026, 6, 17, 8, tzinfo=timezone.utc)),
    ])
    media = CmsMedia(id_org=org.id_org, media_name="AI", media_type="feed_display",
                     mime_type="application/rss+xml", storage_key="", checksum_sha256="",
                     source="feed", media_metadata={"id_feed": feed.id_feed},
                     transcode_status="done", conformance_status="ready")
    db_session.add(media)
    await db_session.commit()

    block = await _feed_display_media_dict(db_session, media)
    items = {i["title"]: i for i in block["feed_config"]["items"]}
    assert items["Titre"]["summary"] == "Une phrase concise."
    assert items["Sans résumé"]["summary"] is None     # pas de résumé → champ null, repli desc côté player


def test_feed_ai_summarize_parses_litellm(monkeypatch):
    """summarize() POST à LiteLLM (OpenAI-compat) et extrait le contenu, en retirant les guillemets."""
    from app.services import feed_ai

    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '"Phrase résumée."'}}]}

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **kw):
            captured["url"] = url
            captured["model"] = kw["json"]["model"]
            return _Resp()

    monkeypatch.setattr(feed_ai.httpx, "Client", _Client)
    out = feed_ai.summarize("Titre", "<p>Un contenu HTML assez long à résumer.</p>")
    assert out == "Phrase résumée."                       # guillemets retirés
    assert captured["url"].endswith("/v1/chat/completions")
    # entrée trop courte → pas d'appel réseau, None direct
    assert feed_ai.summarize("a", "") is None


def test_feed_ai_summarize_graceful_on_error(monkeypatch):
    """Proxy LiteLLM en erreur → None (le player retombe sur la description)."""
    from app.services import feed_ai

    class _Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): raise RuntimeError("litellm down")

    monkeypatch.setattr(feed_ai.httpx, "Client", _Boom)
    assert feed_ai.summarize("Titre", "Contenu suffisamment long pour déclencher l'appel.") is None


@pytest.mark.asyncio
async def test_moderate_requires_payload(client, db_session, org, auth):
    """item_ids vide → 422 ; action invalide → 422."""
    feed = CmsDatafeed(id_org=org.id_org, feed_name="M", feed_type="rss",
                       config={"url": "https://e.com/m.xml"}, display_mode="ticker")
    db_session.add(feed)
    await db_session.commit()
    bad1 = await client.post(f"/api/v1/feeds/{feed.id_feed}/moderate", headers=_h(auth),
                             json={"item_ids": [], "action": "approve"})
    assert bad1.status_code == 422
    bad2 = await client.post(f"/api/v1/feeds/{feed.id_feed}/moderate", headers=_h(auth),
                             json={"item_ids": [1], "action": "delete"})
    assert bad2.status_code == 422
