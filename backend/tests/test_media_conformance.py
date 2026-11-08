"""Tests — conformité & sync-readiness média (passthrough, §XVI.2 / EVOLUTIONS).

Couvre le service pur `media_conformance.evaluate` (verdict 3 états ready/playable/
nonconform sur diffusabilité + sync-readiness) et le détecteur faststart du worker.
"""

from app.services.media_conformance import (
    bitrate_ceiling_kbps,
    evaluate,
    is_cfr,
)
from app.workers.media_worker import _detect_faststart


def _video(**over):
    base = {
        "codec": "h264",
        "width": 1920,
        "height": 1080,
        "bitrate_kbps": 8000,
        "r_frame_rate": "25/1",
        "avg_frame_rate": "25/1",
        "gop": {"max_gop_sec": 2.0},
        "faststart": True,
    }
    base.update(over)
    return {"video": base}


def test_ready_when_cfr_gop_faststart_ok():
    v = evaluate(_video())
    assert v["status"] == "ready"
    assert v["reasons"] == []


def test_vfr_is_playable():
    v = evaluate(_video(avg_frame_rate="24000/1001"))
    assert v["status"] == "playable"
    assert v["checks"]["cfr"]["ok"] is False
    assert any("VFR" in r or "variable" in r for r in v["reasons"])


def test_long_gop_is_playable():
    v = evaluate(_video(gop={"max_gop_sec": 5.0}))
    assert v["status"] == "playable"
    assert v["checks"]["gop"]["ok"] is False


def test_no_faststart_is_playable():
    v = evaluate(_video(faststart=False))
    assert v["status"] == "playable"
    assert v["checks"]["faststart"]["ok"] is False


def test_high_bitrate_is_playable():
    # 1080p H.264 → plafond 25000 kbps ; 40000 dépasse.
    v = evaluate(_video(bitrate_kbps=40000))
    assert v["status"] == "playable"
    assert v["checks"]["bitrate"]["ok"] is False


def test_unknown_codec_is_nonconform():
    v = evaluate(_video(codec="prores"))
    assert v["status"] == "nonconform"
    assert v["checks"]["codec"]["ok"] is False


def test_unknown_gop_does_not_downgrade():
    # GOP indéterminé (None) ne doit pas faire chuter le verdict.
    v = evaluate(_video(gop={"max_gop_sec": None}))
    assert v["status"] == "ready"
    assert v["checks"]["gop"]["ok"] is None


def test_no_video_stream_is_ready():
    assert evaluate({})["status"] == "ready"
    assert evaluate({"audio": {"codec": "aac"}})["status"] == "ready"


def test_is_cfr():
    assert is_cfr("25/1", "25/1") is True
    assert is_cfr("30000/1001", "24000/1001") is False
    assert is_cfr(None, "25/1") is None


def test_bitrate_ceiling_scales_and_hevc_lower():
    c_4k = bitrate_ceiling_kbps("h264", 3840, 2160)
    c_1080 = bitrate_ceiling_kbps("h264", 1920, 1080)
    assert c_4k > c_1080
    assert bitrate_ceiling_kbps("hevc", 3840, 2160) < c_4k
    assert bitrate_ceiling_kbps("h264", None, None) is None


def test_detect_faststart(tmp_path):
    def box(typ: bytes) -> bytes:
        # Atome ISOBMFF minimal : size(4) + type(4) + 8 octets de charge.
        return (16).to_bytes(4, "big") + typ + b"\x00" * 8

    fast = tmp_path / "fast.mp4"
    fast.write_bytes(box(b"ftyp") + box(b"moov") + box(b"mdat"))
    assert _detect_faststart(str(fast)) is True

    slow = tmp_path / "slow.mp4"
    slow.write_bytes(box(b"ftyp") + box(b"mdat") + box(b"moov"))
    assert _detect_faststart(str(slow)) is False

    nomoov = tmp_path / "x.mkv"
    nomoov.write_bytes(box(b"ftyp"))
    assert _detect_faststart(str(nomoov)) is None
