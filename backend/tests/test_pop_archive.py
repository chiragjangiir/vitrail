"""Tests des helpers purs d'archivage Proof of Play (§XXIV, PLAN_POP_ARCHIVAL).

Isolés de la DB / MinIO : nommage/parse des partitions journalières, borne de rétention,
sérialisation CSV.gz + recalcul du merkle_root, agrégat par player (chaîne + signatures).
"""

import csv
import gzip
import io
from datetime import date, datetime, timezone

import pytest

from app.services import pop_archive, pop_counting, pop_proof


def _dt(day: str, h: int = 10, m: int = 0, s: int = 0) -> datetime:
    y, mo, d = (int(x) for x in day.split("-"))
    return datetime(y, mo, d, h, m, s, tzinfo=timezone.utc)


def test_partition_naming_roundtrip():
    d = date(2026, 7, 2)
    name = pop_archive.day_partition_name(d)
    assert name == "cms_proof_of_play_2026_07_02"
    assert pop_archive.parse_partition_day(name) == d


def test_parse_partition_skips_non_daily():
    # partition DEFAULT + vieille partition MENSUELLE + nom étranger → None (pas droppées)
    assert pop_archive.parse_partition_day("cms_proof_of_play_default") is None
    assert pop_archive.parse_partition_day("cms_proof_of_play_2026_07") is None
    assert pop_archive.parse_partition_day("cms_media") is None
    assert pop_archive.parse_partition_day("cms_proof_of_play_2026_13_40") is None  # date invalide


def test_retention_cutoff():
    assert pop_archive.retention_cutoff(date(2026, 7, 2), 90) == date(2026, 4, 3)
    assert pop_archive.retention_cutoff(date(2026, 7, 2), 0) == date(2026, 7, 2)


def _row(id_pop: int, merkle: str, **over) -> dict:
    """Une ligne telle que le worker la lit — donc portant TOUTES les colonnes de
    `ARCHIVE_COLUMNS`. Les anciennes fixtures en omettaient les drapeaux, ce qui reproduisait
    exactement le défaut du worker et le rendait invisible."""
    row = {"id_pop": id_pop, "id_player": 5, "id_playlist": 3, "id_media": 10,
           "played_at": _dt("2026-06-25", 8), "duration_ms": 5000,
           "merkle_hash": merkle, "signature": None,
           "screen_off": False, "covered": False}
    row.update(over)
    return row


def test_csv_gz_roundtrip_merkle():
    rows = [
        _row(1, "a" * 64),
        _row(2, "b" * 64, id_media=11, played_at=_dt("2026-06-25", 9),
             duration_ms=3000, signature="sig=="),
    ]
    gz = pop_archive.build_csv_gz(rows)
    root, count = pop_archive.merkle_root_from_csv_gz(gz)
    assert count == 2
    # le merkle recalculé depuis le CSV.gz == merkle des hashes dans l'ordre du fichier
    assert root == pop_proof.merkle_root(["a" * 64, "b" * 64])


def test_archive_reads_every_non_counting_flag_it_writes():
    """Ce que le SELECT lit et ce que le CSV écrit viennent d'une seule liste.

    La garde qui manquait : `screen_off` (0102) puis `covered` (0125) ont été ajoutées à la
    constante du worker sans l'être au SELECT, et rien ne l'a dit. Une 3ᵉ cause de
    non-comptage sera automatiquement couverte des deux côtés — ou fera tomber ce test.
    """
    sql = pop_archive.select_rows_sql()
    for flag in pop_counting.NON_COUNTING_FLAGS:
        assert flag in pop_archive.ARCHIVE_COLUMNS, f"{flag} n'est pas relu par l'archivage"
        assert flag in pop_archive.CSV_HEADER, f"{flag} n'atteint pas le CSV froid"
        assert flag in sql, f"{flag} est absent du SELECT réellement exécuté"


def test_flag_list_and_counting_condition_agree():
    """La liste qui alimente l'archivage et la condition qui exclut des comptages doivent
    parler des mêmes drapeaux.

    Sans ce lien, retirer un drapeau de la liste laisserait tous les autres tests verts — la
    cohérence interne serait intacte — pendant que le froid cesserait silencieusement de
    distinguer une preuve non comptée. Ici, `COUNTED_SQL` sert de témoin indépendant.
    """
    for flag in pop_counting.NON_COUNTING_FLAGS:
        assert flag in pop_counting.COUNTED_SQL
    # et l'inverse : aucune cause connue des comptages ne manque à la liste de l'archivage
    for flag in ("screen_off", "covered"):
        assert flag in pop_counting.NON_COUNTING_FLAGS


def test_flags_survive_the_worker_pipeline():
    """Chaîne complète telle que le worker l'exécute : colonnes du SELECT → dict → CSV.

    C'est le trajet qui était rompu. Une preuve écran coupé ou recouverte doit ressortir du
    froid marquée comme telle : après le DROP de la partition, l'archive est la seule trace,
    et une preuve non comptée archivée en « diffusion normale » est irréversible.
    """
    # Le curseur rend les valeurs dans l'ordre des colonnes demandées, comme psycopg2.
    values = {"id_pop": 7, "id_player": 5, "id_playlist": None, "id_media": 42,
              "played_at": _dt("2026-06-25", 8), "duration_ms": 9000,
              "merkle_hash": "c" * 64, "signature": None,
              "screen_off": False, "covered": True}
    fetched = tuple(values[c] for c in pop_archive.ARCHIVE_COLUMNS)
    row = dict(zip(pop_archive.ARCHIVE_COLUMNS, fetched))

    text = gzip.decompress(pop_archive.build_csv_gz([row])).decode("utf-8")
    parsed = next(csv.DictReader(io.StringIO(text)))
    assert parsed["covered"] == "true"
    assert parsed["screen_off"] == "false"


def test_incomplete_row_is_refused_rather_than_mislabelled():
    """Une ligne à laquelle il manque un drapeau interrompt l'archivage.

    Le `.get()` d'origine rendait « false » pour une colonne que le SELECT ne lisait plus :
    l'archive partait, fausse, et la partition était droppée derrière. Échouer bruyamment
    est le seul comportement rattrapable.
    """
    incomplete = _row(1, "a" * 64)
    del incomplete["covered"]
    with pytest.raises(KeyError):
        pop_archive.build_csv_gz([incomplete])


def _chain_rows(id_player: int, medias: list[int], day: str) -> list[dict]:
    """Construit une chaîne de hachage VALIDE pour un player (comme l'ingestion)."""
    prev = f"genesis:{id_player}"
    rows = []
    for i, mid in enumerate(medias):
        played = _dt(day, 10, i)
        played_iso = played.astimezone(timezone.utc).isoformat()
        h = pop_proof.chain_hash(prev, id_player, mid, played_iso, 1000)
        rows.append({"id_pop": i + 1, "id_player": id_player, "id_playlist": None,
                     "id_media": mid, "played_at": played, "duration_ms": 1000,
                     "merkle_hash": h, "signature": None})
        prev = h
    return rows


def test_aggregate_valid_chain():
    rows = _chain_rows(5, [10, 11, 12], "2026-06-25")
    players, root = pop_archive.aggregate(rows, keys={5: None}, names={5: "NUC"})
    assert root is not None
    assert len(players) == 1
    p = players[0]
    assert p["player_name"] == "NUC"
    assert p["plays"] == 3
    assert p["unsigned"] == 3
    assert p["signed"] == 0
    assert p["chain_valid"] is True
    assert p["merkle_root"] == pop_proof.merkle_root([r["merkle_hash"] for r in rows])


def test_aggregate_detects_broken_chain():
    rows = _chain_rows(5, [10, 11, 12], "2026-06-25")
    rows[1]["merkle_hash"] = "f" * 64  # altération d'un maillon
    players, _ = pop_archive.aggregate(rows, keys={5: None}, names={})
    assert players[0]["chain_valid"] is False
    assert players[0]["player_name"] == "Player #5"  # nom absent → repli
