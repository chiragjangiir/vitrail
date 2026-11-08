"""Tests du média pointeur « Entrée HDMI » (item de playlist BrightSign XT/4K/XD).

Logique pure : bloc media émis au sync + gate de capacité par modèle
(`_player_has_hdmi_input`, miroir serveur de bsHasHdmiInput frontend).
"""

from app.api.v1.endpoints.ws import _hdmi_input_media_dict, _player_has_hdmi_input


class _Media:
    id_media = 42
    media_name = "TV du magasin"
    mime_type = "application/x-hdmi-input"
    media_metadata = {"input": "hdmi"}


class _Player:
    def __init__(self, caps):
        self.capabilities = caps


def test_hdmi_input_media_dict_is_pure_pointer():
    """Aucun fichier : pas d'URL, rien à cacher — l'item est un ordre de bascule."""
    d = _hdmi_input_media_dict(_Media())
    assert d["media_type"] == "hdmi_input"
    assert d["id_media"] == 42
    assert d["url"] is None
    assert d["cache_key"] is None
    assert d["cache_checksum"] is None
    assert d["checksum_sha256"] == ""


def test_player_has_hdmi_input_model_matrix():
    """Gamme XT + 4K1142/4K1242 + XD1230 = entrée HDMI ; HD/LS = non."""
    def has(model):
        return _player_has_hdmi_input(_Player({"bs_model": model}))

    assert has("XT1144")      # domicile (validé HW)
    assert has("XT1145")
    assert has("XT2145")
    assert has("xt1143")      # insensible à la casse
    assert has("4K1142")
    assert has("4K1242")
    assert has("XD1230")
    assert not has("HD1024")  # domicile — PAS d'entrée HDMI
    assert not has("HD224")
    assert not has("LS424")
    assert not has("")


def test_player_has_hdmi_input_missing_caps():
    """Player sans capabilities / sans bs_model (Electron, Android…) → jamais capable."""
    assert not _player_has_hdmi_input(None)
    assert not _player_has_hdmi_input(_Player(None))
    assert not _player_has_hdmi_input(_Player({}))
    assert not _player_has_hdmi_input(_Player({"platform": "linux"}))


# ── Endpoint de création (API) ───────────────────────────────────────────────
# Réutilise les fixtures org/auth de test_url_display (mêmes permissions media).

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.models.media import CmsMedia  # noqa: E402
from tests.test_url_display import _h, auth, org  # noqa: E402,F401


@pytest.mark.asyncio
async def test_create_hdmi_input_media(client, db_session, org, auth):  # noqa: F811
    resp = await client.post("/api/v1/media/hdmi-input", headers=_h(auth),
                             json={"name": "TV du magasin"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["media_type"] == "hdmi_input"
    media = (await db_session.execute(
        select(CmsMedia).where(CmsMedia.id_media == body["id_media"]))).scalar_one()
    assert media.storage_key == ""           # sentinelle : pas de fichier
    assert media.transcode_status == "done"  # directement diffusable
    assert media.source == "hdmi"


@pytest.mark.asyncio
async def test_create_hdmi_input_requires_permission(client, org):  # noqa: F811
    resp = await client.post("/api/v1/media/hdmi-input", json={"name": "X"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_hdmi_input_media_detail(client, db_session, org, auth):  # noqa: F811
    """GET /media/{id} sur un média pointeur (storage_key='') ne doit PAS signer d'URL
    (botocore rejette une clé vide → 500 constaté en prod le 2026-07-07)."""
    created = (await client.post("/api/v1/media/hdmi-input", headers=_h(auth),
                                 json={"name": "TV"})).json()
    resp = await client.get(f"/api/v1/media/{created['id_media']}", headers=_h(auth))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cdn_url_signed"] is None
    assert body["media_type"] == "hdmi_input"
