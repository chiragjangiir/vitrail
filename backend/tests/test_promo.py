"""Tests du Générateur de visuels promo — Phase 1 (docs/PLAN_GENERATEUR_PROMO.md).

Logique PURE (templates/résolution/prix/remise, conformité, HTML) + endpoints (/promo/*).
Le rendu Playwright lui-même (worker) est validé e2e sur le banc (Chromium requis).
"""

import uuid
from unittest.mock import patch

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.promo import PromoError, backgrounds, conformity, render, url_extract
from app.services.promo.templates import (
    compute_discount_pct,
    format_price,
    list_templates,
    resolve_template,
)

# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PromoOrg", org_slug=f"promo-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    """Token super-admin (bypass RBAC → passe require_permission media:create)."""
    user = CmsUser(id_org=org.id_org, email=f"adm-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole).values(role_key="CMS_SUPER_ADMIN", label="Super", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"], "locale": "fr"})


# ── Logique pure : résolution + formatage ────────────────────────────────────────

def test_format_price_fr():
    assert format_price("4,99") == "4,99 €"
    assert format_price(6.9, "USD") == "6,90 $"
    assert format_price("abc") is None


def test_compute_discount():
    assert compute_discount_pct(4.99, 6.99) == 29          # calculé
    assert compute_discount_pct(4.99, 4.99) is None        # pas de remise si égal
    assert compute_discount_pct(None, None, "30%") == 30   # explicite


def test_resolve_template_with_discount():
    r = resolve_template("fresh", "16:9", "fhd",
                         {"slogan": "Promo", "price": "4,99", "original_price": "6,99"})
    assert (r["width"], r["height"]) == (1920, 1080)
    assert r["slots"]["price"]["text"] == "4,99 €"
    assert r["slots"]["original_price"]["text"] == "6,99 €"
    assert r["slots"]["discount"]["text"] == "-29%"
    assert r["slots"]["slogan"]["text"] == "Promo"


def test_resolve_no_discount_hides_original_and_badge():
    r = resolve_template("premium", "9:16", "4k", {"price": "10"})
    assert (r["width"], r["height"]) == (2160, 3840)
    assert r["slots"]["original_price"] is None
    assert r["slots"]["discount"] is None


def test_resolve_unknown_template_raises():
    try:
        resolve_template("nope", "16:9", "fhd", {"price": "1"})
        raise AssertionError("PromoError attendue")
    except PromoError:
        pass


def test_list_templates_exposes_builtins():
    ids = {t["id"] for t in list_templates()}
    assert {"fresh", "premium"} <= ids


# ── Conformité (lisibilité) ──────────────────────────────────────────────────────

def test_conformity_valid():
    v = conformity.validate("fresh", "16:9", {"price": "4,99", "slogan": "Frais du jour"})
    assert v["valid"] is True and v["errors"] == []


def test_conformity_missing_price():
    v = conformity.validate("fresh", "16:9", {"slogan": "x"})
    assert v["valid"] is False
    assert any(e["field"] == "price" for e in v["errors"])


def test_conformity_original_not_greater():
    v = conformity.validate("fresh", "16:9", {"price": "5", "original_price": "4"})
    assert v["valid"] is False
    assert any(e["field"] == "original_price" for e in v["errors"])


def test_conformity_slogan_too_long():
    v = conformity.validate("fresh", "16:9", {"price": "1", "slogan": "A" * 200})
    assert v["valid"] is False
    assert any(e["field"] == "slogan" for e in v["errors"])


# ── Rendu HTML (compositing déterministe) ────────────────────────────────────────

def test_build_html_escapes_user_text_and_omits_missing_images():
    r = resolve_template("fresh", "16:9", "fhd", {"slogan": "A & <b>x</b>", "price": "2"})
    html = render.build_html(r, None, None)
    assert "&amp;" in html and "&lt;b&gt;" in html      # slogan échappé (anti-injection)
    assert "2,00 €" in html
    assert 'class="product"' not in html                 # pas d'image produit fournie


# ── Phase A — styling par slot (police/couleur/graisse/align/taille) ───────────────

def test_style_override_applies_font_color_weight_align_size():
    from app.services.promo import fonts
    r = resolve_template("fresh", "16:9", "fhd", {
        "price": "4,99",
        "style_overrides": {"price": {"font": "bebas-neue", "color": "#E4572E",
                                      "weight": 900, "align": "center", "size_vh": 20}},
    })
    s = r["slots"]["price"]
    assert s["font"] == "Bebas Neue"
    assert s["color"] == "#E4572E"
    assert s["weight"] == 400          # snappé au seul poids embarqué de Bebas Neue
    assert s["align"] == "center"
    assert s["font_vh"] == 20.0
    # Le CSS @font-face embarque la police choisie (base64, déterministe/offline).
    css = fonts.font_face_css(fonts.used_font_faces(r))
    assert "'Bebas Neue'" in css and "base64," in css


def test_style_override_rejects_unsafe_color_and_unknown_font():
    # Une couleur non hex/non-thème (tentative d'injection CSS) est ignorée ; police inconnue idem.
    r = resolve_template("fresh", "16:9", "fhd", {
        "price": "4,99",
        "style_overrides": {"price": {"color": "red;} body{display:none", "font": "comic-sans"}},
    })
    s = r["slots"]["price"]
    assert s.get("font") is None                 # famille inconnue non appliquée
    assert s["color"] == "accent"                # couleur d'origine du template conservée
    html = render.build_html(r, None, None)
    assert "display:none" not in html            # pas d'injection


def test_resolve_layers_sanitizes_and_sorts():
    r = resolve_template("fresh", "16:9", "fhd", {
        "price": "1",
        "layers": [
            {"type": "text", "x": 5, "y": 5, "w": 20, "h": 10, "z": 3,
             "text": "Hi", "font": "oswald", "color": "red;}x{", "weight": 900},
            {"type": "shape", "shape": "star", "z": 1, "fill": "#4875B4", "stroke_width": 2},
            {"type": "bogus"},                       # type inconnu → ignoré
            {"type": "image", "media_id": "nope"},   # media_id non entier → ignoré
        ],
    })
    ls = r["layers"]
    assert len(ls) == 2                              # bogus + image invalide écartés
    assert [layer["z"] for layer in ls] == [1, 3]   # trié par z
    text = next(x for x in ls if x["type"] == "text")
    assert text["font"] == "Oswald" and text["weight"] == 700   # snappé (Oswald n'a pas 900)
    assert text["color"] != "red;}x{"               # couleur non sûre rejetée → repli thème
    shape = next(x for x in ls if x["type"] == "shape")
    assert shape["shape"] == "rect"                 # forme inconnue → rect par défaut


def test_build_html_renders_layers():
    r = resolve_template("fresh", "16:9", "fhd", {
        "price": "1",
        "layers": [
            {"type": "text", "text": "PROMO<b>x</b>", "x": 10, "y": 10, "w": 20, "h": 8, "z": 1},
            {"type": "shape", "shape": "ellipse", "x": 40, "y": 40, "w": 10, "h": 10,
             "fill": "#E4572E", "z": 2},
        ],
    })
    html = render.build_html(r, None, None)
    assert 'class="layer"' in html
    assert "border-radius:50%" in html              # ellipse
    assert "&lt;b&gt;" in html                       # texte du calque échappé (anti-injection)


async def test_promo_fonts_endpoint(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    rf = await client.get("/api/v1/promo/fonts", headers=h)
    assert rf.status_code == 200
    ids = {f["id"] for f in rf.json()["fonts"]}
    assert {"inter", "bebas-neue", "playfair-display"} <= ids


# ── Polices custom par org (§12.7) ─────────────────────────────────────────────────

def test_detect_font_format():
    from app.services.promo import org_fonts
    assert org_fonts.detect_format(b"wOF2" + b"\x00" * 10) == "woff2"
    assert org_fonts.detect_format(b"OTTO" + b"\x00" * 10) == "otf"
    assert org_fonts.detect_format(b"\x00\x01\x00\x00" + b"\x00" * 10) == "ttf"
    assert org_fonts.detect_format(b"NOPE1234") is None


def test_org_font_catalog_grouping():
    from app.services.promo.org_fonts import _catalog_from_rows
    cat = _catalog_from_rows([
        {"id_font": 1, "family": "Acme Sans", "weight": 700, "storage_key": "k2",
         "font_format": "woff2"},
        {"id_font": 2, "family": "Acme Sans", "weight": 400, "storage_key": "k1",
         "font_format": "ttf"},
    ])
    assert set(cat) == {"org-acme-sans"}
    e = cat["org-acme-sans"]
    assert e["weights"] == [400, 700]          # trié
    assert e["source"] == "custom" and e["keys"][700] == "k2" and e["file_ids"][400] == 2


async def test_org_font_upload_list_serve_delete(client: AsyncClient, admin_token: str):
    from unittest.mock import AsyncMock

    h = {"Authorization": f"Bearer {admin_token}"}
    woff2 = b"wOF2" + b"\x00" * 200
    up = ("app.api.v1.endpoints.promo.upload_file", AsyncMock())
    dl = ("app.api.v1.endpoints.promo.download_file", AsyncMock(return_value=woff2))
    de = ("app.api.v1.endpoints.promo.delete_file", AsyncMock())
    with patch(up[0], up[1]), patch(dl[0], dl[1]), patch(de[0], de[1]):
        # attestation de licence obligatoire
        r0 = await client.post("/api/v1/promo/fonts/upload", headers=h,
                               files={"file": ("acme.woff2", woff2, "font/woff2")},
                               data={"family": "Acme Sans", "weight": "700",
                                     "license_ack": "false"})
        assert r0.status_code == 400
        # upload valide
        r = await client.post("/api/v1/promo/fonts/upload", headers=h,
                              files={"file": ("acme.woff2", woff2, "font/woff2")},
                              data={"family": "Acme Sans", "weight": "700", "license_ack": "true"})
        assert r.status_code == 201
        id_font = r.json()["id_font"]
        # le catalogue inclut la police custom, groupée par famille
        fonts_list = (await client.get("/api/v1/promo/fonts", headers=h)).json()["fonts"]
        custom = [f for f in fonts_list if f["id"] == "org-acme-sans"]
        assert custom and 700 in custom[0]["weights"] and custom[0]["category"] == "custom"
        # sert les octets (même origine → FontFace API)
        ff = await client.get(f"/api/v1/promo/fonts/file/{id_font}", headers=h)
        assert ff.status_code == 200 and ff.content == woff2
        # suppression
        dd = await client.delete(f"/api/v1/promo/fonts/{id_font}", headers=h)
        assert dd.status_code == 204
        fonts_after = (await client.get("/api/v1/promo/fonts", headers=h)).json()["fonts"]
        assert not [f for f in fonts_after if f["id"] == "org-acme-sans"]


async def test_promo_saved_templates_crud(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    cfg = {"template_id": "fresh", "format": "16:9", "resolution": "fhd",
           "inputs": {"price": "4,99", "layers": [{"type": "shape", "shape": "rect"}]}}
    r = await client.post("/api/v1/promo/saved", headers=h,
                          json={"name": "Mon promo", "config": cfg})
    assert r.status_code == 201
    sid = r.json()["id_promo_template"]
    lst = (await client.get("/api/v1/promo/saved", headers=h)).json()
    assert any(x["id_promo_template"] == sid and x["name"] == "Mon promo" for x in lst)
    got = (await client.get(f"/api/v1/promo/saved/{sid}", headers=h)).json()
    assert got["config"]["template_id"] == "fresh" and got["config"]["inputs"]["price"] == "4,99"
    u = await client.put(f"/api/v1/promo/saved/{sid}", headers=h, json={"name": "Renommé"})
    assert u.status_code == 200 and u.json()["name"] == "Renommé"
    d = await client.delete(f"/api/v1/promo/saved/{sid}", headers=h)
    assert d.status_code == 204
    assert (await client.get(f"/api/v1/promo/saved/{sid}", headers=h)).status_code == 404


# ── Endpoints ────────────────────────────────────────────────────────────────────

async def test_promo_templates_and_presets(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    rt = await client.get("/api/v1/promo/templates", headers=h)
    assert rt.status_code == 200
    assert {t["id"] for t in rt.json()["templates"]} >= {"fresh", "premium"}
    rp = await client.get("/api/v1/promo/presets", headers=h)
    assert rp.status_code == 200 and len(rp.json()["presets"]) > 0


async def test_promo_validate_endpoint(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    ok = await client.post("/api/v1/promo/validate", headers=h,
                           json={"template_id": "fresh", "format": "16:9",
                                 "inputs": {"price": "4,99"}})
    assert ok.status_code == 200 and ok.json()["valid"] is True
    ko = await client.post("/api/v1/promo/validate", headers=h,
                           json={"template_id": "fresh", "format": "16:9",
                                 "inputs": {"price": "5", "original_price": "4"}})
    assert ko.status_code == 200 and ko.json()["valid"] is False


async def test_promo_image_creates_job(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    with patch("app.workers.promo_worker.render_promo_image.delay") as mock:
        r = await client.post("/api/v1/promo/image", headers=h, json={
            "template_id": "fresh", "format": "16:9", "resolution": "fhd",
            "inputs": {"slogan": "Frais", "price": "4,99", "original_price": "6,99"},
        })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == "promo_image" and body["status"] == "pending"
    mock.assert_called_once_with(body["id_job"])


async def test_promo_image_rejects_non_conform(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post("/api/v1/promo/image", headers=h, json={
        "template_id": "fresh", "format": "16:9",
        "inputs": {"price": "5", "original_price": "4"},   # barré < prix → non conforme
    })
    assert r.status_code == 422


# ── Détourage produit (Phase 3) ──────────────────────────────────────────────────

async def _add_image(db_session, id_org, *, sha, metadata=None) -> CmsMedia:
    m = CmsMedia(
        id_org=id_org, media_name="produit", media_type="image", mime_type="image/png",
        storage_key=f"{id_org}/{uuid.uuid4().hex}.png", checksum_sha256=sha,
        source="upload", transcode_status="done", media_metadata=metadata or {},
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


async def test_cutout_404_unknown_source(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post("/api/v1/promo/cutout", headers=h, json={"source_media_id": 999999})
    assert r.status_code == 404


async def test_cutout_400_without_fal_key(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, admin_token: str,
):
    src = await _add_image(db_session, org.id_org, sha="src-sha-nokey")
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post("/api/v1/promo/cutout", headers=h, json={"source_media_id": src.id_media})
    assert r.status_code == 400   # cache miss → pas de clé fal → 400


async def test_cutout_cache_hit_returns_existing(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, admin_token: str,
):
    # Source + un détourage déjà produit pour son checksum → réutilisé sans appeler fal.
    src = await _add_image(db_session, org.id_org, sha="cached-src-sha")
    cutout = await _add_image(db_session, org.id_org, sha="cutout-sha",
                              metadata={"cutout": {"source_sha256": "cached-src-sha"}})
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post("/api/v1/promo/cutout", headers=h, json={"source_media_id": src.id_media})
    assert r.status_code == 201, r.text
    assert r.json()["id_media"] == cutout.id_media   # renvoie le cache, pas un nouveau média


# ── Fond IA (Phase 4) ────────────────────────────────────────────────────────────

def test_build_background_prompt():
    prompt, neg = backgrounds.build_background_prompt("premium", "édition limitée", "right")
    assert "elegant dark" in prompt          # fragment de l'ambiance
    assert "édition limitée" in prompt       # description libre
    assert "right side" in prompt            # zone calme
    assert "no text" in prompt
    assert "product" in neg and "text" in neg and "people" in neg   # négatif systématique


def test_build_background_prompt_unknown_ambiance():
    prompt, _ = backgrounds.build_background_prompt("nope", None, None)
    assert "promotional background" in prompt   # garde-fou constant, jamais vide


def test_list_ambiances():
    assert len(backgrounds.list_ambiances()) >= 4
    assert all("id" in a and "label" in a for a in backgrounds.list_ambiances())


async def test_promo_ambiances_endpoint(client: AsyncClient, admin_token: str):
    r = await client.get("/api/v1/promo/ambiances",
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200 and len(r.json()["ambiances"]) >= 4


async def test_promo_background_400_without_fal_key(client: AsyncClient, admin_token: str):
    r = await client.post("/api/v1/promo/background",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"ambiance_id": "fresh", "format": "16:9"})
    assert r.status_code == 400


# ── Extraction URL produit (Phase 5) ─────────────────────────────────────────────

def test_extract_json_ld():
    html = (
        '<html><head><title>Fallback</title>'
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Café Bio","brand":{"name":"MarqueX"},'
        '"image":"/img/c.jpg","description":"Arabica",'
        '"offers":{"price":"4.99","priceCurrency":"EUR"}}</script></head></html>'
    )
    d = url_extract.extract_product(html, "https://shop.example.com/p")
    assert d["name"] == "Café Bio" and d["brand"] == "MarqueX"
    assert d["price"] == "4.99" and d["currency"] == "EUR"
    assert d["image_url"] == "https://shop.example.com/img/c.jpg"   # relatif → absolu
    assert d["description"] == "Arabica"


def test_extract_open_graph_fallback():
    html = ('<html><head>'
            '<meta property="og:title" content="Super Produit">'
            '<meta property="og:image" content="https://x.com/p.png">'
            '<meta property="product:price:amount" content="9,90">'
            '<meta property="product:price:currency" content="EUR">'
            '</head></html>')
    d = url_extract.extract_product(html)
    assert d["name"] == "Super Produit"
    assert d["image_url"] == "https://x.com/p.png"
    assert d["price"] == "9,90" and d["currency"] == "EUR"


def test_extract_title_fallback_only():
    d = url_extract.extract_product("<html><head><title>Juste un titre</title></head></html>")
    assert d["name"] == "Juste un titre"
    assert d["price"] is None and d["image_url"] is None


async def test_extract_url_rejects_internal(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post("/api/v1/promo/extract-url", headers=h, json={"url": "http://localhost/x"})
    assert r.status_code == 400
    r2 = await client.post("/api/v1/promo/import-image", headers=h,
                           json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r2.status_code == 400


# ── Vidéo (Phase 6) ──────────────────────────────────────────────────────────────

def test_kenburns_cmd_clamps_and_animates():
    from app.workers.promo_worker import _kenburns_cmd
    zoom = _kenburns_cmd("i.png", "o.mp4", 1920, 1080, 100, "zoom_in")   # durée > 15 → clampée
    assert "-t" in zoom and "15.00" in zoom
    assert "zoompan" in " ".join(zoom) and "libx264" in zoom
    static = _kenburns_cmd("i.png", "o.mp4", 1920, 1080, 1, "static")    # durée < 3 → 3.00
    assert "3.00" in static and "zoompan" not in " ".join(static)


async def test_promo_video_creates_job(client: AsyncClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    with patch("app.workers.promo_worker.render_promo_video.delay") as mock:
        r = await client.post("/api/v1/promo/video", headers=h, json={
            "template_id": "fresh", "format": "16:9",
            "inputs": {"slogan": "Vid", "price": "4,99"},
            "duration_s": 6, "animation": "zoom_in",
        })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == "promo_video" and body["status"] == "pending"
    mock.assert_called_once_with(body["id_job"])


async def test_promo_video_rejects_non_conform(client: AsyncClient, admin_token: str):
    r = await client.post("/api/v1/promo/video", headers={"Authorization": f"Bearer {admin_token}"},
                          json={"template_id": "fresh", "format": "16:9",
                                "inputs": {"price": "5", "original_price": "4"}})
    assert r.status_code == 422
