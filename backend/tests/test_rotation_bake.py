"""Rotation À GRAVER (BrightSign portrait, 2026-08-14).

Roter le widget BrightSign casse la géométrie du plan vidéo HW sur une source portrait
(striage mesuré 52,2/255) ; la solution validée HW est : widget en PAYSAGE + rendition
paysage au contenu PRÉ-ROTÉ, produite à la demande et servie à la place de tout le reste.

Ce que ces tests FIGENT :
  - le mapping dalle → profil, dont la relation est INVERSÉE (dalle tournée en sens
    horaire ⇒ fichier roté ANTI-horaire) — le genre de signe qu'on ré-implémente à
    l'envers à la première refonte ;
  - la sélection : un player qui grave sa rotation ne reçoit QUE la rendition rotée du
    bon sens — jamais l'originale ni une rendition classique (elles apparaîtraient
    couchées), et le pré-cache télécharge la MÊME clé que le sync (classe du 18/07) ;
  - la production à la demande : rendition absente → enqueue UNE fois (pas de rejeu
    d'un 'failed', pas de doublon d'un 'processing') ;
  - la commande ffmpeg validée HW : transpose + pad paysage, hvc1, ⛔ jamais de -level,
    -b_ref_mode disabled sur NVENC.
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.ws as ws
from app.api.v1.endpoints.ws import _build_prefetch, _resolve_sync_payload, _resolve_variant_key
from app.models.media import CmsMedia, CmsMediaRendition
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.services import renditions as R


# ── Mapping dalle → profil (relation INVERSÉE, figée ici) ─────────────────────────

def test_bake_mapping_is_inverted():
    """Tourner une dalle en sens HORAIRE amène son bord GAUCHE en haut (repère d'Ed :
    le logo de la marque passe du bas vers la GAUCHE) ⇒ le FICHIER doit être roté
    ANTI-horaire (transpose=2, tête à gauche) pour apparaître droit. Et vice-versa.
    Si ce test rougit après une « simplification », c'est la simplification qui a tort."""
    bs = lambda rot: CmsPlayer(  # noqa: E731
        player_os="chromeos", player_version="2.0.39",
        capabilities={"bs_model": "XT1144"},
        display_config={"screen_rotation": rot},
    )
    assert R.bake_rotation_profile(bs("right")) == "rot_ccw"   # dalle horaire → fichier ccw
    assert R.bake_rotation_profile(bs("left")) == "rot_cw"     # dalle anti-horaire → fichier cw
    assert R.bake_rotation_profile(bs("normal")) is None
    assert R.bake_rotation_profile(bs("inverted")) is None     # 180° non supporté (mesuré 01/07)
    assert R.bake_rotation_profile(bs(None)) is None


def test_bake_only_for_brightsign():
    """La gravure est un remède BrightSign (plan vidéo HW du roHtmlWidget). Un player
    sans `capabilities.bs_model` rote son rendu lui-même (CSS/Exo/xrandr) → jamais gravé."""
    android = CmsPlayer(player_os="android", player_version="2.5.31",
                        capabilities={"codecs": ["h264"]},
                        display_config={"screen_rotation": "right"})
    assert R.bake_rotation_profile(android) is None
    no_caps = CmsPlayer(player_os="linux", player_version="1.6.21",
                        display_config={"screen_rotation": "right"})
    assert R.bake_rotation_profile(no_caps) is None


def test_bake_gated_on_renderer_version():
    """GARDE DE MIGRATION : un renderer < 2.0.39 rote ENCORE son widget — lui servir une
    rendition pré-rotée COMPOSERAIT les deux rotations (32 % de la largeur, mesuré 14/08).
    Pas de version rapportée = pas de gravure (défaut sûr). Mutation « garde retirée » →
    ce test rougit."""
    old = CmsPlayer(player_os="chromeos", player_version="2.0.37",
                    capabilities={"bs_model": "XT1144"},
                    display_config={"screen_rotation": "right"})
    assert R.bake_rotation_profile(old) is None
    unknown = CmsPlayer(player_os="chromeos", player_version=None,
                        capabilities={"bs_model": "XT1144"},
                        display_config={"screen_rotation": "right"})
    assert R.bake_rotation_profile(unknown) is None
    new = CmsPlayer(player_os="chromeos", player_version="2.0.39",
                    capabilities={"bs_model": "XT1144"},
                    display_config={"screen_rotation": "right"})
    assert R.bake_rotation_profile(new) == "rot_ccw"


# ── Fixtures ──────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="ROT", org_slug=f"rot-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture(autouse=True)
def _stub_signed_url(monkeypatch):
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")


async def _portrait_video(db, org, *, with_rot=True, with_fhd=True) -> CmsMedia:
    """Vidéo portrait 2160×3840 + (option) rendition rotée rot_ccw prête + rendition fhd."""
    m = CmsMedia(
        id_org=org.id_org, media_name="clip916", media_type="video", mime_type="video/mp4",
        storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        duration_ms=5000, width=2160, height=3840, source="upload",
        transcode_status="done", has_renditions=with_rot or with_fhd,
    )
    db.add(m)
    await db.flush()
    if with_rot:
        db.add(CmsMediaRendition(
            id_parent=m.id_media, profile="rot_ccw", width=3840, height=2160,
            codec="hevc", storage_key=f"v/{m.id_media}.rot_ccw.mp4", status="ready",
        ))
    if with_fhd:
        db.add(CmsMediaRendition(
            id_parent=m.id_media, profile="fhd", width=608, height=1080,
            codec="h264", storage_key=f"v/{m.id_media}.fhd.mp4", status="ready",
        ))
    await db.commit()
    await db.refresh(m)
    return m


def _bs_player(org, rotation="right", **kw):
    return CmsPlayer(
        id_org=org.id_org, player_name=f"BS-{rotation}", player_os="chromeos",
        player_version="2.0.39",   # ≥ BAKE_MIN_RENDERER (la garde de migration passe)
        capabilities={"bs_model": "XT1144"},
        display_config={"screen_rotation": rotation, "screen_resolution": "3840x2160"},
        **kw,
    )


# ── Sélection : le pool roté est EXCLUSIF ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_bake_serves_only_the_rotated_rendition(db_session, org):
    """Avec une rendition fhd prête ET une rot_ccw prête, un player qui grave sa rotation
    reçoit la ROT_CCW — jamais la fhd ni le parent, qui apparaîtraient couchés. Mutation
    « la gravure retombe dans la sélection classique » → ce test rougit (la fhd sortirait
    pour une cible 1080)."""
    media = await _portrait_video(db_session, org)
    key = await _resolve_variant_key(db_session, media, 1080, bake_profile="rot_ccw")
    assert key.endswith(".rot_ccw.mp4")
    # Cible inconnue → toujours la rotée (le cadre paysage est la seule forme droite).
    key2 = await _resolve_variant_key(db_session, media, None, bake_profile="rot_ccw")
    assert key2.endswith(".rot_ccw.mp4")
    # Témoin : SANS gravure, la sélection classique reste inchangée (fhd pour cible 1080).
    key3 = await _resolve_variant_key(db_session, media, 1080)
    assert key3.endswith(".fhd.mp4")


@pytest.mark.asyncio
async def test_bake_wrong_direction_not_served(db_session, org):
    """Une rendition rotée de l'AUTRE sens ne satisfait pas la demande : rot_ccw prête
    mais gravure demandée rot_cw → repli original + enqueue du bon profil."""
    media = await _portrait_video(db_session, org)  # rot_ccw prête
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        key = await _resolve_variant_key(db_session, media, 2160, bake_profile="rot_cw")
    assert key == media.storage_key
    mock_delay.assert_called_once_with(media.id_media, "rot_cw")


# ── Production à la demande ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bake_enqueues_once_when_absent(db_session, org):
    """Rendition rotée absente → repli original + UN enqueue. Mutation « enqueue retiré »
    → ce test rougit : personne ne produirait jamais la rendition."""
    media = await _portrait_video(db_session, org, with_rot=False)
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        key = await _resolve_variant_key(db_session, media, 2160, bake_profile="rot_ccw")
    assert key == media.storage_key          # dégradé (couché) en attendant la rendition
    mock_delay.assert_called_once_with(media.id_media, "rot_ccw")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["processing", "failed", "pending"])
async def test_bake_does_not_reenqueue_existing_row(db_session, org, status):
    """Une ligne existante — même 'failed' — n'est PAS ré-enfilée depuis le sync : un
    échec d'encodage est déterministe (règle 1.0.24), le rejouer toutes les 30 s
    affamerait le serveur ; la régénération passe par l'endpoint renditions."""
    media = await _portrait_video(db_session, org, with_rot=False)
    db_session.add(CmsMediaRendition(id_parent=media.id_media, profile="rot_ccw", status=status))
    await db_session.commit()
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        key = await _resolve_variant_key(db_session, media, 2160, bake_profile="rot_ccw")
    assert key == media.storage_key
    mock_delay.assert_not_called()


@pytest.mark.asyncio
async def test_bake_ignores_non_video(db_session, org):
    img = CmsMedia(id_org=org.id_org, media_name="img", media_type="image",
                   storage_key="i/x.jpg", checksum_sha256="z", transcode_status="done")
    db_session.add(img)
    await db_session.commit()
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        key = await _resolve_variant_key(db_session, img, None, bake_profile="rot_ccw")
    assert key == img.storage_key
    mock_delay.assert_not_called()


# ── Bout en bout : payload + pré-cache servent la MÊME clé rotée ─────────────────

async def _scene_event(db, org, player, media):
    from datetime import UTC, datetime

    from app.models.event import CmsEvent
    ev = CmsEvent(
        id_org=org.id_org, event_name="E", event_type="manual", event_kind="content",
        status="active", id_media=media.id_media, priority=10, duration_ms=5000,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        activated_at=datetime.now(UTC),
    )
    db.add(ev)
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_sync_payload_bs_portrait_gets_rotated_variant(db_session, org):
    media = await _portrait_video(db_session, org)
    player = _bs_player(org, rotation="right")
    db_session.add(player)
    await db_session.commit()
    await _scene_event(db_session, org, player, media)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    m = payload["items"][0]["media"]
    assert m["url"].endswith(".rot_ccw.mp4")
    assert m["cache_key"].endswith(".rot_ccw.mp4")
    # Repli offline : le parent (couché) plutôt qu'un écran noir.
    assert m["cache_key_fallback"] == media.storage_key


@pytest.mark.asyncio
async def test_sync_payload_bs_landscape_unchanged(db_session, org):
    """Témoin de non-régression : un BrightSign en paysage (`normal`) garde la sélection
    classique — le parent portrait, servi tel quel (net, pillarboxé — mesuré 0,9/255)."""
    media = await _portrait_video(db_session, org, with_fhd=False)
    player = _bs_player(org, rotation="normal")
    db_session.add(player)
    await db_session.commit()
    await _scene_event(db_session, org, player, media)

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload["items"][0]["media"]["cache_key"] == media.storage_key


@pytest.mark.asyncio
async def test_prefetch_serves_rotated_variant(db_session, org):
    """Le look-ahead télécharge la clé que le sync SERVIRA (classe de défaut du 18/07 :
    un pré-cache qui ne suit pas la sélection = faux « média manquant »)."""
    from datetime import UTC, datetime

    from app.models.event import CmsEvent
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem

    media = await _portrait_video(db_session, org)
    player = _bs_player(org, rotation="right")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="P")
    db_session.add_all([player, pl])
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=media.id_media,
                                   sort_order=0, duration_ms=5000))
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="E", event_type="manual", event_kind="content",
        status="active", id_playlist=pl.id_playlist, priority=10,
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        activated_at=datetime.now(UTC),
    ))
    await db_session.commit()

    prefetch = await _build_prefetch(db_session, player.id_player)
    entry = next(p for p in prefetch if p["id_media"] == media.id_media)
    assert entry["cache_key"].endswith(".rot_ccw.mp4")


# ── Commande ffmpeg validée HW (pièges du 14/08) ─────────────────────────────────

def test_rotated_frame_follows_source():
    from app.workers.media_worker import _rotated_frame
    # Portrait 4K → cadre paysage 4K HEVC (validé HW XT1144).
    assert _rotated_frame({"width": 2160, "height": 3840}) == (3840, 2160, "hevc")
    assert _rotated_frame({"width": 2160, "height": 3778}) == (3840, 2160, "hevc")
    # Portrait FHD → cadre paysage FHD H.264 (compat universelle).
    assert _rotated_frame({"width": 1080, "height": 1920}) == (1920, 1080, "h264")
    # Paysage 16:9 sur dalle portrait : roté quand même (bande verticale pillarboxée).
    assert _rotated_frame({"width": 1920, "height": 1080}) == (1920, 1080, "h264")


def _probe_stub():
    return {"width": 2160, "height": 3840, "has_audio": True, "is_hdr": False,
            "duration_ms": 5000, "fps": 30.0, "src_kbps": None}


def test_rotated_cmd_software_hevc():
    from app.workers.media_worker import _build_rotated_cmd
    cmd = _build_rotated_cmd("in.mp4", "out.mp4", _probe_stub(), 2, 3840, 2160, "hevc",
                             force_sw=True)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("transpose=2,")                      # anti-horaire (tête à gauche)
    assert "pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black" in vf    # cadre PAYSAGE complété
    assert "force_original_aspect_ratio=decrease" in vf
    # hvc1 obligatoire (hev1 = refusé par Chromium — mesuré 14/08).
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"
    # ⛔ jamais de -level : 5.1 en tier main plafonne à 40 Mbit/s → NVENC refuse (Invalid Level).
    assert "-level" not in cmd


def test_rotated_cmd_nvenc_has_b_ref_mode_disabled():
    """`-b_ref_mode disabled` = la traduction nvenc du b_pyramid=0 recommandé par BrightSign."""
    import app.workers.media_worker as mw
    with patch.object(mw, "_select_encoder",
                      return_value={"name": "hevc_nvenc", "kind": "nvenc", "vaapi_device": None}):
        cmd = mw._build_rotated_cmd("in.mp4", "out.mp4", _probe_stub(), 2, 3840, 2160, "hevc")
    assert cmd[cmd.index("-b_ref_mode") + 1] == "disabled"
    assert "-level" not in cmd
    assert cmd[cmd.index("-c:v") + 1] == "hevc_nvenc"


def test_rotated_cmd_cw_direction():
    from app.workers.media_worker import _build_rotated_cmd
    cmd = _build_rotated_cmd("in.mp4", "out.mp4", _probe_stub(), 1, 1920, 1080, "h264",
                             force_sw=True)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("transpose=1,")                      # horaire (tête à droite)
    assert "pad=1920:1080" in vf


def test_rotation_profiles_registered():
    """Les profils rotés existent au catalogue des profils, avec le transpose du mapping :
    rot_cw = transpose 1 (horaire) · rot_ccw = transpose 2 (anti-horaire) — et leurs
    variantes _fhd (cadre paysage FIXE 1920×1080 H.264, même transpose)."""
    from app.workers.media_worker import RENDITION_PROFILES
    assert RENDITION_PROFILES["rot_cw"]["transpose"] == 1
    assert RENDITION_PROFILES["rot_ccw"]["transpose"] == 2
    assert RENDITION_PROFILES["rot_cw_fhd"] == {
        "box": None, "codec": "h264", "transpose": 1, "frame": (1920, 1080)}
    assert RENDITION_PROFILES["rot_ccw_fhd"] == {
        "box": None, "codec": "h264", "transpose": 2, "frame": (1920, 1080)}
    # Et le mapping du service pointe bien vers des profils EXISTANTS (anti-typo),
    # variantes _fhd comprises (bake_variant_profile les dérive par suffixe).
    for prof in R.BAKE_PROFILE_BY_ROTATION.values():
        assert prof in RENDITION_PROFILES
        assert f"{prof}_fhd" in RENDITION_PROFILES


# ── Rendition rotée PAR DÉFINITION (demande d'Ed 2026-08-14 soir) ─────────────────

def test_bake_output_height_priorities():
    """La DÉFINITION suit la SORTIE EFFECTIVE, pas l'écran : ⚠️ `player_target_height` fait
    primer les display_modes de l'ÉCRAN — un HD1024 forcé FHD au drawer mais branché sur une
    dalle 4K rendait 2160 (mesuré). Priorité : intention du drawer > sortie réelle remontée
    > repli classique. Mutation « bs_video_mode ignoré » → ce test rougit."""
    mk = lambda dc=None, caps=None: CmsPlayer(  # noqa: E731
        player_os="chromeos", player_version="2.0.39",
        display_config=dc or {}, capabilities={"bs_model": "HD1024", **(caps or {})})
    # 1. L'intention du drawer prime (elle peut être en avance d'un reboot sur la sortie réelle).
    assert R.bake_output_height(mk(dc={"bs_video_mode": "fhd"},
                                   caps={"bs_video_mode": "3840x2160x30p"})) == 1080
    assert R.bake_output_height(mk(dc={"bs_video_mode": "3840x2160x60p"})) == 2160
    # 2. 'best'/absent → la sortie RÉELLEMENT en service (remontée par le device).
    assert R.bake_output_height(mk(dc={"bs_video_mode": "best"},
                                   caps={"bs_video_mode": "3840x2160x30p"})) == 2160
    assert R.bake_output_height(mk(caps={"bs_video_mode": "1920x1080x60p"})) == 1080
    # 3. Repli : la cible classique (modes écran) ; rien du tout → None (profil de base).
    assert R.bake_output_height(mk(dc={"screen_resolution": "3840x2160"})) == 2160
    assert R.bake_output_height(mk()) is None


def test_bake_variant_profile_threshold():
    """Sortie ≤ 1080 sur une source > FHD → variante _fhd ; sinon profil de base.
    ⚠️ Source déjà FHD : le profil de base produit DÉJÀ un cadre FHD H.264 — demander _fhd
    fabriquerait un doublon d'encodage identique → profil de base. Sortie inconnue → base
    (défaut sûr). Mutation « seuil retiré » → ce test rougit."""
    assert R.bake_variant_profile("rot_ccw", 1080, 2160, 3840) == "rot_ccw_fhd"
    assert R.bake_variant_profile("rot_cw", 720, 2160, 3840) == "rot_cw_fhd"
    assert R.bake_variant_profile("rot_ccw", 2160, 2160, 3840) == "rot_ccw"
    assert R.bake_variant_profile("rot_ccw", None, 2160, 3840) == "rot_ccw"
    # Source portrait déjà FHD (1080×1920) : pas de doublon, le cadre de base EST déjà FHD.
    assert R.bake_variant_profile("rot_ccw", 1080, 1080, 1920) == "rot_ccw"


@pytest.mark.asyncio
async def test_bake_fhd_variant_served_and_enqueued(db_session, org):
    """Un BS dont la SORTIE est FHD (bs_video_mode='fhd') reçoit la rendition _fhd — prête
    → servie ; absente → enqueuée (repli parent). Le XT 4K du test e2e d'hier reste sur le
    profil de base (anti-régression, couvert par test_sync_payload_bs_portrait...)."""
    media = await _portrait_video(db_session, org, with_rot=False, with_fhd=False)
    hd = CmsPlayer(
        id_org=org.id_org, player_name="HD-fhd", player_os="chromeos",
        player_version="2.0.39", capabilities={"bs_model": "HD1024"},
        display_config={"screen_rotation": "right", "bs_video_mode": "fhd"},
    )
    db_session.add(hd)
    await db_session.commit()
    await _scene_event(db_session, org, hd, media)

    # Rendition _fhd absente → repli parent + enqueue du BON profil (_fhd, pas le 4K).
    # ℹ️ Un payload complet résout le média DEUX fois (items de l'event + look-ahead) →
    # jusqu'à 2 enqueues identiques ; la garde worker « processing frais → skip » rend le
    # doublon no-op. Ce qu'on fige ici : tous les appels visent le _fhd, jamais le 4K.
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        payload = await _resolve_sync_payload(db_session, hd.id_player)
    assert payload["items"][0]["media"]["cache_key"] == media.storage_key
    assert mock_delay.call_count >= 1
    assert all(c.args == (media.id_media, "rot_ccw_fhd") for c in mock_delay.call_args_list), \
        mock_delay.call_args_list

    # Rendition _fhd prête → servie (et pas la rot_ccw 4K, même si elle existait).
    db_session.add_all([
        CmsMediaRendition(id_parent=media.id_media, profile="rot_ccw", width=3840, height=2160,
                          codec="hevc", storage_key=f"v/{media.id_media}.rot_ccw.mp4",
                          status="ready"),
        CmsMediaRendition(id_parent=media.id_media, profile="rot_ccw_fhd", width=1920,
                          height=1080, codec="h264",
                          storage_key=f"v/{media.id_media}.rot_ccw_fhd.mp4", status="ready"),
    ])
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, hd.id_player)
    assert payload["items"][0]["media"]["cache_key"].endswith(".rot_ccw_fhd.mp4")


@pytest.mark.asyncio
async def test_bake_fhd_falls_back_to_ready_4k_of_same_direction(db_session, org):
    """La _fhd demandée n'est pas prête mais la rot 4K du MÊME sens l'est → on sert la 4K
    (elle est DROITE — le parent est couché) en attendant, ET on enqueue la _fhd. Cas réel :
    le HD qui bascule de la 4K vers la _fhd garde l'écran droit pendant l'encodage.
    ⚠️ Une rendition de l'AUTRE sens ne sert jamais de repli."""
    media = await _portrait_video(db_session, org, with_rot=False, with_fhd=False)
    db_session.add_all([
        CmsMediaRendition(id_parent=media.id_media, profile="rot_ccw", width=3840, height=2160,
                          codec="hevc", storage_key=f"v/{media.id_media}.rot_ccw.mp4",
                          status="ready"),
        # Le sens OPPOSÉ, prêt lui aussi : il ne doit JAMAIS être servi en repli.
        CmsMediaRendition(id_parent=media.id_media, profile="rot_cw", width=3840, height=2160,
                          codec="hevc", storage_key=f"v/{media.id_media}.rot_cw.mp4",
                          status="ready"),
    ])
    await db_session.commit()
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        key = await _resolve_variant_key(db_session, media, 1080,
                                         bake_profile="rot_ccw", bake_height=1080)
    assert key.endswith(".rot_ccw.mp4")          # repli DROIT, pas le parent couché
    mock_delay.assert_called_once_with(media.id_media, "rot_ccw_fhd")
    # Sens opposé demandé (rot_cw_fhd) : le repli est la rot_cw prête, jamais la rot_ccw.
    with patch("app.workers.media_worker.generate_rendition.delay"):
        key2 = await _resolve_variant_key(db_session, media, 1080,
                                          bake_profile="rot_cw", bake_height=1080)
    assert key2.endswith(".rot_cw.mp4")


@pytest.mark.asyncio
async def test_endpoint_accepts_rotated_fhd_profile(client, db_session, org):
    """POST /renditions accepte les profils rotés (_fhd compris). ⚠️ Le contrôle de taille des
    profils de DOWNSCALE comparait `max(w,h) <= prof['box']` — box est None sur un profil roté
    et rot_*_fhd porte codec='h264' ⇒ sans le guard `transpose`, TypeError = 500 en prod.
    Mutation « guard retiré » → ce test rougit."""
    import uuid as _uuid

    from app.core.security import hash_password
    from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
    from app.models.user import CmsUser
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    uid = _uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"rot-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_ROT_{uid}", label="ROT", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in [("media", "read"), ("media", "edit")]:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    h = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    media = await _portrait_video(db_session, org, with_rot=False, with_fhd=False)
    with patch("app.workers.media_worker.generate_rendition.delay") as mock_delay:
        r = await client.post(f"/api/v1/media/{media.id_media}/renditions",
                              json={"profile": "rot_ccw_fhd"}, headers=h)
    assert r.status_code == 202, r.text
    mock_delay.assert_called_once_with(media.id_media, "rot_ccw_fhd")


@pytest.mark.asyncio
async def test_bake_group_height_is_group_min(db_session, org):
    """Groupe LAN actif : la définition rotée = min des SORTIES des membres BS rotés (même
    règle de cohérence frame que _player_target_height). Le XT 4K d'un mur qui compte un HD
    FHD reçoit la _fhd lui aussi — tous jouent le MÊME fichier. Mutation « min du groupe
    retiré » → ce test rougit."""
    from app.api.v1.endpoints.ws import _bake_group_height
    xt = CmsPlayer(
        id_org=org.id_org, player_name="XT", player_os="chromeos", player_version="2.0.39",
        capabilities={"bs_model": "XT1144", "bs_video_mode": "3840x2160x60p"},
        display_config={"screen_rotation": "right", "lan_sync_enabled": True,
                        "lan_sync_group": "mur"},
    )
    hd = CmsPlayer(
        id_org=org.id_org, player_name="HD", player_os="chromeos", player_version="2.0.39",
        capabilities={"bs_model": "HD1024"},
        display_config={"screen_rotation": "right", "bs_video_mode": "fhd",
                        "lan_sync_enabled": True, "lan_sync_group": "mur"},
    )
    db_session.add_all([xt, hd])
    await db_session.commit()
    assert await _bake_group_height(db_session, xt) == 1080   # tiré vers le HD
    assert await _bake_group_height(db_session, hd) == 1080
    # Hors groupe (lan_sync_enabled false) : chacun sa sortie.
    xt.display_config = {**xt.display_config, "lan_sync_enabled": False}
    await db_session.commit()
    assert await _bake_group_height(db_session, xt) == 2160
