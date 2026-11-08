"""Budget de temps d'un encodage vidéo — défaut mesuré sur le banc d'installation (2026-08-02).

Une source 4K de 205 s, encodée en libx265 sur un serveur SANS GPU, a été tuée à 1800 s sans
avoir fini : la première tentative prenait toujours le budget MATÉRIEL, et le budget logiciel
n'était atteignable que par la branche de repli — donc jamais quand le logiciel est le PREMIER
choix, ce qui est le cas de tout serveur sans carte graphique.
"""

from app.workers.media_worker import _encode_timeout

FHD = (1920, 1080)
UHD = (3840, 2160)


def test_l_ancienne_formule_tuait_bien_le_cas_du_banc():
    """Fige le défaut, sans dépendre de git : l'ancienne logique est reproduite ici.

    Avant le 2026-08-02, la première tentative prenait toujours `_hw_timeout`, quel que soit
    l'encodeur retenu — le budget logiciel n'existait que dans la branche de repli. Pour la
    source du banc (4K, 205 s, libx265, aucun GPU) cela donnait exactement les 1800 s qui l'ont
    tuée, alors que l'encodage n'avait pas fini.
    """
    dur = 205.0
    ancien_hw = max(1800, min(int(dur * 6), 10800))    # ce qui était RÉELLEMENT appliqué
    ancien_sw = max(1800, min(int(dur * 12), 14400))   # ce qui n'était atteignable qu'en repli
    assert ancien_hw == 1800, "c'est bien la valeur qui a tué l'encodage du banc"
    assert ancien_sw == 2460, "et même le budget logiciel d'alors aurait été trop court"

    nouveau, _ = _encode_timeout(dur, *UHD, "libx265")
    assert nouveau > ancien_sw, "le nouveau budget dépasse même l'ancien budget de repli"


def test_le_logiciel_ne_prend_plus_le_budget_du_materiel():
    """Le cas EXACT du banc : 4K, libx265, 205 s. Le budget doit dépasser les 1800 s fatals."""
    timeout, mult = _encode_timeout(205.0, *UHD, "libx265")
    assert timeout > 1800, (
        f"budget {timeout}s — c'est celui du matériel, l'encodage logiciel 4K y meurt"
    )
    assert mult > 12, "le multiplicateur doit tenir compte des pixels ET du codec"


def test_le_materiel_reste_sobre():
    """NVENC est peu sensible à la résolution : son budget ne doit pas exploser."""
    hw, hw_mult = _encode_timeout(205.0, *UHD, "h264_nvenc")
    sw, sw_mult = _encode_timeout(205.0, *UHD, "libx265")
    assert hw_mult < sw_mult, "le matériel ne doit pas hériter de la marge du logiciel"
    assert hw <= 10800, "plafond matériel à 3 h"
    assert sw <= 21600, "plafond logiciel à 6 h"


def test_le_cout_croit_avec_les_pixels():
    """Le même encodeur, quatre fois plus de pixels : le budget doit suivre."""
    fhd, _ = _encode_timeout(600.0, *FHD, "libx264")
    uhd, _ = _encode_timeout(600.0, *UHD, "libx264")
    assert uhd > fhd, "un encodage 4K ne coûte pas le même temps qu'un 1080p"


def test_x265_est_plus_lent_que_x264():
    """La règle produit envoie tout ce qui dépasse la FHD vers HEVC : les deux se cumulent.

    ⚠️ Durée choisie SOUS le plafond : à 600 s en 4K les deux le touchent et deviennent égaux,
    ce qui masquerait la différence (mon premier test tombait dans ce piège).
    """
    x264, _ = _encode_timeout(120.0, *UHD, "libx264")
    x265, _ = _encode_timeout(120.0, *UHD, "libx265")
    assert x265 > x264


def test_le_plafond_est_atteint_TRES_vite_en_4K_logiciel():
    """Constat qui justifie la suite : en 4K logiciel, le plafond de 6 h borne dès ~5 minutes
    de source. Autrement dit ce budget ne PROTÈGE que les sources courtes — au-delà, il
    plafonne et l'encodage sera tué quoi qu'il arrive. C'est la limite intrinsèque d'un
    multiplicateur, et la raison pour laquelle il faut passer à un ÉTALONNAGE de la machine
    avec avertissement AVANT la mise en file (décision d'Ed, 2026-08-02).
    """
    assert _encode_timeout(300.0, *UHD, "libx265")[0] == 21600  # 5 min de source → déjà plafonné
    assert _encode_timeout(120.0, *UHD, "libx265")[0] < 21600   # 2 min → encore proportionnel


def test_plancher_conserve_pour_les_sources_courtes():
    """Une vidéo de 3 s ne doit pas hériter d'un budget de 36 s : le plancher de 30 min tient."""
    assert _encode_timeout(3.0, *FHD, "libx264")[0] == 1800
    assert _encode_timeout(0.0, 0, 0, "?")[0] == 1800  # durée/résolution inconnues


def test_plafonds_respectes():
    """Une source très longue ne doit pas produire un budget sans fin."""
    assert _encode_timeout(100_000.0, *UHD, "libx265")[0] == 21600
    assert _encode_timeout(100_000.0, *UHD, "h264_nvenc")[0] == 10800
