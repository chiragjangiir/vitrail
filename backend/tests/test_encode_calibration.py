"""Étalonnage de l'encodage : bandes de décision, replis proposés, commande échantillon.

Fonctions PURES uniquement — la sonde elle-même (`_estimate_encode_seconds`) lance un vrai
ffmpeg et ne se teste utilement qu'en l'exerçant sur une vraie source, ce que fait le worker.
"""

import pytest

from app.workers.media_worker import (
    ENCODE_BAND_AUTO_S,
    ENCODE_BAND_REFUSE_S,
    _build_video_cmd,
    _decision_band,
    _downscale_options,
    _sample_cmd,
    _scaled_pixels,
)

UHD = {"width": 3840, "height": 2160, "duration_ms": 600_000, "is_hdr": False,
       "has_audio": True, "fps": 30.0, "src_kbps": 20_000}
FHD = {**UHD, "width": 1920, "height": 1080}


class TestBandes:
    def test_en_dessous_de_vingt_minutes_on_lance(self):
        assert _decision_band(ENCODE_BAND_AUTO_S - 1) == "auto"

    def test_entre_vingt_minutes_et_quatre_heures_l_utilisateur_decide(self):
        assert _decision_band(ENCODE_BAND_AUTO_S) == "confirm"
        assert _decision_band(ENCODE_BAND_REFUSE_S) == "confirm"

    def test_au_dela_de_quatre_heures_refus(self):
        assert _decision_band(ENCODE_BAND_REFUSE_S + 1) == "refuse"

    def test_sans_mesure_on_ne_bloque_JAMAIS(self):
        """Sonde impossible (source trop courte) ou en échec : on garde le comportement
        historique. Bloquer un upload sur une mesure qu'on n'a pas su faire serait pire
        que le mur qu'on essaie d'éviter."""
        assert _decision_band(None) == "auto"

    def test_les_bandes_valent_bien_ce_qui_a_ete_decide(self):
        """Garde anti-dérive : ce sont des valeurs validées par Ed, pas des réglages libres."""
        assert ENCODE_BAND_AUTO_S == 20 * 60
        assert ENCODE_BAND_REFUSE_S == 4 * 3600


class TestReplis:
    def test_une_4k_propose_1080p_et_720p_avec_leur_propre_estimation(self):
        """C'est ce qui transforme un refus en choix : « 4 h » seul est une impasse."""
        opts = _downscale_options(14_400, 3840, 2160)
        assert [o["profile"] for o in opts] == ["fhd", "hd720"]
        # 4K → 1080p = 4× moins de pixels ⇒ ~4× moins de temps.
        assert opts[0]["estimate_s"] == pytest.approx(3600, rel=0.02)
        assert opts[1]["estimate_s"] < opts[0]["estimate_s"]

    def test_une_source_deja_petite_ne_propose_pas_de_repli_plus_grand(self):
        """Proposer « encoder en 1080p » une source 1080p ne résoudrait rien."""
        assert [o["profile"] for o in _downscale_options(3600, 1920, 1080)] == ["hd720"]
        assert _downscale_options(3600, 1280, 720) == []

    def test_sans_resolution_connue_aucune_proposition_inventee(self):
        assert _downscale_options(9999, 0, 0) == []

    def test_mise_a_l_echelle_quadratique(self):
        assert _scaled_pixels(3840, 2160, 1920) == 3840 * 2160 // 4
        assert _scaled_pixels(1920, 1080, 3840) == 1920 * 1080   # jamais d'agrandissement


class TestCommandeEchantillon:
    def test_la_tranche_rejoue_la_MEME_commande(self):
        """🔑 Mesurer autre chose que la commande réelle reviendrait à étalonner un
        encodage qu'on ne lancera jamais (encodeur, filtres, codec, débit plafond)."""
        cmd = _build_video_cmd("/src.mkv", "/out.mp4", FHD)
        sample = _sample_cmd(cmd, "/sample.mp4", 42.0, 10)
        # Tout ce qui décide du coût est conservé, à l'identique.
        assert sample[sample.index("-c:v") + 1] == cmd[cmd.index("-c:v") + 1]
        assert "-ss" in sample and sample[sample.index("-ss") + 1] == "42.000"
        assert sample[sample.index("-t") + 1] == "10"
        assert sample[-1] == "/sample.mp4"
        assert "/out.mp4" not in sample

    def test_la_recherche_precede_l_entree(self):
        """`-ss` avant `-i` = recherche à l'entrée (rapide). Après, ffmpeg décoderait
        depuis le début — la sonde mesurerait le décodage, pas l'encodage."""
        sample = _sample_cmd(_build_video_cmd("/src.mkv", "/out.mp4", FHD), "/s.mp4", 5.0, 10)
        assert sample.index("-ss") < sample.index("-i")


class TestDefinitionInferieure:
    def test_une_4k_ramenee_en_1080p_sort_en_h264_pas_en_hevc(self):
        """🔑 Le point du repli : sans recalcul des dimensions EFFECTIVES, la sortie
        resterait en HEVC — l'encodeur le plus lent, celui-là même qu'on fuit."""
        plein = _build_video_cmd("/s.mkv", "/o.mp4", UHD, force_sw=True)
        reduit = _build_video_cmd("/s.mkv", "/o.mp4", UHD, force_sw=True, box=1920)
        assert plein[plein.index("-c:v") + 1] == "libx265"
        assert reduit[reduit.index("-c:v") + 1] == "libx264"

    def test_le_downscale_utilise_le_filtre_partage(self):
        cmd = _build_video_cmd("/s.mkv", "/o.mp4", UHD, force_sw=True, box=1280)
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=" in vf and "1280" in vf

    def test_sans_box_aucun_filtre_impose(self):
        """Non-régression : le chemin nominal ne doit pas gagner un scale au passage."""
        cmd = _build_video_cmd("/s.mkv", "/o.mp4", FHD, force_sw=True)
        assert "-vf" not in cmd

    def test_le_hdr_sait_aussi_reduire(self):
        """La branche HDR n'utilise pas `_enc_filter` (libx265 seul) : sans son propre
        scale, choisir « définition inférieure » sur une source HDR n'aurait rien réduit."""
        hdr = {**UHD, "is_hdr": True}
        cmd = _build_video_cmd("/s.mkv", "/o.mp4", hdr, box=1920)
        assert "-vf" in cmd and "1920" in cmd[cmd.index("-vf") + 1]
        assert cmd[cmd.index("-c:v") + 1] == "libx265"   # HDR reste en 10-bit x265
