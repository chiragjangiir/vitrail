"""Sélection de la rendition adaptative servie à un player (« artefacts » vidéo).

Au sync, chaque player reçoit la variante d'une vidéo la mieux adaptée à sa capacité :
on ne sert jamais plus que ce que son écran affiche ni que ce que son décodeur encaisse.

  - `player_target_height(player)` : hauteur vidéo maximale à servir à ce player
    (min entre la définition de son écran et son plafond de décodage logiciel). None =
    capacité inconnue → on sert l'originale (aucune dégradation à l'aveugle).
  - `select_variant(...)` : parmi {originale + renditions prêtes}, choisit la plus haute
    définition qui tient sous la cible (sinon la plus petite disponible).

Règle LAN sync (appliquée par l'appelant ws.py) : en groupe, la cible est le **min** des
cibles des membres → tous les écrans du mur jouent le MÊME encode (cohérence frame pour
`switch_at`/offset). Cf. EVOLUTIONS.md « Renditions adaptatives par capacité player ».

Fonctions pures (aucune I/O DB) ; opèrent sur l'objet CmsPlayer et des dicts.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services import player_capabilities

# Plafond de hauteur tenable en décodage logiciel (cf. player_capabilities) : au-delà,
# un CPU sans accélération matérielle saccade et désynchronise un mur.
SW_DECODE_HEIGHT_CAP = player_capabilities.SW_MAX_HEIGHT  # 1080

# ── Rotation À GRAVER (BrightSign, 2026-08-14) ────────────────────────────────
# Sur BrightSign, roter le widget (`transform` du roHtmlWidget) casse la géométrie du plan
# vidéo HW sur une source portrait (tampon lu avec la foulée de SORTIE — striage mesuré
# 52,2/255). Solution validée HW (XT1144, FHD et 4K) : le widget reste en PAYSAGE et la
# rotation est ENCODÉE dans une rendition paysage au contenu pré-roté (0,8/255).
#
# ⚠️ RELATION INVERSÉE — le genre de signe qu'on implémente à l'envers, d'où ce test-figé
# (test_rotation_bake.py) et ce repère : tourner une dalle en sens HORAIRE amène son bord
# GAUCHE en haut (le logo de la marque passe du bas vers la GAUCHE) ⇒ pour apparaître droit,
# le FICHIER doit être roté en sens ANTI-horaire (transpose=2, tête à gauche). Et vice-versa.
# Cohérent avec le widget d'avant : `right` (dalle horaire) → rot270 = 90° anti-horaire.
#
# `screen_rotation` : right = dalle tournée horaire · left = anti-horaire · `inverted`
# (180°) = non supporté (le plan vidéo BS ne tourne pas à 180 — mesuré le 2026-07-01).
# ✅ SENS DE MONTAGE CONFIRMÉ SUR DALLE PHYSIQUEMENT TOURNÉE (Ed, 2026-08-14 soir, XT1144) :
# dalle tournée horaire (logo du fabricant passé du bas à la GAUCHE) + `right` + fichier
# `rot_ccw` ⇒ contenu DROIT, plein cadre, tête en haut. Ce mapping n'est plus une hypothèse.
BAKE_PROFILE_BY_ROTATION = {
    "right": "rot_ccw",   # dalle tournée horaire      → fichier anti-horaire (transpose=2)
    "left": "rot_cw",     # dalle tournée anti-horaire → fichier horaire      (transpose=1)
}

# ⚠️ GARDE DE MIGRATION : un renderer BS < 2.0.39 rote ENCORE son widget (l'ancien
# bsApplyRotation) — lui servir une rendition pré-rotée COMPOSERAIT les deux rotations
# (il ne reste que 32 % de la largeur, mesuré le 14/08). Tant que CE device n'a pas
# rapporté ≥ 2.0.39, on ne grave rien : il garde strictement le comportement d'avant,
# et la garde se lève d'elle-même, device par device, à son OTA.
BAKE_MIN_RENDERER = (2, 0, 39)


def bake_rotation_profile(player: Any) -> Optional[str]:
    """Profil de rendition ROTÉE à servir à ce player, ou None (pas de gravure).

    Gravure = players **BrightSign** uniquement (présence de `capabilities.bs_model`,
    comme le gate HDMI-in), TOUS modèles — décision Ed 2026-08-14 : la doc BrightSign ne
    parle que des Series 4 mais le comportement est observé en Series 5 aussi ⇒ une règle,
    pas de branche par famille. Les autres players rotent leur rendu eux-mêmes (CSS/
    ExoPlayer/xrandr) sans casser le plan vidéo.
    """
    caps = getattr(player, "capabilities", None) or {}
    if not caps.get("bs_model"):
        return None
    dc = getattr(player, "display_config", None) or {}
    profile = BAKE_PROFILE_BY_ROTATION.get(dc.get("screen_rotation"))
    if profile is None:
        return None
    # Version non rapportée / non parsable → (0,0,0) → pas de gravure : défaut SÛR
    # (comportement d'avant), jamais une double rotation.
    from app.services.ota import semver_key  # import local (renditions reste léger)
    if semver_key(getattr(player, "player_version", None)) < BAKE_MIN_RENDERER:
        return None
    return profile


def _mode_height(mode) -> Optional[int]:
    """'1920x1080x60p' / '3840x2160x30p' → hauteur, sinon None (format BrightSign WxHxR)."""
    if not isinstance(mode, str):
        return None
    parts = mode.lower().split("x")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1])
    except (ValueError, TypeError):
        return None


def bake_output_height(player: Any) -> Optional[int]:
    """Hauteur de la SORTIE EFFECTIVE d'un player BrightSign (définition de la rendition rotée).

    ⚠️ `player_target_height` ne suffit PAS ici : `display_max_height` fait primer les
    `display_modes` de l'ÉCRAN — un HD1024 forcé en FHD au drawer mais branché sur une dalle
    4K rendait 2160 (mesuré le 2026-08-14), et aurait reçu la rendition 4K pour une sortie FHD.
    La demande d'Ed est l'inverse : la rendition suit ce que la sortie AFFICHE.

    Priorité :
      1. l'INTENTION du drawer (`display_config.bs_video_mode` : 'fhd' → 1080, 'WxHxR' → H) —
         elle prime sur la sortie réelle, qui peut être en retard d'un reboot ;
      2. la sortie RÉELLEMENT en service, remontée par le device (`capabilities.bs_video_mode`,
         couvre 'best' et l'absence d'avis) ;
      3. repli : la cible classique (modes écran ∩ décodage). None = inconnue → profil de base.
    """
    dc = getattr(player, "display_config", None) or {}
    mode = dc.get("bs_video_mode")
    if mode == "fhd":
        return 1080
    h = _mode_height(mode)
    if h:
        return h
    caps = getattr(player, "capabilities", None) or {}
    h = _mode_height(caps.get("bs_video_mode"))
    if h:
        return h
    return player_target_height(player)


def bake_variant_profile(base_profile: str, output_height: Optional[int],
                         media_w: Optional[int], media_h: Optional[int]) -> str:
    """Profil roté FINAL pour un média donné : `<base>` (cadre dérivé de la source, 4K HEVC
    au-delà de la FHD) ou `<base>_fhd` (cadre 1920×1080 H.264).

    Le `_fhd` n'est choisi que si la sortie est ≤ 1080 **ET que la source dépasse la FHD** :
    sur une source déjà FHD, le profil de base produit DÉJÀ un cadre FHD H.264 (`_rotated_frame`)
    — demander `_fhd` en plus fabriquerait un doublon d'encodage strictement identique.
    Sortie inconnue (None) → profil de base : le 4K passe partout où le parent 4K passait
    (défaut sûr, comportement d'avant ce chantier).
    """
    if (output_height and output_height <= 1080
            and max(media_w or 0, media_h or 0) > 1920):
        return f"{base_profile}_fhd"
    return base_profile


def _parse_height(mode: Optional[str]) -> Optional[int]:
    """'3840x2160@60' → 2160 ; '1920x1080' → 1080 ; invalide → None."""
    if not mode or not isinstance(mode, str):
        return None
    token = mode.split("@", 1)[0].strip().lower()
    if "x" not in token:
        return None
    try:
        _, h = token.split("x", 1)
        return int(h)
    except (ValueError, TypeError):
        return None


def display_max_height(
    capabilities: Optional[dict], display_config: Optional[dict]
) -> Optional[int]:
    """Hauteur maximale affichable par l'écran du player.

    Priorité aux modes réels remontés (`capabilities.display_modes`, format 'WxH@Hz') ;
    repli sur `display_config.screen_resolution` ('WxH'). None si rien d'exploitable.
    """
    caps = capabilities if isinstance(capabilities, dict) else {}
    modes = caps.get("display_modes")
    if isinstance(modes, list) and modes:
        heights = [h for h in (_parse_height(m) for m in modes) if h]
        if heights:
            return max(heights)
    dc = display_config if isinstance(display_config, dict) else {}
    return _parse_height(dc.get("screen_resolution"))


def player_target_height(player: Any) -> Optional[int]:
    """Hauteur vidéo max à servir à ce player (None = inconnu → servir l'originale).

    = min(définition écran, plafond décodage). Le plafond décodage ne s'applique que si
    le player décode confirmé en **logiciel** (un player HW ou inconnu n'est pas bridé)."""
    caps = getattr(player, "capabilities", None)
    dc = getattr(player, "display_config", None)
    panel = display_max_height(caps, dc)

    decode_cap: Optional[int] = None
    if player_capabilities.decode_health(player)["effective_decode"] == "software":
        decode_cap = SW_DECODE_HEIGHT_CAP

    candidates = [c for c in (panel, decode_cap) if c]
    return min(candidates) if candidates else None


_BROWSER_SAFE_EXT = ("mp4", "m4v", "webm")
# Codecs NON décodables par un <video> de navigateur Chromium (WebView Amlogic 83, ChromeOS PWA,
# extension…) — même dans un conteneur .mp4. Un player navigateur doit recevoir du H.264, pas ça.
_BROWSER_UNSAFE_CODECS = {"hevc", "h265", "hvc1", "hev1"}


def _browser_safe_container(storage_key: Optional[str]) -> bool:
    """True si le conteneur (extension du storage_key) est lisible par un <video> de navigateur
    (MP4/WebM). Un MKV/MOV/AVI ne l'est pas (Chromium <video> : ChromeOS PWA, extension,
    Electron/WebView hors mpv/exo). Sans extension → supposé safe (legacy, ne pas sur-filtrer)."""
    if not storage_key or "." not in storage_key:
        return True
    return storage_key.rsplit(".", 1)[-1].lower() in _BROWSER_SAFE_EXT


def is_browser_unsafe_codec(codec: Optional[str]) -> bool:
    """True si le CODEC n'est pas décodable par un <video> Chromium (HEVC…) — même en .mp4."""
    return (codec or "").lower() in _BROWSER_UNSAFE_CODECS


def select_variant(
    original_height: Optional[int],
    original_key: Optional[str],
    renditions: list[dict],
    target_height: Optional[int],
    prefer_codec: Optional[str] = None,
    original_codec: Optional[str] = None,
    browser_only: bool = False,
    allow_hevc: bool = False,
) -> dict:
    """Choisit la variante à servir parmi l'originale + les renditions prêtes.

    renditions : [{height, storage_key, profile, codec}] (seulement les artefacts 'ready').
    Retour : {"storage_key", "profile" (None = originale), "height", "codec"}.

    Stratégie : la plus HAUTE définition qui tient sous la cible ; si aucune ne tient
    (cible plus petite que tout), la plus PETITE disponible ; cible None → originale.
    `prefer_codec` (ex. 'hevc' pour un player ExoPlayer dont le décodeur h264 cale en 4K@60) :
    à définition retenue, préfère une variante de ce codec si disponible. Sans préférence,
    comportement strictement inchangé (sélection par hauteur seule).
    `browser_only` (player rendant via <video> Chromium) : exclut les conteneurs non lisibles
    par un navigateur (MKV/MOV/AVI...) — y compris l'originale — pour ne servir que du MP4/WebM.
    """
    variants: list[dict] = [
        {"height": original_height, "storage_key": original_key, "profile": None,
         "codec": original_codec}
    ]
    for r in renditions:
        if r.get("storage_key"):
            variants.append({
                "height": r.get("height"),
                "storage_key": r["storage_key"],
                "profile": r.get("profile"),
                "codec": r.get("codec"),
            })

    if browser_only:
        # Ne garder que les variantes lisibles par un <video> : conteneur navigateur-safe, ET
        # codec décodable. Le HEVC (même en .mp4) n'est exclu que si le player NE déclare PAS le
        # décoder (`allow_hevc=False` : WebView Chromium 83 du Minix) ; un ChromeOS récent à
        # décodeur HEVC matériel (`allow_hevc=True`) garde le HEVC 4K. Si AUCUNE variante ne
        # passe (legacy non transcodé) → pool intact (repli : mieux vaut tenter l'original).
        safe = [
            v for v in variants
            if _browser_safe_container(v["storage_key"])
            and (allow_hevc or not is_browser_unsafe_codec(v.get("codec")))
        ]
        if safe:
            variants = safe

    if target_height is None:
        return variants[0]

    pref = (prefer_codec or "").lower() or None

    def _codec_pick(pool: list[dict], best):
        """Dans `pool`, préfère le codec demandé (extrême selon `best`), sinon `best` global."""
        if pref:
            same = [v for v in pool if (v.get("codec") or "").lower() == pref]
            if same:
                return best(same, key=lambda v: v["height"])
        return best(pool, key=lambda v: v["height"])

    fitting = [v for v in variants if v["height"] and v["height"] <= target_height]
    if fitting:
        return _codec_pick(fitting, max)

    known = [v for v in variants if v["height"]]
    if known:
        return _codec_pick(known, min)
    return variants[0]
