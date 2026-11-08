"""Tests Documents multipages (PDF/PPT/PPTX) — §3.2 « rendu page par page ».

- Parsing pur : parse_page_selection ("2-5,8", bornes, ordre, doublons, invalide),
  effective_duration_py (durée par page × pages).
- Déroulé : unroll_slots aplatit les listes imbriquées (document = 1 unité de slot).
- Payload player (_resolve_sync_payload) : un item document converti devient N items
  IMAGE (durée par page, cache_key/checksum par page, sélection honorée), document
  en rotation = 1 unité par tour, PDF non converti = fallback historique (1 item
  document), PPTX non converti = non servi.
- API : PATCH doc_pages (brouillon → publish → doc_page_count dénormalisé),
  GET /media/{id}/pages, total_duration_ms/sync_ready document-aware.
- Worker : conversion réelle PDF→pages (skip si poppler absent de l'environnement).
"""

import shutil
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.ws import _resolve_sync_payload
from app.core.security import hash_password
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
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.document_media import (
    effective_duration_py,
    parse_page_selection,
    selection_count,
)
from app.services.playlist_rotation import unroll_slots


# ── Parsing pur ────────────────────────────────────────────────────────────────

def test_parse_page_selection():
    assert parse_page_selection(None, 4) == [1, 2, 3, 4]
    assert parse_page_selection("", 4) == [1, 2, 3, 4]
    assert parse_page_selection("2-3", 4) == [2, 3]
    assert parse_page_selection("2-5,8", 10) == [2, 3, 4, 5, 8]
    # Ordre de saisie respecté (diffuser la page 5 avant la 2) + doublons ignorés.
    assert parse_page_selection("5,2,5", 6) == [5, 2]
    # Bornes clampées au nombre de pages réel.
    assert parse_page_selection("3-99", 5) == [3, 4, 5]
    assert parse_page_selection("0-2", 5) == [1, 2]
    # Plage inversée tolérée.
    assert parse_page_selection("5-3", 6) == [3, 4, 5]
    # Hors bornes / illisible → repli sûr : tout le document.
    assert parse_page_selection("42", 3) == [1, 2, 3]
    assert parse_page_selection("abc", 3) == [1, 2, 3]
    assert parse_page_selection("1,x", 3) == [1, 2, 3]
    assert selection_count("2-5,8", 10) == 5


def test_effective_duration_py():
    # Non-document : fallback historique item → media → None.
    assert effective_duration_py(5000, 20000, None) == 5000
    assert effective_duration_py(None, 20000, None) == 20000
    assert effective_duration_py(None, None, None) is None
    # Document : par page × pages (défaut 10 s/page), jamais None.
    assert effective_duration_py(None, None, 6) == 60000
    assert effective_duration_py(5000, None, 6) == 30000
    assert effective_duration_py(5000, None, 6, doc_pages="2-3") == 10000
    assert effective_duration_py(5000, None, 6, doc_page_count=4) == 20000


def test_unroll_slots_flattens_nested_lists():
    # Un document (liste de pages) reste UNE unité de rotation, aplatie en sortie.
    base = [
        {"kind": "inline", "items": ["A"]},
        {"kind": "rotation", "items": [["d1", "d2"], "r2"], "mode": "one_sequential",
         "k": 1, "seed": 0},
    ]
    out = unroll_slots(base)
    assert out == ["A", "d1", "d2", "A", "r2"]
    # Inline avec document imbriqué : simple aplatissement.
    assert unroll_slots([{"kind": "inline", "items": ["A", ["d1", "d2"], "B"]}]) == \
        ["A", "d1", "d2", "B"]


# ── Fixtures API ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="DocOrg", org_slug=f"doc-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def headers(client: AsyncClient, db_session: AsyncSession, org) -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"doc-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_DOC_{uid}", label="Doc", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [
        ("playlists", "create"), ("playlists", "read"), ("playlists", "edit"),
        ("media", "read"),
    ]:
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


def _doc_meta(base: str, n: int) -> dict:
    return {
        "document": {
            "page_count": n,
            "pages": [
                {"key": f"{base}_pages/{i:04d}.jpg", "checksum": f"sha-{i}",
                 "width": 1920, "height": 1080}
                for i in range(1, n + 1)
            ],
            "source": "pdf",
        }
    }


async def _mk_document(db: AsyncSession, org, name: str, pages: int,
                       mime: str = "application/pdf", converted: bool = True) -> CmsMedia:
    base = f"t/{uuid.uuid4().hex}"
    m = CmsMedia(
        id_org=org.id_org, media_name=name, media_type="document",
        mime_type=mime, storage_key=f"{base}.pdf", checksum_sha256="x",
        transcode_status="done",
        page_count=pages if converted else None,
        media_metadata=_doc_meta(base, pages) if converted else {},
    )
    db.add(m)
    await db.flush()
    return m


async def _mk_video(db: AsyncSession, org, name: str, dur: int = 30_000) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name=name, media_type="video",
                 storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
                 transcode_status="done", duration_ms=dur)
    db.add(m)
    await db.flush()
    return m


async def _scene(db: AsyncSession, org, playlist: CmsPlaylist) -> CmsPlayer:
    player = CmsPlayer(id_org=org.id_org, player_name="P", player_os="linux")
    db.add(player)
    await db.flush()
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=playlist.id_playlist, is_active=True)
    db.add(sched)
    await db.flush()
    db.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player.id_player),
    ])
    await db.commit()
    return player


# ── Payload player : déroulé des pages ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_payload_expands_document_pages(db_session, org):
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Docs", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    video = await _mk_video(db_session, org, "vid")
    doc = await _mk_document(db_session, org, "menu.pdf", pages=3)
    db_session.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=video.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=doc.id_media,
                        sort_order=1, duration_ms=8_000),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, pl)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    items = payload["items"]
    assert len(items) == 4  # vid + 3 pages
    pages = items[1:]
    assert [p["media"]["doc_page"] for p in pages] == [1, 2, 3]
    for p in pages:
        assert p["media"]["media_type"] == "image"      # rendu par tous les players
        assert p["media"]["mime_type"] == "image/jpeg"
        assert p["duration_ms"] == 8_000                 # durée PAR PAGE
        assert p["media"]["id_media"] == doc.id_media    # PoP au document
        assert p["media"]["cache_key"].endswith(f"{p['media']['doc_page']:04d}.jpg")
        assert p["media"]["cache_checksum"] == f"sha-{p['media']['doc_page']}"
    # Wall-clock calculé sur la liste déroulée (4 items).
    assert payload["start_index"] is not None and 0 <= payload["start_index"] < 4


@pytest.mark.asyncio
async def test_sync_payload_honors_page_selection(db_session, org):
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="DocSel", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    doc = await _mk_document(db_session, org, "deck.pdf", pages=6)
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=doc.id_media,
                                   sort_order=0, duration_ms=None, doc_pages="5,2-3"))
    await db_session.commit()
    player = await _scene(db_session, org, pl)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert [i["media"]["doc_page"] for i in payload["items"]] == [5, 2, 3]
    assert all(i["duration_ms"] == 10_000 for i in payload["items"])  # défaut 10 s/page


@pytest.mark.asyncio
async def test_sync_payload_document_in_rotation_is_one_unit(db_session, org):
    parent = CmsPlaylist(id_org=org.id_org, playlist_name="Parent", sync_mode="wall_clock")
    child = CmsPlaylist(id_org=org.id_org, playlist_name="Rot",
                        rotation_mode="one_sequential", items_per_turn=1)
    db_session.add_all([parent, child])
    await db_session.flush()
    home = await _mk_video(db_session, org, "home")
    doc = await _mk_document(db_session, org, "doc.pdf", pages=2)
    r2 = await _mk_video(db_session, org, "r2")
    db_session.add_all([
        CmsPlaylistItem(id_playlist=child.id_playlist, id_media=doc.id_media,
                        sort_order=0, duration_ms=5_000),
        CmsPlaylistItem(id_playlist=child.id_playlist, id_media=r2.id_media,
                        sort_order=1, duration_ms=10_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=home.id_media,
                        sort_order=0, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=parent.id_playlist, id_media=None,
                        item_type="sub_playlist", id_child_playlist=child.id_playlist,
                        sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, parent)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    names = [i["media"]["media_name"] for i in payload["items"]]
    # T=2 tours : home + doc(2 pages) · home + r2 — le document = 1 unité de tour.
    assert names == ["home", "doc.pdf — p.1/2", "doc.pdf — p.2/2", "home", "r2"]


@pytest.mark.asyncio
async def test_sync_payload_unconverted_fallbacks(db_session, org):
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Raw", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    raw_pdf = await _mk_document(db_session, org, "raw.pdf", pages=0, converted=False)
    raw_ppt = await _mk_document(
        db_session, org, "deck.pptx", pages=0, converted=False,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    db_session.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=raw_pdf.id_media, sort_order=0),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=raw_ppt.id_media, sort_order=1),
    ])
    await db_session.commit()
    player = await _scene(db_session, org, pl)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    items = payload["items"]
    # PDF non converti : comportement historique (1 item document, iframe 1re page).
    # PPTX non converti : injouable → non servi.
    assert len(items) == 1
    assert items[0]["media"]["media_type"] == "document"
    assert items[0]["media"]["media_name"] == "raw.pdf"


# ── API : doc_pages, publish, agrégats, pages ──────────────────────────────────

@pytest.mark.asyncio
async def test_doc_pages_patch_publish_and_aggregates(client, headers, db_session, org):
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="DocApi", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    doc = await _mk_document(db_session, org, "deck.pdf", pages=6)
    await db_session.commit()

    # Ajout au brouillon.
    r = await client.post(f"/api/v1/playlists/{pl.id_playlist}/items",
                          json={"id_media": doc.id_media}, headers=headers)
    assert r.status_code == 201, r.text
    uid = r.json()["id_item"]
    assert r.json()["media_page_count"] == 6

    # Sélection de pages + durée par page.
    r = await client.patch(f"/api/v1/playlists/{pl.id_playlist}/items/{uid}",
                           json={"doc_pages": "2-4", "duration_ms": 5000}, headers=headers)
    assert r.status_code == 200, r.text
    entry = next(i for i in r.json() if i["id_item"] == uid)
    assert entry["doc_pages"] == "2-4"

    # Publish → colonnes posées + doc_page_count dénormalisé.
    r = await client.post(f"/api/v1/playlists/{pl.id_playlist}/publish", headers=headers)
    assert r.status_code == 200, r.text
    row = (await db_session.execute(
        select(CmsPlaylistItem).where(CmsPlaylistItem.id_playlist == pl.id_playlist)
    )).scalar_one()
    assert row.doc_pages == "2-4"
    assert row.doc_page_count == 3
    assert row.duration_ms == 5000

    # Liste : durée totale = 3 pages × 5 s, et sync_ready malgré media.duration NULL.
    r = await client.get("/api/v1/playlists/", headers=headers)
    me = next(p for p in r.json() if p["id_playlist"] == pl.id_playlist)
    assert me["total_duration_ms"] == 15_000
    assert me["sync_ready"] is True

    # Détail publié : mêmes chiffres.
    r = await client.get(f"/api/v1/playlists/{pl.id_playlist}", headers=headers)
    assert r.status_code == 200
    assert r.json()["total_duration_ms"] == 15_000
    item = r.json()["items"][0]
    assert item["doc_pages"] == "2-4" and item["media_page_count"] == 6


# ── Navigation tactile des documents (migr 0129, décisions d'Ed 2026-08-14) ────

@pytest.mark.asyncio
async def test_touch_navigation_reaches_every_page(db_session, org):
    """Le drapeau voyage sur CHAQUE page — c'est l'item servi que le renderer regarde.

    Le poser sur la seule première page donnerait un document navigable… jusqu'à ce que le
    visiteur tourne une page, moment où il cesserait de l'être. Rien ne le signalerait.
    """
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="DocTouch", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    doc = await _mk_document(db_session, org, "carte.pdf", pages=3)
    db_session.add(CmsPlaylistItem(
        id_playlist=pl.id_playlist, id_media=doc.id_media, sort_order=0,
        duration_ms=15_000, touch_navigation=True, touch_resume_after_s=45,
    ))
    await db_session.commit()
    player = await _scene(db_session, org, pl)

    items = (await _resolve_sync_payload(db_session, player.id_player))["items"]
    assert len(items) == 3
    for it in items:
        assert it["touch_navigation"] is True
        assert it["touch_resume_after_s"] == 45
    # Les pages partagent le MÊME id_item : c'est lui qui borne le document côté renderer.
    # Sans cette identité commune, un glissé sortirait du document sans qu'on le voie.
    assert len({it["id_item"] for it in items}) == 1


@pytest.mark.asyncio
async def test_touch_navigation_absent_when_off(db_session, org):
    """Déploiement NEUTRE : case décochée ⇒ la clé n'est pas dans le payload du tout.

    Témoin de non-régression du parc entier : ce n'est pas « false », c'est ABSENT — le
    payload servi est identique à celui d'avant la migration.
    """
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="DocPlain", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    doc = await _mk_document(db_session, org, "plain.pdf", pages=2)
    db_session.add(CmsPlaylistItem(
        id_playlist=pl.id_playlist, id_media=doc.id_media, sort_order=0, duration_ms=9_000,
    ))
    await db_session.commit()
    player = await _scene(db_session, org, pl)

    items = (await _resolve_sync_payload(db_session, player.id_player))["items"]
    assert len(items) == 2
    for it in items:
        assert "touch_navigation" not in it
        assert "touch_resume_after_s" not in it


@pytest.mark.asyncio
async def test_touch_navigation_survives_publish(client, headers, db_session, org):
    """Le brouillon est du JSON, les items publiés sont des LIGNES.

    Un champ recopié d'un seul côté de `apply_draft` serait posé au brouillon puis perdu à la
    publication, en silence : l'opérateur cocherait la case, la verrait cochée, et l'écran ne
    changerait pas de comportement. On exerce donc la chaîne complète jusqu'au payload.
    """
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="DocTouchApi", sync_mode="wall_clock")
    db_session.add(pl)
    await db_session.flush()
    doc = await _mk_document(db_session, org, "menu-tactile.pdf", pages=4)
    await db_session.commit()

    r = await client.post(f"/api/v1/playlists/{pl.id_playlist}/items",
                          json={"id_media": doc.id_media}, headers=headers)
    assert r.status_code == 201, r.text
    uid = r.json()["id_item"]
    assert r.json()["touch_navigation"] is False        # défaut : inerte

    r = await client.patch(f"/api/v1/playlists/{pl.id_playlist}/items/{uid}",
                           json={"touch_navigation": True, "touch_resume_after_s": 30,
                                 "duration_ms": 15000},
                           headers=headers)
    assert r.status_code == 200, r.text
    entry = next(i for i in r.json() if i["id_item"] == uid)
    assert entry["touch_navigation"] is True and entry["touch_resume_after_s"] == 30

    r = await client.post(f"/api/v1/playlists/{pl.id_playlist}/publish", headers=headers)
    assert r.status_code == 200, r.text
    row = (await db_session.execute(
        select(CmsPlaylistItem).where(CmsPlaylistItem.id_playlist == pl.id_playlist)
    )).scalar_one()
    assert row.touch_navigation is True
    assert row.touch_resume_after_s == 30

    # …et jusqu'à l'écran : les 4 pages servies le portent.
    player = await _scene(db_session, org, pl)
    items = (await _resolve_sync_payload(db_session, player.id_player))["items"]
    assert len(items) == 4
    assert all(it["touch_navigation"] is True for it in items)

    # SECONDE PUBLICATION — le cas courant, et celui qu'une première passe ne couvre pas :
    # `apply_draft` a DEUX branches (insert d'un item neuf / update d'un item déjà publié).
    # Sans ce second tour, retirer la recopie de la branche update laissait le test VERT
    # (mesuré par mutation le 2026-08-14) : un opérateur décocherait la case sur un document
    # déjà en ligne, la verrait décochée, et l'écran continuerait de se laisser feuilleter.
    # ⚠️ Après une publication le brouillon est vidé : l'item est ré-identifié par son VRAI
    # id_item (le `uid` rendu à la création est temporaire). Reprendre l'ancien uid rend 404.
    r = await client.patch(f"/api/v1/playlists/{pl.id_playlist}/items/{row.id_item}",
                           json={"touch_navigation": False}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/playlists/{pl.id_playlist}/publish", headers=headers)
    assert r.status_code == 200, r.text
    await db_session.refresh(row)
    assert row.touch_navigation is False
    items = (await _resolve_sync_payload(db_session, player.id_player))["items"]
    assert all("touch_navigation" not in it for it in items)


@pytest.mark.asyncio
async def test_media_pages_endpoint(client, headers, db_session, org):
    doc = await _mk_document(db_session, org, "menu.pdf", pages=2)
    await db_session.commit()
    r = await client.get(f"/api/v1/media/{doc.id_media}/pages", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page_count"] == 2
    assert [p["page"] for p in body["pages"]] == [1, 2]
    assert all(p["url"] for p in body["pages"])

    # Média non-document : liste vide (pas d'erreur).
    vid = await _mk_video(db_session, org, "v")
    await db_session.commit()
    r = await client.get(f"/api/v1/media/{vid.id_media}/pages", headers=headers)
    assert r.status_code == 200
    assert r.json()["page_count"] == 0


# ── Anti-coupure : jamais de pub entre les pages d'un document ─────────────────

def test_splice_never_inserts_between_document_pages():
    from types import SimpleNamespace

    from app.services.campaign_delivery import splice_ad_items

    def home(name, dur, no_ad=False):
        d = {"media": {"media_name": name}, "duration_ms": dur}
        if no_ad:
            d["no_ad_before"] = True
        return d

    # Boucle : vidéo · doc p1 · p2 · p3 (continuations marquées) · vidéo.
    home_items = [
        home("vid1", 30_000),
        home("p1", 10_000),
        home("p2", 10_000, no_ad=True),
        home("p3", 10_000, no_ad=True),
        home("vid2", 30_000),
    ]
    ad = {"media": {"media_name": "AD"}, "duration_ms": 10_000}
    # 3 pubs demandées à des positions qui tomberaient ENTRE les pages.
    ads = [(SimpleNamespace(position=p), dict(ad)) for p in (0.35, 0.45, 0.55)]
    out = splice_ad_items(home_items, ads)
    names = [i["media"]["media_name"] for i in out]
    # Aucune pub juste avant p2/p3 (frontières interdites).
    for a, b in zip(names, names[1:]):
        assert not (a == "AD" and b in ("p2", "p3")), names
    # Le doc reste d'un bloc.
    assert "p1" in names and names.index("p2") == names.index("p1") + 1
    assert names.index("p3") == names.index("p2") + 1
    # Les pubs ont glissé sur des frontières autorisées (pas toutes abandonnées).
    assert names.count("AD") >= 1


# ── Worker : conversion réelle (poppler requis) ────────────────────────────────

class _S3Stub:
    """Stub minimal : sert le PDF téléchargé, enregistre les put_object."""

    def __init__(self, pdf_bytes: bytes):
        self._pdf = pdf_bytes
        self.puts: dict[str, bytes] = {}

    def download_file(self, bucket, key, dest):
        with open(dest, "wb") as f:
            f.write(self._pdf)

    def put_object(self, Bucket, Key, Body, **kwargs):  # noqa: N803
        self.puts[Key] = Body


def _make_pdf(pages: int) -> bytes:
    import io

    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    for i in range(pages):
        c.drawString(100, 400, f"Page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler absent")
def test_process_document_pdf():
    from app.workers.media_worker import _process_document

    s3 = _S3Stub(_make_pdf(3))
    updates: dict = {}
    pages = _process_document(s3, "org/abc.pdf", "abc.pdf", {"foo": "bar"}, updates)

    assert updates["page_count"] == 3
    assert len(pages) == 3
    meta = updates["metadata"].adapted  # psycopg2 Json wrapper
    assert meta["foo"] == "bar"
    doc = meta["document"]
    assert doc["page_count"] == 3 and doc["source"] == "pdf"
    keys = [p["key"] for p in doc["pages"]]
    assert keys == [f"org/abc_pages/{i:04d}.jpg" for i in (1, 2, 3)]
    # Pages uploadées + vignette (page 1) + dimensions posées.
    for k in keys:
        assert k in s3.puts
    assert updates["thumbnail_url"] == "org/abc_thumb.jpg"
    assert updates["width"] > 0 and updates["height"] > 0
    # Checksums cohérents avec le contenu uploadé.
    import hashlib
    assert doc["pages"][0]["checksum"] == hashlib.sha256(s3.puts[keys[0]]).hexdigest()


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice absent")
def test_soffice_conversion_available():
    """Sanity : la chaîne PPTX → PDF est présente dans l'image worker (S2)."""
    import subprocess
    r = subprocess.run(["soffice", "--version"], capture_output=True, timeout=60)
    assert r.returncode == 0
