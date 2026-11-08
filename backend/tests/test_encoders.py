"""Tests de la sélection d'encodeur (app/core/encoders.py).

Pas de GPU en CI → on mocke `detect_hw_encoders` pour valider la logique de préférence
et le repli logiciel. Un test d'intégration réel (test-encode) tournerait sur une machine
avec GPU mais n'est pas requis ici.
"""

import importlib

from app.core import encoders


def _patch_avail(monkeypatch, names):
    monkeypatch.setattr(encoders, "detect_hw_encoders", lambda: tuple(names))


def test_best_encoder_software_fallback(monkeypatch):
    _patch_avail(monkeypatch, [])
    assert encoders.best_encoder("h264") == {"name": "libx264", "kind": "sw", "vaapi_device": None}
    assert encoders.best_encoder("hevc")["name"] == "libx265"


def test_best_encoder_prefers_nvenc(monkeypatch):
    _patch_avail(monkeypatch, ["h264_vaapi", "h264_qsv", "h264_nvenc"])
    b = encoders.best_encoder("h264")
    assert b["name"] == "h264_nvenc" and b["kind"] == "nvenc"


def test_best_encoder_qsv_over_vaapi(monkeypatch):
    monkeypatch.setattr(encoders, "vaapi_device", lambda: "/dev/dri/renderD128")
    _patch_avail(monkeypatch, ["h264_vaapi", "h264_qsv"])
    b = encoders.best_encoder("h264")
    assert b["name"] == "h264_qsv" and b["kind"] == "qsv"


def test_best_encoder_vaapi_carries_device(monkeypatch):
    monkeypatch.setattr(encoders, "vaapi_device", lambda: "/dev/dri/renderD129")
    _patch_avail(monkeypatch, ["h264_vaapi"])
    b = encoders.best_encoder("h264")
    assert b == {"name": "h264_vaapi", "kind": "vaapi", "vaapi_device": "/dev/dri/renderD129"}


def test_hevc_picks_hevc_encoder(monkeypatch):
    _patch_avail(monkeypatch, ["h264_nvenc", "hevc_nvenc"])
    assert encoders.best_encoder("hevc")["name"] == "hevc_nvenc"
    # h264 ne doit pas piocher un encodeur hevc
    _patch_avail(monkeypatch, ["hevc_nvenc"])
    assert encoders.best_encoder("h264")["name"] == "libx264"


def test_kind_classification():
    assert encoders._kind("h264_nvenc") == "nvenc"
    assert encoders._kind("h264_qsv") == "qsv"
    assert encoders._kind("hevc_vaapi") == "vaapi"
    assert encoders._kind("libx264") == "sw"


def test_disable_hwenc_env(monkeypatch):
    # SF_DISABLE_HWENC=1 → aucune détection HW, repli sw (on vide le cache lru).
    monkeypatch.setenv("SF_DISABLE_HWENC", "1")
    importlib.reload(encoders)
    try:
        assert encoders.detect_hw_encoders() == ()
        assert encoders.hw_encode_available() is False
        assert encoders.best_encoder("h264")["kind"] == "sw"
    finally:
        monkeypatch.delenv("SF_DISABLE_HWENC", raising=False)
        importlib.reload(encoders)
