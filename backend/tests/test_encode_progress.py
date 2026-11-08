"""Progression d'encodage : analyse de la sortie `ffmpeg -progress` + forme publiée.

Ces fonctions sont PURES (aucun process, aucun Redis) parce que ce sont elles qui portent
les pièges de format. Le reste de la chaîne (Popen, tube, échéance) ne se teste utilement
qu'en exerçant un vrai ffmpeg, ce que le worker fait en production.
"""

from app.services import encode_progress
from app.workers.media_worker import _parse_progress_line, _progress_snapshot


def _feed(lines: list[str]) -> dict:
    state: dict = {}
    for line in lines:
        _parse_progress_line(line, state)
    return state


class TestParseProgressLine:
    def test_out_time_ms_contient_des_microsecondes(self):
        """🔑 LE piège du format : `out_time_ms` est un nom TROMPEUR, ffmpeg y écrit des
        microsecondes. Le lire comme des millisecondes donnerait une progression 1000×
        trop rapide — barre pleine en une seconde sur un encodage d'une heure."""
        state = _feed(["out_time_ms=30000000"])          # 30 s de source encodés
        assert state["done_ms"] == 30_000                 # et non 30_000_000

    def test_out_time_us_meme_unite(self):
        assert _feed(["out_time_us=30000000"])["done_ms"] == 30_000

    def test_repli_sur_out_time_horaire(self):
        """Si les clés numériques manquent, on sait encore lire `HH:MM:SS.micro`."""
        assert _feed(["out_time=00:01:30.500000"])["done_ms"] == 90_500

    def test_les_cles_numeriques_priment_sur_le_repli(self):
        state = _feed(["out_time_us=5000000", "out_time=00:10:00.000000"])
        assert state["done_ms"] == 5_000

    def test_valeurs_na_au_demarrage_ne_cassent_rien(self):
        """ffmpeg émet `N/A` tant que rien n'est encodé — une exception ici tuerait
        l'encodage pour un problème d'affichage."""
        state = _feed(["out_time_us=N/A", "speed=N/A"])
        assert "done_ms" not in state and "speed" not in state

    def test_vitesse_avec_suffixe_x(self):
        assert _feed(["speed=2.4x"])["speed"] == 2.4

    def test_seul_le_marqueur_de_fin_de_bloc_declenche_une_publication(self):
        """ffmpeg émet ~10 lignes par bloc ; publier à chacune multiplierait par dix les
        écritures Redis pour la même information."""
        state: dict = {}
        assert _parse_progress_line("frame=250", state) is False
        assert _parse_progress_line("speed=1.2x", state) is False
        assert _parse_progress_line("progress=continue", state) is True

    def test_fin_d_encodage_signalee(self):
        state: dict = {}
        _parse_progress_line("progress=end", state)
        assert state["ended"] is True

    def test_ligne_sans_egal_ignoree(self):
        state: dict = {}
        assert _parse_progress_line("bruit sur la sortie", state) is False
        assert state == {}


class TestProgressSnapshot:
    def test_pourcentage_et_temps_restant(self):
        state = {"done_ms": 30_000, "speed": 2.0}
        pct, eta, speed = _progress_snapshot(state, total_ms=120_000)
        assert pct == 25.0
        assert eta == 45          # 90 s de source restants à 2× temps réel
        assert speed == 2.0

    def test_sans_duree_totale_aucun_pourcentage_invente(self):
        """Source sans durée sondable : on montre une activité, jamais un chiffre faux."""
        pct, eta, _ = _progress_snapshot({"done_ms": 30_000, "speed": 1.0}, total_ms=None)
        assert pct is None and eta is None

    def test_sans_vitesse_pas_d_estimation(self):
        pct, eta, _ = _progress_snapshot({"done_ms": 30_000}, total_ms=120_000)
        assert pct == 25.0 and eta is None

    def test_fin_d_encodage_cale_a_cent(self):
        """Mesuré sur un ffmpeg réel : le dernier `out_time` d'une source de 20 s donne
        99,665 %. La barre resterait figée à 99 % pendant l'upload et la conformité qui
        SUIVENT l'encodage — un blocage apparent."""
        state = {"done_ms": 19_933, "speed": 9.4, "ended": True}
        pct, eta, _ = _progress_snapshot(state, total_ms=20_000)
        assert pct == 100.0 and eta == 0

    def test_fin_sans_duree_totale_ne_fabrique_pas_de_pourcentage(self):
        pct, _, _ = _progress_snapshot({"done_ms": 100, "ended": True}, total_ms=None)
        assert pct is None

    def test_le_pourcentage_ne_depasse_jamais_cent(self):
        """ffmpeg peut annoncer un out_time légèrement supérieur à la durée sondée
        (arrondis de conteneur) — une barre à 103 % se lit comme un bug."""
        pct, _, _ = _progress_snapshot({"done_ms": 121_000, "speed": 1.0}, total_ms=120_000)
        assert pct == 100.0


class TestPayload:
    def test_forme_canonique(self):
        p = encode_progress.payload(pct=42.46, eta_s=310, speed=1.777, phase="encode")
        assert p["pct"] == 42.5 and p["eta_s"] == 310 and p["speed"] == 1.78
        assert p["phase"] == "encode" and "at" in p

    def test_champs_inconnus_absents_plutot_que_nuls(self):
        """Le front distingue « pas de pourcentage » de « 0 % » : on omet la clé."""
        p = encode_progress.payload(pct=None, eta_s=None, speed=None, phase="encode")
        assert "pct" not in p and "eta_s" not in p and "speed" not in p

    def test_profil_porte_pour_une_rendition(self):
        p = encode_progress.payload(pct=10, eta_s=5, speed=1, phase="rendition", profile="hd720")
        assert p["profile"] == "hd720"

    def test_bornes(self):
        assert encode_progress.payload(pct=-5, eta_s=-1, speed=1, phase="x")["pct"] == 0.0
        assert encode_progress.payload(pct=140, eta_s=1, speed=1, phase="x")["pct"] == 100.0

    def test_cle_redis_stable(self):
        """La clé est la seule chose que le worker et le backend partagent : elle ne doit
        pas dériver d'un côté sans l'autre."""
        assert encode_progress.key(42) == "signflow:media:42:enc"


class TestTelechargement:
    """Phase `download` : le média restait « en cours » SANS barre pendant toute la
    recuperation du fichier — ~9 s pour 1,7 Go en local, mais ~105 s de silence sur un
    master 4K de 20 Go, ce qui se lit comme un blocage."""

    def test_l_avancement_du_telechargement_est_publie(self, monkeypatch):
        from unittest.mock import MagicMock

        import app.workers.media_worker as mw
        from app.services import encode_progress

        # Le pas de publication est neutralisé : on teste le CALCUL, pas la cadence.
        monkeypatch.setattr(mw, "_PROGRESS_MIN_INTERVAL_S", 0.0)

        # `mw.encode_progress` EST le module importé ici — un seul patch suffit.
        seen: list[dict] = []
        monkeypatch.setattr(encode_progress, "publish", lambda _id, data: seen.append(data))

        s3 = MagicMock()
        s3.head_object.return_value = {"ContentLength": 1000}

        def _dl(Bucket, Key, Filename, Callback=None):  # noqa: N803
            with open(Filename, "wb") as f:
                f.write(b"")
            for _ in range(4):
                Callback(250)

        s3.download_file.side_effect = _dl

        import tempfile

        dest = tempfile.mktemp()
        mw._download_with_progress(s3, "k/gros.mp4", dest, id_media=7)

        assert seen, "aucune progression publiée pendant le téléchargement"
        assert all(d["phase"] == "download" for d in seen)
        pcts = [d["pct"] for d in seen if "pct" in d]
        assert pcts[-1] == 100.0
        assert all(b >= a for a, b in zip(pcts, pcts[1:]))
        # ⚠️ Pas de `speed` : le champ signifie « × le temps réel » pour un encodage.
        # Y mettre un débit d'octets afficherait « 190× le temps réel » sur un
        # téléchargement, ce qui ne veut rien dire.
        assert all("speed" not in d for d in seen)

    def test_taille_inconnue_barre_indeterminee_et_pas_d_echec(self, monkeypatch):
        """`head_object` peut échouer (droits, objet en cours d'écriture) : on télécharge
        quand même, sans inventer de pourcentage."""
        from unittest.mock import MagicMock

        import app.workers.media_worker as mw
        from app.services import encode_progress

        monkeypatch.setattr(mw, "_PROGRESS_MIN_INTERVAL_S", 0.0)
        seen: list[dict] = []
        monkeypatch.setattr(mw.encode_progress, "publish", lambda _id, d: seen.append(d))

        s3 = MagicMock()
        s3.head_object.side_effect = RuntimeError("pas de droits")

        def _dl(Bucket, Key, Filename, Callback=None):  # noqa: N803
            open(Filename, "wb").close()
            Callback(100)

        s3.download_file.side_effect = _dl

        import tempfile

        mw._download_with_progress(s3, "k/x.mp4", tempfile.mktemp(), id_media=8)
        assert seen and all("pct" not in d for d in seen)

    def test_sans_media_identifie_aucune_machinerie(self, monkeypatch):
        """Pas d'id → pas de lecteur possible : on retombe sur le téléchargement simple,
        sans même interroger la taille."""
        from unittest.mock import MagicMock

        import app.workers.media_worker as mw
        import tempfile

        s3 = MagicMock()
        mw._download_with_progress(s3, "k/x.mp4", tempfile.mktemp(), id_media=None)
        s3.head_object.assert_not_called()
        s3.download_file.assert_called_once()
