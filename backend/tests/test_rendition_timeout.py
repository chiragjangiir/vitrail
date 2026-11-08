"""Une rendition qui EXPIRE ne doit pas être rejouée (règle de la 1.0.24, jamais appliquée
à `generate_rendition` avant le 2026-08-03).

Une expiration est **déterministe** : rejouer le même encodage avec les mêmes paramètres
expirera de la même façon. Avec `max_retries=2`, on brûlait 3 fois le budget — jusqu'à
90 min de processeur pour un échec garanti, en affamant les autres encodages.
"""

import subprocess
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def rendition_media():
    """Média posé par la MÊME voie que le worker (psycopg2), pas par la session de test.

    🔑 Piège vécu en écrivant ce test : la fixture ORM ne rendait rien de visible au
    worker, qui ouvre sa PROPRE connexion psycopg2 — la tâche ne trouvait aucun média et
    sortait aussitôt. Résultat : le test « passait » sans avoir jamais lancé d'encodage.
    Un test qui ne pose pas ses données là où le code les lit ne prouve rien.
    """
    from app.workers.media_worker import _db_conn

    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cms_organizations (org_name, org_slug) VALUES (%s, %s) RETURNING id_org",
        ("RendOrg", f"rend-{uuid.uuid4().hex[:8]}"),
    )
    id_org = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO cms_media (id_org, media_name, media_type, storage_key, checksum_sha256,"
        " transcode_status, width, height) VALUES (%s,'gros.mp4','video',%s,%s,'done',3840,2160)"
        " RETURNING id_media",
        (id_org, f"t/{uuid.uuid4().hex}.mp4", "r" * 64),
    )
    id_media = cur.fetchone()[0]
    conn.commit()
    yield id_media
    cur.execute("DELETE FROM cms_media_renditions WHERE id_parent=%s", (id_media,))
    cur.execute("DELETE FROM cms_media WHERE id_media=%s", (id_media,))
    cur.execute("DELETE FROM cms_organizations WHERE id_org=%s", (id_org,))
    conn.commit()
    cur.close()
    conn.close()


def _rendition_status(id_media: int) -> str | None:
    from app.workers.media_worker import _db_conn

    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM cms_media_renditions WHERE id_parent=%s", (id_media,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def _stub_s3(tmp_path_factory) -> MagicMock:
    s3 = MagicMock()
    s3.head_object.return_value = {"ContentLength": 1024}

    def _dl(Bucket, Key, Filename, Callback=None):  # noqa: N803 — signature boto3
        with open(Filename, "wb") as f:
            f.write(b"\x00" * 1024)
        if Callback:
            Callback(1024)

    s3.download_file.side_effect = _dl
    return s3


@pytest.mark.asyncio
async def test_une_rendition_expiree_n_est_PAS_rejouee(
    rendition_media: int, tmp_path_factory,
) -> None:
    from app.workers.media_worker import generate_rendition

    probe = {"width": 3840, "height": 2160, "duration_ms": 900_000, "is_hdr": False,
             "has_audio": True, "fps": 25.0, "src_kbps": 20_000}

    with patch("app.workers.media_worker._s3", return_value=_stub_s3(tmp_path_factory)), \
         patch("app.workers.media_worker._probe", return_value=probe), \
         patch("app.workers.media_worker._run_ffmpeg",
               side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1800)) as run:
        result = generate_rendition.apply(args=(rendition_media, "fhd"))

    # `apply()` rend l'état RETRY quand la tâche demande une reprise. SUCCESS = elle a
    # échoué franchement, une seule fois — c'est tout le point.
    assert result.state == "SUCCESS", "une expiration ne doit pas déclencher de reprise"
    # Une seule tentative matérielle : le repli logiciel ne doit pas non plus s'enclencher
    # sur une EXPIRATION (ce n'est pas un GPU capricieux, c'est une source trop lourde).
    assert run.call_count == 1

    # L'échec reste VISIBLE : la ligne d'artefact est marquée en échec, pas effacée.
    assert _rendition_status(rendition_media) == "failed"


@pytest.mark.asyncio
async def test_une_panne_ORDINAIRE_reste_rejouee(
    rendition_media: int, tmp_path_factory,
) -> None:
    """Le pendant du test précédent : on ne supprime pas TOUTE reprise. Une erreur
    passagère (disque plein momentané, GPU occupé) mérite une seconde chance — seule
    l'expiration est déterministe.

    Ce qui est asserté est le NOMBRE D'APPELS à ffmpeg, pas l'état Celery : c'est la mesure
    directe de « rejouée ou non », et elle ne dépend pas des subtilités du mode d'exécution
    (mesuré : `apply()` absorbe les reprises et n'expose ni `RETRY` ni exception).
    Sans ce test, supprimer *toute* reprise passerait inaperçu — et une panne d'une seconde
    condamnerait définitivement un artefact.
    """
    from app.workers.media_worker import generate_rendition

    probe = {"width": 1920, "height": 1080, "duration_ms": 60_000, "is_hdr": False,
             "has_audio": False, "fps": 25.0, "src_kbps": 5_000}

    with patch("app.workers.media_worker._s3", return_value=_stub_s3(tmp_path_factory)), \
         patch("app.workers.media_worker._probe", return_value=probe), \
         patch("app.workers.media_worker._run_ffmpeg",
               side_effect=OSError("disque plein")) as run:
        generate_rendition.apply(args=(rendition_media, "fhd"))

    # Plusieurs tentatives : la reprise ordinaire est bien conservée.
    assert run.call_count > 1
