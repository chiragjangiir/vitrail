"""Re-ancrage ponctuel de la chaîne Proof of Play (maintenance banc).

Recalcule `merkle_hash` de chaque player dans l'ordre `id_pop` (= l'ordre que la vérification
utilise), pour réparer l'historique écrit avant le fix de semis (prev_hash semé par `played_at`
au lieu de `id_pop` → faux « chaîne altérée » sur les players multi-zones).

- Ne touche QUE `merkle_hash`. Les signatures Ed25519 signent le message canonique (player, média,
  playlist, played_at_ms, durée), PAS le hash de chaîne → re-ancrer n'invalide AUCUNE signature.
- N'UPDATE que les lignes dont le hash change (no-op sur les chaînes déjà valides).
- Idempotent : relancer ne change plus rien une fois la chaîne cohérente.

Usage (dans le conteneur backend) :
    python scripts/reanchor_pop_chain.py --player signflow-001      # un player par nom
    python scripts/reanchor_pop_chain.py --all                      # tous les players
    python scripts/reanchor_pop_chain.py --player signflow-001 --apply   # écrit (sinon dry-run)
"""
from __future__ import annotations

import argparse
import hashlib
import os
from datetime import timezone

import psycopg2


def _next_hash(prev: str, id_player: int, id_media, played_at: str, duration_ms: int) -> str:
    data = f"{prev}:{id_player}:{id_media or ''}:{played_at}:{duration_ms}"
    return hashlib.sha256(data.encode()).hexdigest()


def _sync_dsn() -> str:
    dsn = os.environ["DATABASE_URL"]
    return dsn.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", help="player_name à re-ancrer")
    ap.add_argument("--all", action="store_true", help="re-ancrer tous les players")
    ap.add_argument("--apply", action="store_true", help="écrire (sinon dry-run)")
    args = ap.parse_args()
    if not args.player and not args.all:
        ap.error("préciser --player <nom> ou --all")

    conn = psycopg2.connect(_sync_dsn())
    conn.autocommit = False
    cur = conn.cursor()

    if args.all:
        cur.execute("SELECT id_player, player_name FROM cms_players ORDER BY id_player")
    else:
        cur.execute("SELECT id_player, player_name FROM cms_players WHERE player_name = %s", (args.player,))
    players = cur.fetchall()
    if not players:
        print("Aucun player trouvé.")
        return

    total_changed = 0
    for id_player, name in players:
        cur.execute(
            "SELECT id_pop, id_media, played_at, duration_ms, merkle_hash "
            "FROM cms_proof_of_play WHERE id_player = %s ORDER BY id_pop",
            (id_player,),
        )
        rows = cur.fetchall()
        prev = f"genesis:{id_player}"
        changed = 0
        for id_pop, id_media, played_at, duration_ms, stored in rows:
            played_at_str = played_at.astimezone(timezone.utc).isoformat()
            h = _next_hash(prev, id_player, id_media, played_at_str, duration_ms)
            if h != stored:
                changed += 1
                if args.apply:
                    cur.execute(
                        "UPDATE cms_proof_of_play SET merkle_hash = %s WHERE id_pop = %s",
                        (h, id_pop),
                    )
            prev = h
        total_changed += changed
        print(f"  {name} (id={id_player}) : {len(rows)} preuves, {changed} hash à corriger")

    if args.apply:
        conn.commit()
        print(f"APPLIQUÉ : {total_changed} lignes mises à jour.")
    else:
        conn.rollback()
        print(f"DRY-RUN : {total_changed} lignes seraient mises à jour (relancer avec --apply).")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
