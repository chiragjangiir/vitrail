"""Proof of Play — archivage (§XXIV, PLAN_POP_ARCHIVAL).

Helpers PURS (sans DB / sans I/O) réutilisés par le worker `archive_pop` et testables
isolément : nommage/parse des partitions journalières, calcul de la borne de rétention,
sérialisation CSV.gz d'une période, agrégat par player (intégrité de chaîne + signatures +
Merkle root) au format attendu par `pop_report.build_pop_report_pdf`.
"""

from __future__ import annotations

import csv
import gzip
import io
from datetime import date, timedelta, timezone

from app.services import pop_proof
from app.services.pop_counting import NON_COUNTING_FLAGS

PARTITION_PREFIX = "cms_proof_of_play_"

# Colonnes de `cms_proof_of_play` que l'archivage doit relire. Les drapeaux de non-comptage
# sont AJOUTÉS depuis `pop_counting` plutôt que recopiés : c'est la seule chose qui garantit
# qu'une 3ᵉ cause, le jour où elle existera, entre dans le froid sans que personne y pense.
ARCHIVE_COLUMNS: tuple[str, ...] = (
    "id_pop", "id_player", "id_playlist", "id_media",
    "played_at", "duration_ms", "merkle_hash", "signature",
) + NON_COUNTING_FLAGS

# En-tête du CSV.gz froid (lignes brutes = valeur légale, ré-importables / re-vérifiables).
# Ordre HISTORIQUE conservé (id_media avant id_playlist, `played_at_utc` explicite) : il est
# documenté et relu par des tiers. Les drapeaux restent EN FIN — les archives antérieures ne
# les ont pas, et `merkle_root_from_csv_gz` lit par NOM (DictReader) → elles restent vérifiables.
CSV_HEADER = [
    "id_pop", "id_player", "id_media", "id_playlist",
    "played_at_utc", "duration_ms", "merkle_hash", "signature",
    *NON_COUNTING_FLAGS,
]


def select_rows_sql() -> str:
    """Le `SELECT` que le worker exécute pour une org et un jour donnés.

    Construit ici, à côté de `build_csv_gz`, pour que les colonnes lues et les colonnes
    écrites viennent d'une seule liste. C'est du texte, pas de l'I/O : le module reste pur.
    """
    return (
        f"SELECT {', '.join(ARCHIVE_COLUMNS)} FROM cms_proof_of_play "
        "WHERE id_org=%s AND played_at >= %s AND played_at < %s "
        "ORDER BY id_player, id_pop"
    )


def day_partition_name(d: date) -> str:
    """Nom de la partition journalière (une par jour) : cms_proof_of_play_AAAA_MM_JJ."""
    return f"{PARTITION_PREFIX}{d.strftime('%Y_%m_%d')}"


def parse_partition_day(name: str) -> date | None:
    """Jour d'une partition journalière, ou None si ce n'est pas une partition JOUR
    (partition DEFAULT, ou vieille partition mensuelle cms_proof_of_play_AAAA_MM)."""
    if not name.startswith(PARTITION_PREFIX):
        return None
    parts = name[len(PARTITION_PREFIX):].split("_")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def retention_cutoff(today: date, retention_days: int) -> date:
    """Jour-pivot : on archive/DROP toute partition JOUR STRICTEMENT antérieure à ce jour
    (donc plus vieille que `retention_days` jours pleins)."""
    return today - timedelta(days=max(0, retention_days))


def build_csv_gz(rows: list[dict]) -> bytes:
    """CSV.gz des lignes brutes d'une période (colonnes CSV_HEADER). `rows` = dicts portant
    les clés `ARCHIVE_COLUMNS`.

    Les drapeaux sont lus par indexation STRICTE, jamais par `.get()`. C'est le point du
    correctif : un `.get()` sur une clé que le `SELECT` avait cessé de lire rendait « false »
    en silence, donc archivait une preuve écran coupé ou recouverte comme de l'antenne réelle.
    Mieux vaut interrompre l'archivage sur un `KeyError` que produire une archive qui ment —
    la partition est DROPée juste après, et l'archive devient la seule trace.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    for r in rows:
        w.writerow([
            r["id_pop"], r["id_player"],
            r["id_media"] if r["id_media"] is not None else "",
            r["id_playlist"] if r["id_playlist"] is not None else "",
            r["played_at"].astimezone(timezone.utc).isoformat(),
            r["duration_ms"], r["merkle_hash"], r["signature"] or "",
            *("true" if r[flag] else "false" for flag in NON_COUNTING_FLAGS),
        ])
    return gzip.compress(buf.getvalue().encode("utf-8"))


def merkle_root_from_csv_gz(data: bytes) -> tuple[str | None, int]:
    """Recalcule (merkle_root, row_count) depuis un CSV.gz produit par build_csv_gz.
    Sert à la vérification hors ligne d'une archive."""
    text = gzip.decompress(data).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    hashes = [row["merkle_hash"] for row in reader]
    return pop_proof.merkle_root(hashes), len(hashes)


def aggregate(
    rows: list[dict], keys: dict[int, str | None], names: dict[int, str],
) -> tuple[list[dict], str | None]:
    """Agrégat d'une période au format `pop_report.build_pop_report_pdf` :
    (players_report, merkle_root_global).

    `rows` DOIT être trié par (id_player, id_pop) pour recomposer la chaîne. `keys` =
    {id_player: clé publique PEM}. Mirroir de l'agrégat de l'endpoint /pop/report.pdf,
    mais sur des dicts (worker psycopg2)."""
    per: dict[int, dict] = {}
    prev_by_player: dict[int, str] = {}
    for r in rows:
        pid = r["id_player"]
        p = per.setdefault(pid, {
            "id_player": pid, "player_name": names.get(pid) or f"Player #{pid}",
            "plays": 0, "duration_sec": 0, "signed": 0, "unsigned": 0,
            "signature_invalid": 0, "chain_valid": True, "chain_head": None, "_hashes": [],
        })
        p["plays"] += 1
        p["duration_sec"] += round((r["duration_ms"] or 0) / 1000)
        p["chain_head"] = r["merkle_hash"]
        p["_hashes"].append(r["merkle_hash"])
        prev = prev_by_player.get(pid, f"genesis:{pid}")
        played_iso = r["played_at"].astimezone(timezone.utc).isoformat()
        recomputed = pop_proof.chain_hash(prev, pid, r["id_media"], played_iso, r["duration_ms"])
        if p["chain_valid"] and recomputed != r["merkle_hash"]:
            p["chain_valid"] = False
        prev_by_player[pid] = r["merkle_hash"]
        if r["signature"]:
            key = keys.get(pid)
            msg = pop_proof.canonical_message(
                pid, r["id_media"], r["id_playlist"],
                pop_proof.played_at_ms(r["played_at"]), r["duration_ms"],
            )
            if key and pop_proof.verify_signature(key, r["signature"], msg):
                p["signed"] += 1
            else:
                p["signature_invalid"] += 1
        else:
            p["unsigned"] += 1

    players_report = [
        {**{k: v for k, v in p.items() if k != "_hashes"},
         "merkle_root": pop_proof.merkle_root(p["_hashes"])}
        for p in per.values()
    ]
    global_root = pop_proof.merkle_root([r["merkle_hash"] for r in rows])
    return players_report, global_root
