"""Tests de la logique de sélection d'encodage vidéo (§XVI.2 — défauts intelligents).

L'encodeur matériel (NVENC/QSV/VAAPI) est forcé OFF ici → on valide les défauts logiciels
(libx264/libx265) de façon déterministe, sans dépendre d'un GPU/ffmpeg. La sélection HW est
testée séparément dans test_encoders.py.
"""

import pytest

from app.core import encoders
from app.workers import media_worker
from app.workers.media_worker import (
    _auto_passthrough_eligible,
    _build_video_cmd,
    _gop_frames,
    _maxrate_args,
    _maxrate_kbps,
    _parse_fps,
    _served_display_name,
)


@pytest.fixture(autouse=True)
def _force_software_encoder(monkeypatch):
    monkeypatch.setattr(encoders, "detect_hw_encoders", lambda: ())


def _probe(width, height, has_audio=True, is_hdr=False, fps=None, src_kbps=None):
    return {"width": width, "height": height, "has_audio": has_audio, "is_hdr": is_hdr,
            "fps": fps, "src_kbps": src_kbps}


def test_1080p_uses_h264_with_normalized_aac():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080))
    assert "libx264" in cmd
    assert "libx265" not in cmd
    assert "-af" in cmd  # loudnorm présent
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in cmd
    assert "aac" in cmd


def test_no_audio_uses_an_and_no_loudnorm():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080, has_audio=False))
    assert "-an" in cmd
    assert "-af" not in cmd
    assert "aac" not in cmd


def test_4k_exact_uses_h265():
    # 4K pile (3840×2160) = UHD → HEVC. Le seuil est `>=` (commit 7e06051) : H.264 en 4K@60 = Level 6,
    # mal décodé (SIGILL ChromeOS/Chromebox) et gonfle le débit (HEVC ~11 Mbps → H.264 ~37 Mbps).
    cmd = _build_video_cmd("in", "out", _probe(3840, 2160))
    assert "libx265" in cmd
    assert "libx264" not in cmd


# ── Nom affiché reflétant l'extension servie (.mp4 / .ogg) ───────────────────────

def test_served_name_video_to_mp4():
    assert _served_display_name("video", "clip.mov", "org/x.mp4") == "clip.mp4"
    assert _served_display_name("video", "clip.MKV", "org/x.mp4") == "clip.mp4"


def test_served_name_audio_to_ogg():
    assert _served_display_name("audio", "track.mp3", "org/x.ogg") == "track.ogg"
    assert _served_display_name("audio", "track.WAV", "org/x.ogg") == "track.ogg"
    assert _served_display_name("audio", "song.m4a", "org/x.ogg") == "song.ogg"


def test_served_name_no_rename_when_already_correct():
    # Déjà au bon conteneur → pas de renommage (et pas de double extension).
    assert _served_display_name("video", "clip.mp4", "org/x.mp4") is None
    assert _served_display_name("audio", "track.ogg", "org/x.ogg") is None


def test_served_name_no_extension_or_mismatch():
    assert _served_display_name("audio", "noext", "org/x.ogg") is None
    assert _served_display_name("video", "clip.mov", "org/x.mkv") is None  # servi pas en .mp4
    assert _served_display_name("image", "pic.png", "org/x.png") is None


# ── Plafond de débit (anti-gonflement) ──────────────────────────────────────────

def test_maxrate_kbps_tiers():
    assert _maxrate_kbps(3840, 2160) == 20000   # 4K
    assert _maxrate_kbps(2560, 1440) == 12000   # 1440p
    assert _maxrate_kbps(1920, 1080) == 8000    # 1080p
    assert _maxrate_kbps(1280, 720) == 4000     # 720p
    assert _maxrate_kbps(640, 360) == 2500      # SD
    assert _maxrate_kbps(0, 0) == 0             # inconnu → pas de plafond
    # Portrait : on borne par la plus GRANDE arête (1080×1920 = un FHD pivoté).
    assert _maxrate_kbps(1080, 1920) == 8000


def test_fhd_cmd_has_maxrate_8mbps():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080))
    assert "-maxrate" in cmd
    assert cmd[cmd.index("-maxrate") + 1] == "8000k"
    assert cmd[cmd.index("-bufsize") + 1] == "16000k"


def test_4k_cmd_has_maxrate_20mbps():
    cmd = _build_video_cmd("in", "out", _probe(3840, 2160))
    assert cmd[cmd.index("-maxrate") + 1] == "20000k"


def test_hdr_cmd_has_maxrate():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080, is_hdr=True))
    assert "-maxrate" in cmd
    assert cmd[cmd.index("-maxrate") + 1] == "8000k"


def test_maxrate_capped_to_source_bitrate():
    # Source 4K déjà compacte (~9 Mbps) → plafond = 1,1× source = 9900k (et non 20000k),
    # sinon le ré-encodage HEVC CQ gonflerait (~14-16 Mbps). Anti-gonflement.
    assert _maxrate_args(3840, 2160, 9000) == ["-maxrate", "9900k", "-bufsize", "19800k"]


def test_maxrate_source_above_ceiling_uses_ceiling():
    # Source 4K très lourde (30 Mbps) → on borne au plafond résolution (20000k), pas 1,1×.
    assert _maxrate_args(3840, 2160, 30000) == ["-maxrate", "20000k", "-bufsize", "40000k"]


def test_maxrate_source_floor():
    # Source minuscule → plancher 800k (sécurité qualité), pas en-dessous.
    assert _maxrate_args(1920, 1080, 200) == ["-maxrate", "800k", "-bufsize", "1600k"]


def test_fhd_cmd_uses_source_cap():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080, src_kbps=4000))
    assert cmd[cmd.index("-maxrate") + 1] == "4400k"  # min(8000, 4000*1.1)


# ── Auto-passthrough (anti-gonflement : ne PAS ré-encoder une source déjà conforme) ──

def _meta(codec="h264", width=1920, height=1080, br=6000, acodec="aac",
          container="mov,mp4,m4a,3gp,3g2,mj2", cfr=True):
    rate = "30/1"
    return {
        "container": container,
        "video": {
            "codec": codec, "width": width, "height": height, "bitrate_kbps": br,
            "r_frame_rate": rate, "avg_frame_rate": rate if cfr else "30000/1001",
        },
        "audio": ({"codec": acodec} if acodec else None),
    }


@pytest.fixture
def _stub_conformance(monkeypatch):
    """Probe conforme par défaut : GOP 2s, faststart présent. Le meta vient des tests."""
    monkeypatch.setattr(media_worker, "_probe_keyframe_gop",
                        lambda p: {"max_gop_sec": 2.0, "keyframes": 15})
    monkeypatch.setattr(media_worker, "_detect_faststart", lambda p: True)


def _set_meta(monkeypatch, meta):
    monkeypatch.setattr(media_worker, "_probe_full", lambda p: meta)


def test_passthrough_eligible_conformant_h264(monkeypatch, _stub_conformance):
    _set_meta(monkeypatch, _meta())
    ok, meta = _auto_passthrough_eligible("in", _probe(1920, 1080))
    assert ok is True
    assert meta["conformance"]["status"] == "ready"


def test_passthrough_rejects_h264_4k(monkeypatch, _stub_conformance):
    # H.264 en 4K = SIGILL Chromebox → on ré-encode (en HEVC), jamais passthrough.
    _set_meta(monkeypatch, _meta(width=3840, height=2160, br=18000))
    ok, _ = _auto_passthrough_eligible("in", _probe(3840, 2160))
    assert ok is False


def test_passthrough_accepts_hevc_4k(monkeypatch, _stub_conformance):
    _set_meta(monkeypatch, _meta(codec="hevc", width=3840, height=2160, br=12000))
    ok, _ = _auto_passthrough_eligible("in", _probe(3840, 2160))
    assert ok is True


def test_passthrough_rejects_vp9(monkeypatch, _stub_conformance):
    # vp9/av1 décodent mal sur certains players <video>/WebView83 → ré-encode universel.
    _set_meta(monkeypatch, _meta(codec="vp9", container="matroska,webm"))
    ok, _ = _auto_passthrough_eligible("in", _probe(1920, 1080))
    assert ok is False


def test_passthrough_rejects_non_aac_audio(monkeypatch, _stub_conformance):
    _set_meta(monkeypatch, _meta(acodec="ac3"))
    ok, _ = _auto_passthrough_eligible("in", _probe(1920, 1080))
    assert ok is False


def test_passthrough_rejects_overweight_source(monkeypatch, _stub_conformance):
    # Conforme mais bien au-dessus du plafond (8000×1,5=12000) → ré-encode pour rapetisser.
    _set_meta(monkeypatch, _meta(br=20000))
    ok, _ = _auto_passthrough_eligible("in", _probe(1920, 1080))
    assert ok is False


def test_passthrough_rejects_hdr_source(monkeypatch, _stub_conformance):
    _set_meta(monkeypatch, _meta())
    ok, _ = _auto_passthrough_eligible("in", _probe(1920, 1080, is_hdr=True))
    assert ok is False  # HDR → libx265 10-bit, jamais passthrough


def test_above_4k_uses_h265():
    cmd = _build_video_cmd("in", "out", _probe(7680, 4320))
    assert "libx265" in cmd
    assert "libx264" not in cmd


def test_hdr_forces_h265_10bit():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080, is_hdr=True))
    assert "libx265" in cmd
    assert "yuv420p10le" in cmd
    # métadonnées HDR préservées
    joined = " ".join(cmd)
    assert "smpte2084" in joined
    assert "bt2020" in joined


def test_keyframes_and_faststart_always_present():
    cmd = _build_video_cmd("in", "out", _probe(1920, 1080))
    assert "-g" in cmd and "60" in cmd
    assert "+faststart" in cmd
    assert "-sc_threshold" in cmd


def test_gop_frames_from_fps():
    """GOP dérivé de la cadence : vise ≤2s quelle que soit la fps (fix 25fps PAL=2.4s)."""
    assert _gop_frames(25.0) == 50      # PAL : 50/25 = 2.0s (avant : 60/25 = 2.4s ❌)
    assert _gop_frames(30.0) == 60      # 60/30 = 2.0s
    assert _gop_frames(24.0) == 48      # ciné : 48/24 = 2.0s
    assert _gop_frames(29.97) == 60     # NTSC : 60/29.97 ≈ 2.002s
    assert _gop_frames(23.976) == 48
    assert _gop_frames(50.0) == 100
    assert _gop_frames(None) == 60      # repli si fps indéterminable
    assert _gop_frames(0) == 60


def test_video_cmd_gop_matches_fps():
    """Une vidéo 25fps doit produire -g 50 (et plus -g 60 qui donnait 2.4s)."""
    cmd = _build_video_cmd("in.mp4", "out.mp4", _probe(1920, 1080, fps=25.0))
    assert "-g" in cmd
    assert cmd[cmd.index("-g") + 1] == "50"
    assert cmd[cmd.index("-keyint_min") + 1] == "50"


def test_probe_extracts_fps(monkeypatch):
    """_probe (utilisé À l'encodage) doit remonter la fps — sinon GOP retombe sur 60
    (= 2.4s à 25fps). Régression de la cause racine du bug 488Spider."""
    import json as _json

    from app.workers import media_worker

    fake = type("R", (), {
        "returncode": 0,
        "stdout": _json.dumps({
            "streams": [{
                "codec_type": "video", "width": 1920, "height": 1080,
                "avg_frame_rate": "25/1", "duration": "10.0",
            }],
            "format": {},
        }),
        "stderr": "",
    })()
    monkeypatch.setattr(media_worker.subprocess, "run", lambda *a, **k: fake)
    p = media_worker._probe("x.mp4")
    assert p["fps"] == 25.0
    assert p["width"] == 1920


def test_parse_fps():
    """_parse_fps (§6) — conversion des frame rates ffprobe."""
    assert _parse_fps("30000/1001") == 29.97
    assert _parse_fps("25/1") == 25.0
    assert _parse_fps("0/0") is None
    assert _parse_fps(None) is None
    assert _parse_fps("bogus") is None
