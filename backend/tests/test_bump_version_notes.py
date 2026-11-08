"""Garde-fou d'encodage des notes de release (`deploy/registry/bump-version.py`).

Pourquoi ce test existe : le 2026-08-03, des notes de release sont parties chez les clients
en double-encodage UTF-8 (« médias » affiché « mÃ©dias » dans la cloche de mise à jour).
Le garde-fou refuse désormais de stager de telles notes.

🔑 Le vrai risque de ce garde-fou n'est PAS de rater un mojibake, c'est de **rejeter du
français légitime** : « château », « âge » et « bâtiment » contiennent tous « â », qui est
aussi un marqueur de double-encodage. C'est pour ça qu'on teste un aller-retour et non une
liste de marqueurs — et c'est ce que la moitié de ces tests vérifie.
"""

import importlib.util
from pathlib import Path

import pytest

def _find_script() -> Path | None:
    """`deploy/` n'est PAS monté dans le conteneur backend (seul `backend/` l'est) : le
    test se saute alors proprement et tourne en CI, où le dépôt entier est présent.
    Un chemin de secours permet de le forcer en local (SIGNFLOW_REPO)."""
    import os

    # ⚠️ Pas de chemin « pratique » en dur (type /repo) : une copie oubliée du script y
    # deviendrait PÉRIMÉE et le test passerait contre une version qui n'existe plus.
    # Un chemin explicite s'opte, donc on sait ce qu'on teste.
    #
    # 🔑 Depuis Git Bash sous Windows, préfixer l'appel de `MSYS_NO_PATHCONV=1` : sans lui,
    # MSYS réécrit `/repo` en `C:/Program Files/Git/repo` et la variable pointe à côté —
    # le test se saute alors en donnant l'impression que l'échappatoire ne marche pas
    # (vécu le 2026-08-03, une bonne minute perdue à soupçonner le mauvais coupable).
    candidates = [Path(__file__).resolve().parents[2]]
    if os.environ.get("SIGNFLOW_REPO"):
        candidates.insert(0, Path(os.environ["SIGNFLOW_REPO"]))
    for root in candidates:
        p = root / "deploy" / "registry" / "bump-version.py"
        if p.is_file():
            return p
    return None


_SCRIPT = _find_script()
pytestmark = pytest.mark.skipif(
    _SCRIPT is None, reason="deploy/ absent de ce conteneur (le test tourne en CI)"
)


def _load():
    """Le script porte un tiret dans son nom : import par chemin."""
    spec = importlib.util.spec_from_file_location("bump_version", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # `main()` n'est appelé que sous __main__
    return mod


bv = _load() if _SCRIPT else None


class TestTexteSain:
    """Aucun de ces cas ne doit être refusé — un faux positif bloquerait une release."""

    @pytest.mark.parametrize("texte", [
        "Media encoding: live progress bar",                    # ASCII pur
        "Encodage des médias : barre de progression",           # accents français
        "Le château a l'âge de pierre, bâtiment compris",       # « â » LÉGITIME
        "Estimation avant démarrage — ou définition inférieure", # tiret cadratin
        "Précisions : coût, délai, écran, œuvre, français",
        "Kodierung — Kapazität, Übersicht, Größe",              # allemand
        "Codificação: capacidade, análise, atenção",            # portugais
        "Codificación: capacidad, análisis, atención",          # espagnol
    ])
    def test_non_signale(self, texte):
        assert bv.repaired_if_double_encoded(texte) is None

    def test_check_notes_laisse_passer(self):
        bv.check_notes_encoding({"en": "Progress bar", "fr": "Barre de progression — médias"})


class TestDoubleEncodage:
    def test_detecte_et_repare(self):
        """Le cas RÉEL qui est parti en production."""
        casse = "Encodage des mÃ©dias : barre de progression"
        assert bv.repaired_if_double_encoded(casse) == "Encodage des médias : barre de progression"

    def test_detecte_le_tiret_cadratin_casse(self):
        """C'est ce caractère qui avait fait échouer ma première réparation (latin-1 ne
        couvre pas 0x80-0x9F) — il doit être détecté, pas contourné."""
        casse = "measured before they start â€” you can run them"
        assert bv.repaired_if_double_encoded(casse) == "measured before they start — you can run them"

    def test_stage_refuse_avec_un_message_actionnable(self):
        with pytest.raises(SystemExit):
            bv.check_notes_encoding({"en": "ok", "fr": "des mÃ©dias"})

    def test_le_message_montre_le_fragment_et_l_attendu(self, capsys):
        """Un « c'est cassé » sans montrer quoi n'est pas croyable — et donc pas actionné."""
        with pytest.raises(SystemExit):
            bv.check_notes_encoding({"fr": "des mÃ©dias en 4K"})
        # ⚠️ `readouterr()` VIDE le tampon : l'appeler deux fois rend la seconde vide.
        capture = capsys.readouterr()
        sortie = capture.out + capture.err
        assert "DOUBLE-ENCODAGE" in sortie
        assert "attendu" in sortie
