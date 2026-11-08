"""Détection des encodeurs vidéo MATÉRIELS + sélection auto (NVENC / Intel QSV-VAAPI).

Miroir serveur de la détection de DÉCODAGE des players (`player-*/scripts/detect-capabilities.sh`)
et de `app/core/resources.py` (auto-sizing). But : si un GPU est accessible au conteneur,
encoder sur le GPU (transcodes bien plus rapides, CPU libéré) ; sinon repli `libx264`/`libx265`
(zéro régression). Auto-adaptatif : la même image marche d'un serveur RTX à un mini-PC sans GPU.

`ffmpeg -encoders` liste les encodeurs même sans driver/GPU → on **teste réellement** chaque
candidat par un encode d'1s (sinon faux positifs). Résultat caché 1× par process worker.

Surcharges env :
  - `SF_DISABLE_HWENC=1`     → force le logiciel (debug / repli volontaire).
  - `SF_VIDEO_ENCODER=<name>` → force un encodeur précis (ex. `h264_vaapi`), bypass détection.
"""

from __future__ import annotations

import functools
import glob
import logging
import os
import subprocess  # nosec B404

logger = logging.getLogger(__name__)

# Candidats testés, dans l'ordre de préférence par famille de codec.
_H264 = ["h264_nvenc", "h264_qsv", "h264_vaapi"]
_HEVC = ["hevc_nvenc", "hevc_qsv", "hevc_vaapi"]


def _kind(name: str) -> str:
    if name.endswith("_nvenc"):
        return "nvenc"
    if name.endswith("_qsv"):
        return "qsv"
    if name.endswith("_vaapi"):
        return "vaapi"
    return "sw"


def vaapi_device() -> str | None:
    """1er nœud render DRM présent (iGPU/GPU Intel/AMD), défaut renderD128. None si absent."""
    env = os.environ.get("SF_VAAPI_DEVICE")
    if env:
        return env
    nodes = sorted(glob.glob("/dev/dri/renderD*"))
    return nodes[0] if nodes else None


def _ffmpeg_has_encoder(name: str) -> bool:
    try:
        out = subprocess.run(  # nosec B603,B607
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-encoders"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())
    except Exception:  # noqa: BLE001
        return False


def _test_encode(name: str) -> bool:
    """Encode réel d'1s (testsrc) → confirme encodeur + driver + accès device."""
    kind = _kind(name)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if kind == "vaapi":
        dev = vaapi_device()
        if not dev:
            return False
        cmd += ["-vaapi_device", dev,
                "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=5",
                "-vf", "format=nv12,hwupload", "-c:v", name]
    elif kind == "qsv":
        cmd += ["-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=5", "-c:v", name]
    else:  # nvenc
        cmd += ["-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=5", "-c:v", name]
    cmd += ["-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)  # nosec B603
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def detect_hw_encoders() -> tuple[str, ...]:
    """Encodeurs matériels qui ENCODENT réellement sur cette machine (cachés 1×)."""
    if os.environ.get("SF_DISABLE_HWENC"):
        logger.info("[encoders] SF_DISABLE_HWENC=1 → encodage logiciel forcé")
        return ()
    forced = os.environ.get("SF_VIDEO_ENCODER")
    if forced:
        ok = _ffmpeg_has_encoder(forced) and _test_encode(forced)
        logger.info("[encoders] SF_VIDEO_ENCODER=%s → %s", forced, "OK" if ok else "INDISPONIBLE")
        return (forced,) if ok else ()
    found: list[str] = []
    for name in _H264 + _HEVC:
        if _ffmpeg_has_encoder(name) and _test_encode(name):
            found.append(name)
    logger.info("[encoders] matériels détectés : %s", ", ".join(found) or "(aucun → libx264)")
    return tuple(found)


def best_encoder(codec: str = "h264") -> dict:
    """Meilleur encodeur dispo pour `codec` (h264|hevc). Ordre nvenc > qsv > vaapi > sw.

    Retourne {name, kind, vaapi_device}. `kind=sw` → libx264/libx265 (repli).
    """
    avail = detect_hw_encoders()
    pref = _H264 if codec == "h264" else _HEVC
    for name in pref:
        if name in avail:
            return {"name": name, "kind": _kind(name), "vaapi_device": vaapi_device()}
    sw = "libx264" if codec == "h264" else "libx265"
    return {"name": sw, "kind": "sw", "vaapi_device": None}


def hw_encode_available() -> bool:
    """True si au moins un encodeur matériel est utilisable (pour le dimensionnement worker)."""
    return len(detect_hw_encoders()) > 0
