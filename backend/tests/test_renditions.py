"""Tests renditions adaptatives (« artefacts » vidéo).

Couvre :
  - service pur : parse hauteur, capacité écran, cible player (écran ∩ décodage),
    sélection de variante (originale + renditions) selon la cible.
  - résolution runtime : _resolve_variant_key + _resolve_sync_payload servent la
    rendition adaptée (FHD) au lieu de l'originale 4K ; repli sur l'originale.
  - règle LAN sync : la cible d'un membre = min du groupe.
  - endpoints : GET/POST/DELETE renditions + validations.
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.ws as ws
from app.api.v1.endpoints.ws import (
    _build_prefetch,
    _player_prefers_hevc,
    _player_target_height,
    _resolve_sync_payload,
    _resolve_variant_key,
)
from app.core.security import hash_password
from app.models.media import CmsMedia, CmsMediaRendition
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services import renditions as R


# ── Service pur ────────────────────────────────────────────────────────────────

def test_parse_height():
    assert R._parse_height("3840x2160@60") == 2160
    assert R._parse_height("1920x1080") == 1080
    assert R._parse_height("1080x1920@30") == 1920  # portrait
    assert R._parse_height("garbage") is None
    assert R._parse_height(None) is None


def test_display_max_height_modes_priority():
    caps = {"display_modes": ["1920x1080@60", "3840x2160@30", "1280x720@60"]}
    assert R.display_max_height(caps, {"screen_resolution": "1920x1080"}) == 2160


def test_display_max_height_fallback_screen_resolution():
    assert R.display_max_height({}, {"screen_resolution": "1920x1080"}) == 1080
    assert R.display_max_height(None, None) is None


def test_player_target_height_panel_only():
    # Écran 4K, décodage inconnu (pas de capabilities décodage) → pas de bridage décodage
    p = CmsPlayer(player_os="linux", display_config={"screen_resolution": "3840x2160"})
    assert R.player_target_height(p) == 2160


def test_player_target_height_software_decode_caps_to_1080():
    # Écran 4K mais décodage logiciel confirmé → plafonné à 1080
    p = CmsPlayer(
        player_os="linux",
        display_config={"screen_resolution": "3840x2160"},
        capabilities={"hw_decode": "vaapi", "hw_decode_active": False},
    )
    assert R.player_target_height(p) == 1080


def test_player_target_height_hardware_keeps_panel():
    p = CmsPlayer(
        player_os="android",
        capabilities={
            "hw_decode": "mediacodec", "hw_decode_active": True,
            "display_modes": ["3840x2160@60"],
        },
    )
    assert R.player_target_height(p) == 2160


def test_player_target_height_mpv_standalone_serves_4k():
    """Player mpv (VAAPI HW hors Chromium) hors groupe LAN sur écran 4K → 4K servie.

    Forme réelle du heartbeat en mode video_renderer=mpv : detect-capabilities pose
    hw_decode='vaapi' (méthode) et le bloc mpv force hw_decode_active=true → décodage
    classé matériel → le plafond logiciel 1080 ne s'applique pas. Cf. item #4 (4K HW
    hors groupe LAN) (mpv = standalone).
    """
    from app.services import player_capabilities as PC
    caps = {"hw_decode": "vaapi", "hw_decode_active": True,
            "mpv_vaapi": True, "decode_via": "mpv",
            "display_modes": ["3840x2160@60"]}
    p = CmsPlayer(player_os="linux", capabilities=caps)  # pas de lan_sync_group
    assert PC.decode_health(p)["effective_decode"] == "hardware"
    assert R.player_target_height(p) == 2160


def test_player_target_height_chromeos_native_uses_panel():
    """ChromeOS PWA : chromium-native = matériel → cible = définition écran (intentionnel).

    Le bridge remonte display_modes (résolution physique de l'écran). Un Chromebox 1080p
    reçoit donc du FHD, un 4K reçoit du 4K — fini le « 4K servi par défaut » faute de
    capacité connue. Cf. backlog ChromeOS UI CMS.
    """
    p1080 = CmsPlayer(player_os="chromeos", capabilities={
        "hw_decode": "chromium-native", "platform": "chromeos",
        "display_modes": ["1920x1080"]})
    assert R.player_target_height(p1080) == 1080
    p4k = CmsPlayer(player_os="chromeos", capabilities={
        "hw_decode": "chromium-native", "platform": "chromeos",
        "display_modes": ["3840x2160"]})
    assert R.player_target_height(p4k) == 2160


def test_player_target_height_chromeos_no_modes_serves_original():
    """ChromeOS sans display_modes remonté (vieux bridge) → None = originale (repli sûr)."""
    p = CmsPlayer(player_os="chromeos", capabilities={
        "hw_decode": "chromium-native", "platform": "chromeos"})
    assert R.player_target_height(p) is None


def test_player_target_height_unknown():
    p = CmsPlayer(player_os="linux")
    assert R.player_target_height(p) is None


def test_select_variant_picks_fhd_for_1080_target():
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    v = R.select_variant(2160, "k.mp4", rends, 1080)
    assert v["storage_key"] == "k.fhd.mp4" and v["profile"] == "fhd"


def test_select_variant_original_when_target_none():
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    v = R.select_variant(2160, "k.mp4", rends, None)
    assert v["storage_key"] == "k.mp4" and v["profile"] is None


def test_select_variant_original_when_fits_target():
    # Cible 4K, originale 4K tient → on garde l'originale (la plus haute déf qui tient)
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    v = R.select_variant(2160, "k.mp4", rends, 2160)
    assert v["profile"] is None


def test_select_variant_smallest_when_nothing_fits():
    # Cible 480 plus petite que tout → la plus petite disponible (FHD)
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    v = R.select_variant(2160, "k.mp4", rends, 480)
    assert v["storage_key"] == "k.fhd.mp4"


def test_select_variant_browser_only_excludes_mkv_original():
    # Player navigateur (<video> Chromium) : l'originale 4K .mkv est ILLISIBLE → on sert la
    # rendition FHD .mp4 même si la cible 4K « préférerait » l'originale (cas Acer ChromeOS).
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    # Sans browser_only → originale .mkv (4K tient sous la cible)
    assert R.select_variant(2160, "k.mkv", rends, 2160)["storage_key"] == "k.mkv"
    # Avec browser_only → la .mkv est exclue → FHD .mp4
    v = R.select_variant(2160, "k.mkv", rends, 2160, browser_only=True)
    assert v["storage_key"] == "k.fhd.mp4" and v["profile"] == "fhd"


def test_select_variant_browser_only_keeps_mp4_original():
    # Originale déjà .mp4 (codec non-HEVC) → browser_only ne change rien (4K reste éligible).
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd"}]
    v = R.select_variant(2160, "k.mp4", rends, 2160, browser_only=True)
    assert v["storage_key"] == "k.mp4" and v["profile"] is None


def test_select_variant_browser_only_excludes_hevc_in_mp4():
    # Parent HEVC EN .mp4 : conteneur navigateur-safe MAIS codec illisible par Chromium 83
    # (cas Minix WebView). browser_only doit servir la rendition FHD H.264, pas le parent HEVC.
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd", "codec": "h264"}]
    v = R.select_variant(2160, "k.mp4", rends, 2160, original_codec="hevc", browser_only=True)
    assert v["storage_key"] == "k.fhd.mp4" and v["codec"] == "h264"
    # Sans browser_only (player exo/mpv natif) → le parent HEVC 4K reste servi.
    v2 = R.select_variant(2160, "k.mp4", rends, 2160, original_codec="hevc")
    assert v2["storage_key"] == "k.mp4"


def test_is_browser_unsafe_codec():
    assert R.is_browser_unsafe_codec("hevc") is True
    assert R.is_browser_unsafe_codec("HVC1") is True
    assert R.is_browser_unsafe_codec("h264") is False
    assert R.is_browser_unsafe_codec(None) is False


def test_select_variant_browser_hevc_capable_keeps_4k_hevc():
    # Player navigateur QUI DÉCLARE décoder le HEVC (ChromeOS récent) : on garde le parent
    # HEVC 4K (pas de rétrogradation FHD), tout en gardant le filtre conteneur (mp4).
    rends = [{"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd", "codec": "h264"}]
    v = R.select_variant(2160, "k.mp4", rends, 2160, original_codec="hevc",
                         browser_only=True, allow_hevc=True)
    assert v["storage_key"] == "k.mp4" and v["codec"] == "hevc"
    # …mais une originale .mkv reste exclue même si HEVC autorisé (conteneur illisible <video>).
    v2 = R.select_variant(2160, "k.mkv", rends, 2160, original_codec="hevc",
                          browser_only=True, allow_hevc=True)
    assert v2["storage_key"] == "k.fhd.mp4"


def test_browser_safe_container():
    assert R._browser_safe_container("a/b.mp4") is True
    assert R._browser_safe_container("a/b.webm") is True
    assert R._browser_safe_container("a/b.mkv") is False
    assert R._browser_safe_container("a/b.mov") is False
    assert R._browser_safe_container("noext") is True   # legacy sans extension → supposé safe


# ── Fixtures DB ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RND", org_slug=f"rnd-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture(autouse=True)
def _stub_signed_url(monkeypatch):
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")


async def _make_4k_video_with_fhd(db, org) -> CmsMedia:
    m = CmsMedia(
        id_org=org.id_org, media_name="clip4k", media_type="video", mime_type="video/mp4",
        storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        duration_ms=5000, width=3840, height=2160, source="upload",
        transcode_status="done", has_renditions=True,
    )
    db.add(m)
    await db.flush()
    db.add(CmsMediaRendition(
        id_parent=m.id_media, profile="fhd", width=1920, height=1080,
        codec="h264", storage_key=f"v/{m.id_media}.fhd.mp4", status="ready",
    ))
    await db.commit()
    await db.refresh(m)
    return m


# ── Résolution runtime ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_variant_key_fhd_player(db_session, org):
    media = await _make_4k_video_with_fhd(db_session, org)
    # Cible 1080 → la rendition FHD
    key = await _resolve_variant_key(db_session, media, 1080)
    assert key.endswith(".fhd.mp4")
    # Cible inconnue → l'originale
    key = await _resolve_variant_key(db_session, media, None)
    assert key == media.storage_key


@pytest.mark.asyncio
async def test_resolve_variant_hevc_parent_browser_gets_fhd(db_session, org):
    """Parent HEVC 4K (en .mp4) + player navigateur (Minix WebView) → rendition FHD H.264,
    JAMAIS le parent HEVC (Chromium 83 ne le décode pas), même à cible inconnue."""
    media = await _make_4k_video_with_fhd(db_session, org)
    media.media_metadata = {"video": {"codec": "hevc", "width": 3840, "height": 2160}}
    await db_session.commit()
    await db_session.refresh(media)

    # Player navigateur SANS capacité HEVC (WebView Chromium 83) : cible 4K ET inconnue → FHD H.264.
    assert (await _resolve_variant_key(db_session, media, 2160, browser_only=True)).endswith(".fhd.mp4")
    assert (await _resolve_variant_key(db_session, media, None, browser_only=True)).endswith(".fhd.mp4")
    # Player navigateur HEVC-capable (ChromeOS récent) : garde le parent HEVC 4K.
    assert (await _resolve_variant_key(db_session, media, 2160, browser_only=True, allow_hevc=True)) == media.storage_key
    assert (await _resolve_variant_key(db_session, media, None, browser_only=True, allow_hevc=True)) == media.storage_key
    # Player natif (exo/mpv) → le parent HEVC 4K reste servi.
    assert (await _resolve_variant_key(db_session, media, 2160)) == media.storage_key


def test_select_variant_prefers_hevc_when_requested():
    rends = [
        {"height": 2160, "storage_key": "k.hevc_4k.mp4", "profile": "hevc_4k", "codec": "hevc"},
        {"height": 1080, "storage_key": "k.fhd.mp4", "profile": "fhd", "codec": "h264"},
    ]
    # Player ExoPlayer (prefer hevc) sur écran 4K → la variante HEVC 4K (pas l'originale h264)
    v = R.select_variant(2160, "orig.mkv", rends, 2160, prefer_codec="hevc", original_codec="h264")
    assert v["storage_key"] == "k.hevc_4k.mp4" and v["codec"] == "hevc"
    # Sans préférence → comportement INCHANGÉ : la plus haute (l'originale 2160 d'abord)
    v2 = R.select_variant(2160, "orig.mkv", rends, 2160)
    assert v2["profile"] is None and v2["height"] == 2160
    # Prefer hevc mais cible 1080 → aucune HEVC ne tient → la fitting h264 (fhd 1080)
    v3 = R.select_variant(2160, "orig.mkv", rends, 1080, prefer_codec="hevc", original_codec="h264")
    assert v3["storage_key"] == "k.fhd.mp4"


def test_player_prefers_hevc():
    exo = CmsPlayer(player_os="android", display_config={"video_renderer": "exo"},
                    capabilities={"codecs": ["h264", "hevc"]})
    assert _player_prefers_hevc(exo) == "hevc"
    # Mode WebView (pas exo) → pas de HEVC (la WebView ne le décode pas)
    wv = CmsPlayer(player_os="android", display_config={},
                   capabilities={"codecs": ["h264", "hevc"]})
    assert _player_prefers_hevc(wv) is None
    # exo mais aucun décodeur hevc déclaré → None
    exo_noh = CmsPlayer(player_os="android", display_config={"video_renderer": "exo"},
                        capabilities={"codecs": ["h264"]})
    assert _player_prefers_hevc(exo_noh) is None


@pytest.mark.asyncio
async def test_resolve_variant_key_exo_player_gets_hevc(db_session, org):
    m = await _make_4k_video_with_fhd(db_session, org)
    db_session.add(CmsMediaRendition(
        id_parent=m.id_media, profile="hevc_4k", width=3840, height=2160,
        codec="hevc", storage_key=f"v/{m.id_media}.hevc_4k.mp4", status="ready",
    ))
    await db_session.commit()
    # Player ExoPlayer 4K (prefer hevc) → la rendition HEVC 4K (pas l'originale h264)
    key = await _resolve_variant_key(db_session, m, 2160, "hevc")
    assert key.endswith(".hevc_4k.mp4")
    # Sans préférence (target 2160) → l'originale 4K (h264)
    key2 = await _resolve_variant_key(db_session, m, 2160)
    assert key2 == m.storage_key


@pytest.mark.asyncio
async def test_resolve_variant_key_no_renditions(db_session, org):
    m = CmsMedia(
        id_org=org.id_org, media_name="plain", media_type="video",
        storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256="x",
        width=3840, height=2160, transcode_status="done", has_renditions=False,
    )
    db_session.add(m)
    await db_session.commit()
    key = await _resolve_variant_key(db_session, m, 1080)
    assert key == m.storage_key


async def _scene_event(db, org, player, media):
    """Event content actif ciblant le player avec un média unique (chemin id_media)."""
    from app.models.event import CmsEvent
    from datetime import UTC, datetime
    ev = CmsEvent(
        id_org=org.id_org, event_name="E", event_type="manual", event_kind="content", status="active",
        id_media=media.id_media, priority=10, duration_ms=5000,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        activated_at=datetime.now(UTC),
    )
    db.add(ev)
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_sync_payload_serves_fhd_to_1080_panel(db_session, org):
    media = await _make_4k_video_with_fhd(db_session, org)
    player = CmsPlayer(id_org=org.id_org, player_name="FHD", player_os="linux",
                       display_config={"screen_resolution": "1920x1080"})
    db_session.add(player)
    await db_session.commit()
    await _scene_event(db_session, org, player, media)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    m = payload["items"][0]["media"]
    assert m["url"].endswith(".fhd.mp4")
    # Offline-first : la clé de cache = la rendition servie (pas le parent) ; pas de
    # checksum d'intégrité tant que la rendition n'a pas son propre sha.
    assert m["cache_key"].endswith(".fhd.mp4")
    assert m["cache_checksum"] is None
    # Repli offline : on sert une rendition → le parent (4K) est proposé en repli pour
    # éviter l'écran noir si la rendition n'est pas (encore) cachée et serveur down.
    assert m["cache_key_fallback"] == media.storage_key
    assert m["cache_checksum_fallback"] == media.checksum_sha256


@pytest.mark.asyncio
async def test_sync_payload_includes_player_name_for_overlay(db_session, org):
    """L'overlay de maintenance lit player_name (+ playlist_name) dans le payload."""
    media = await _make_4k_video_with_fhd(db_session, org)
    player = CmsPlayer(id_org=org.id_org, player_name="Mur-Nord", player_os="linux",
                       display_config={"screen_resolution": "1920x1080"})
    db_session.add(player)
    await db_session.commit()
    # Payload vide (rien programmé) : player_name présent quand même
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["player_name"] == "Mur-Nord"
    # Payload event (single media) : player_name présent
    await _scene_event(db_session, org, player, media)
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["player_name"] == "Mur-Nord"


@pytest.mark.asyncio
async def test_sync_payload_serves_original_to_4k_panel(db_session, org):
    media = await _make_4k_video_with_fhd(db_session, org)
    player = CmsPlayer(
        id_org=org.id_org, player_name="UHD", player_os="android",
        capabilities={"hw_decode": "mediacodec", "hw_decode_active": True,
                      "display_modes": ["3840x2160@60"]},
    )
    db_session.add(player)
    await db_session.commit()
    await _scene_event(db_session, org, player, media)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    m = payload["items"][0]["media"]
    assert m["url"].endswith(media.storage_key)  # originale 4K
    # Offline-first : on sert le parent → clé de cache = storage_key parent + checksum
    # d'intégrité présent (sha du parent).
    assert m["cache_key"] == media.storage_key
    assert m["cache_checksum"] == media.checksum_sha256
    # On sert déjà le parent → pas de repli (la clé servie EST le parent).
    assert m["cache_key_fallback"] is None
    assert m["cache_checksum_fallback"] is None


# ── Règle LAN sync : min du groupe ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lan_group_target_is_group_min(db_session, org):
    # A = écran 4K (cible 2160 seul), B = écran FHD (cible 1080) ; même groupe LAN
    a = CmsPlayer(id_org=org.id_org, player_name="A", player_os="android",
                  display_config={"lan_sync_enabled": True, "lan_sync_group": "wall",
                                  "screen_resolution": "3840x2160"})
    b = CmsPlayer(id_org=org.id_org, player_name="B", player_os="linux",
                  display_config={"lan_sync_enabled": True, "lan_sync_group": "wall",
                                  "screen_resolution": "1920x1080"})
    db_session.add_all([a, b])
    await db_session.commit()

    # A seul vaudrait 2160, mais dans le groupe il prend le min (1080)
    assert await _player_target_height(db_session, a) == 1080
    assert await _player_target_height(db_session, b) == 1080


@pytest.mark.asyncio
async def test_lan_different_group_not_constrained(db_session, org):
    a = CmsPlayer(id_org=org.id_org, player_name="A", player_os="android",
                  display_config={"lan_sync_enabled": True, "lan_sync_group": "wallA",
                                  "screen_resolution": "3840x2160"})
    b = CmsPlayer(id_org=org.id_org, player_name="B", player_os="linux",
                  display_config={"lan_sync_enabled": True, "lan_sync_group": "wallB",
                                  "screen_resolution": "1920x1080"})
    db_session.add_all([a, b])
    await db_session.commit()
    assert await _player_target_height(db_session, a) == 2160


# ── Endpoints ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"rnd-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_RND_{uid}", label="RND", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("media", "read"), ("media", "edit"), ("media", "delete")]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_endpoints_list_generate_delete(client, db_session, org, auth_token):
    h = {"Authorization": f"Bearer {auth_token}"}
    media = await _make_4k_video_with_fhd(db_session, org)

    # GET : la rendition FHD existe déjà
    r = await client.get(f"/api/v1/media/{media.id_media}/renditions", headers=h)
    assert r.status_code == 200
    assert [x["profile"] for x in r.json()] == ["fhd"]

    # POST : régénère la rendition FHD (idempotent) — passe à pending, enqueue le worker
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        r = await client.post(f"/api/v1/media/{media.id_media}/renditions",
                              json={"profile": "fhd"}, headers=h)
    assert r.status_code == 202
    assert r.json()["status"] == "pending"
    mock_delay.assert_called_once_with(media.id_media, "fhd")

    # DELETE : supprime l'artefact + recalcule has_renditions
    rend_id = r.json()["id_rendition"]
    with patch("app.workers.media_worker.delete_media_files.delay"):
        r = await client.delete(
            f"/api/v1/media/{media.id_media}/renditions/{rend_id}", headers=h)
    assert r.status_code == 204
    m = (await db_session.execute(
        select(CmsMedia).where(CmsMedia.id_media == media.id_media)
    )).scalar_one()
    await db_session.refresh(m)
    assert m.has_renditions is False


@pytest.mark.asyncio
async def test_generate_rejects_non_video(client, db_session, org, auth_token):
    h = {"Authorization": f"Bearer {auth_token}"}
    img = CmsMedia(id_org=org.id_org, media_name="img", media_type="image",
                   storage_key="i/x.jpg", checksum_sha256="z", transcode_status="done")
    db_session.add(img)
    await db_session.commit()
    r = await client.post(f"/api/v1/media/{img.id_media}/renditions",
                          json={"profile": "fhd"}, headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_generate_rejects_source_not_bigger(client, db_session, org, auth_token):
    h = {"Authorization": f"Bearer {auth_token}"}
    small = CmsMedia(id_org=org.id_org, media_name="small", media_type="video",
                     storage_key="v/s.mp4", checksum_sha256="z", width=1280, height=720,
                     transcode_status="done")
    db_session.add(small)
    await db_session.commit()
    r = await client.post(f"/api/v1/media/{small.id_media}/renditions",
                          json={"profile": "fhd"}, headers=h)
    assert r.status_code == 422


# ── Conformité §XVI.2 : auto-rendition à l'affectation (alerte + auto-génération) ──

async def _audience_scene(db, org, media, screen="1920x1080"):
    """Player + playlist + schedule ciblant le player. Renvoie (player, playlist)."""
    player = CmsPlayer(id_org=org.id_org, player_name="aud", player_os="linux",
                       display_config={"screen_resolution": screen})
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P")
    db.add_all([player, pl])
    await db.flush()
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db.add(sched)
    await db.flush()
    db.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                             target_id=player.id_player))
    await db.commit()
    return player, pl


@pytest.mark.asyncio
async def test_conformance_autogen_for_4k_on_fhd_audience(db_session, org):
    from app.api.v1.endpoints.playlists import _conformance_autogen
    media = CmsMedia(id_org=org.id_org, media_name="clip4k", media_type="video",
                     mime_type="video/mp4", storage_key=f"v/{uuid.uuid4().hex}.mp4",
                     checksum_sha256=uuid.uuid4().hex, duration_ms=5000,
                     width=3840, height=2160, source="upload", transcode_status="done")
    db_session.add(media)
    await db_session.flush()
    _, pl = await _audience_scene(db_session, org, media)
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        adv = await _conformance_autogen(db_session, org.id_org, pl.id_playlist, media)
    assert adv == {"id_media": media.id_media, "media_height": 2160,
                   "target_height": 1080, "action": "generating"}
    mock_delay.assert_called_once_with(media.id_media, "fhd")


@pytest.mark.asyncio
async def test_conformance_no_advisory_when_media_fits(db_session, org):
    from app.api.v1.endpoints.playlists import _conformance_autogen
    media = CmsMedia(id_org=org.id_org, media_name="fhd", media_type="video",
                     storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256="z",
                     width=1920, height=1080, source="upload", transcode_status="done")
    db_session.add(media)
    await db_session.flush()
    _, pl = await _audience_scene(db_session, org, media)
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        adv = await _conformance_autogen(db_session, org.id_org, pl.id_playlist, media)
    assert adv is None
    mock_delay.assert_not_called()


@pytest.mark.asyncio
async def test_conformance_no_advisory_without_audience(db_session, org):
    """Playlist sans schedule (aucune audience résoluble) → pas de contrôle."""
    from app.api.v1.endpoints.playlists import _conformance_autogen
    media = CmsMedia(id_org=org.id_org, media_name="clip4k", media_type="video",
                     storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256="z",
                     width=3840, height=2160, source="upload", transcode_status="done")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="orphan")
    db_session.add_all([media, pl])
    await db_session.commit()
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        adv = await _conformance_autogen(db_session, org.id_org, pl.id_playlist, media)
    assert adv is None
    mock_delay.assert_not_called()


@pytest.mark.asyncio
async def test_conformance_check_playlist_flags_only_oversized(db_session, org):
    """conformance_check_playlist (affectation) : sur une playlist mixte, seul le média
    plus haut que la cible de l'audience est signalé + généré ; le FHD est laissé."""
    from app.api.v1.endpoints.playlists import conformance_check_playlist
    big = CmsMedia(id_org=org.id_org, media_name="clip4k", media_type="video",
                   storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
                   width=3840, height=2160, source="upload", transcode_status="done")
    small = CmsMedia(id_org=org.id_org, media_name="clipfhd", media_type="video",
                     storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
                     width=1920, height=1080, source="upload", transcode_status="done")
    db_session.add_all([big, small])
    await db_session.flush()
    _, pl = await _audience_scene(db_session, org, big)   # player FHD + schedule ciblant la playlist
    db_session.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=big.id_media, sort_order=0, duration_ms=5000),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=small.id_media, sort_order=1, duration_ms=5000),
    ])
    await db_session.commit()
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        advisories = await conformance_check_playlist(db_session, org.id_org, pl.id_playlist)
    assert advisories == [{"id_media": big.id_media, "media_height": 2160,
                           "target_height": 1080, "action": "generating"}]
    mock_delay.assert_called_once_with(big.id_media, "fhd")


# ── §25.4 : un template multi-zones force la variante navigateur-safe ─────────────

async def _scene_playlist_event(db, org, player, media, zones, zone_index=0):
    """Event content actif ciblant le player avec une playlist liée à un template (zones)."""
    from datetime import UTC, datetime

    from app.models.event import CmsEvent
    from app.models.template import CmsTemplate

    tmpl = CmsTemplate(id_org=org.id_org, template_name="T",
                       layout={"layout_type": "split_v", "zones": zones})
    db.add(tmpl)
    await db.flush()
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P", id_template=tmpl.id_template,
                     sync_mode="loop")
    db.add(pl)
    await db.flush()
    db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                           sort_order=0, zone_index=zone_index, duration_ms=5000))
    ev = CmsEvent(
        id_org=org.id_org, event_name="E", event_type="manual", event_kind="content",
        status="active", id_playlist=pl.id_playlist, priority=10,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        activated_at=datetime.now(UTC),
    )
    db.add(ev)
    await db.commit()
    return pl


@pytest.mark.asyncio
async def test_multizone_playlist_forces_browser_safe_variant(db_session, org):
    """§25.4 : un template MULTI-zones est rendu en Chromium <video> côté player → même un
    player mpv reçoit la rendition navigateur-safe (FHD H.264), JAMAIS le parent HEVC/MKV
    injouable dans une zone. Hors zone (mono-zone), le player mpv garderait son parent HEVC."""
    media = await _make_4k_video_with_fhd(db_session, org)
    media.media_metadata = {"video": {"codec": "hevc", "width": 3840, "height": 2160}}
    await db_session.commit()
    # Player mpv (rendu natif hors zone) sur écran 1080.
    player = CmsPlayer(id_org=org.id_org, player_name="NUC", player_os="linux",
                       display_config={"video_renderer": "mpv", "screen_resolution": "1920x1080"})
    db_session.add(player)
    await db_session.commit()

    two_zones = [
        {"index": 0, "x": 0, "y": 0, "w": 960, "h": 1080, "label": "L"},
        {"index": 1, "x": 960, "y": 0, "w": 960, "h": 1080, "label": "R"},
    ]
    await _scene_playlist_event(db_session, org, player, media, two_zones, zone_index=1)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    # Le bloc template est émis (2 zones) et l'item de la zone 1 sert la rendition FHD .mp4
    # (browser-safe), pas le parent HEVC — alors que le player est en mpv.
    assert payload["template"] is not None
    z1 = next(z for z in payload["template"]["zones"] if z["index"] == 1)
    assert z1["items"][0]["media"]["url"].endswith(".fhd.mp4")
    # La liste plate (union) est elle aussi résolue navigateur-safe.
    assert payload["items"][0]["media"]["url"].endswith(".fhd.mp4")


@pytest.mark.asyncio
async def test_singlezone_template_keeps_native_variant(db_session, org):
    """Garde-fou : un template MONO-zone (= plein écran) n'altère PAS la résolution — le
    player mpv garde son parent HEVC 4K et aucun bloc template n'est émis."""
    media = await _make_4k_video_with_fhd(db_session, org)
    media.media_metadata = {"video": {"codec": "hevc", "width": 3840, "height": 2160}}
    await db_session.commit()
    player = CmsPlayer(id_org=org.id_org, player_name="NUC", player_os="linux",
                       display_config={"video_renderer": "mpv", "screen_resolution": "3840x2160"})
    db_session.add(player)
    await db_session.commit()

    one_zone = [{"index": 0, "x": 0, "y": 0, "w": 1920, "h": 1080, "label": "Main"}]
    await _scene_playlist_event(db_session, org, player, media, one_zone, zone_index=0)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["template"] is None
    assert payload["items"][0]["media"]["url"].endswith(media.storage_key)  # parent HEVC 4K


@pytest.mark.asyncio
async def test_prefetch_multizone_caches_browser_safe_variant(db_session, org):
    """§25.4 offline-first : le look-ahead pré-télécharge la variante NAVIGATEUR-SAFE pour un
    média servi via un template multi-zones (rendu Chromium <video>), même sur un player mpv qui
    jouerait normalement le parent HEVC 4K. Sans ça, la zone vidéo streamerait hors-ligne (noir)."""
    media = await _make_4k_video_with_fhd(db_session, org)
    media.media_metadata = {"video": {"codec": "hevc", "width": 3840, "height": 2160}}
    await db_session.commit()
    # Player mpv sur écran 4K → hors zone il prendrait le parent HEVC 4K (cf. test mono-zone).
    player = CmsPlayer(id_org=org.id_org, player_name="NUC", player_os="linux",
                       display_config={"video_renderer": "mpv", "screen_resolution": "3840x2160"})
    db_session.add(player)
    await db_session.commit()

    two_zones = [
        {"index": 0, "x": 0, "y": 0, "w": 960, "h": 1080, "label": "L"},
        {"index": 1, "x": 960, "y": 0, "w": 960, "h": 1080, "label": "R"},
    ]
    await _scene_playlist_event(db_session, org, player, media, two_zones, zone_index=1)

    prefetch = await _build_prefetch(db_session, player.id_player)
    entry = next(p for p in prefetch if p["id_media"] == media.id_media)
    assert entry["cache_key"].endswith(".fhd.mp4")   # browser-safe, pas le parent HEVC 4K
