"""Maintenance du journal d'audit : archiver, purger, anonymiser (P3.5).

Le journal est en AJOUT SEUL — migration 0121, qui retire `UPDATE`/`DELETE`/`TRUNCATE` à
`signflow_app` et `signflow_worker`. Ce script est donc le SEUL chemin par lequel de
l'histoire est retirée ou réécrite ; il se connecte en rôle PROPRIÉTAIRE (`DATABASE_URL`)
et se lance à la main pendant une maintenance. Délibérément pas un bouton et pas une tâche
planifiée : une opération qui raccourcit le registre servant à auditer la plateforme doit
demander que quelqu'un la tape.

    # ce qui se passerait — le défaut : rien n'est écrit
    docker compose exec -T backend python scripts/audit_retention.py archive --months 24

    # archiver dans un fichier, puis purger ce qui a été archivé
    docker compose exec -T backend python scripts/audit_retention.py archive --months 24 \
        --out /tmp/audit-2024.csv --apply
    docker compose exec -T backend python scripts/audit_retention.py purge --months 24 \
        --archive /tmp/audit-2024.csv --apply

    # droit à l'effacement : les lignes restent, la personne n'y apparaît plus
    docker compose exec -T backend python scripts/audit_retention.py anonymise \
        --email parti@annonceur.fr --apply

⚠️ Le fichier est écrit DANS LE CONTENEUR : le sortir ensuite (`docker compose cp`) fait
partie de l'opération, sinon l'archive disparaît avec le conteneur — et la purge qui s'y
adosse aurait supprimé pour de bon.

⚠️ Depuis Git Bash sous Windows, préfixer par `MSYS_NO_PATHCONV=1` : sans quoi
`/tmp/audit.csv` est réécrit en `C:/Program Files/Git/tmp/...` avant même d'atteindre le
conteneur, et l'archive atterrit là où personne ne la cherchera.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

from app.core.config import settings  # noqa: E402
from app.services import audit_retention  # noqa: E402
from app.services.audit_retention import RetentionRefused  # noqa: E402


def connect():
    """Rôle PROPRIÉTAIRE. `DATABASE_URL` est l'URL superuser — le seul rôle autorisé à
    supprimer dans le journal, et la raison pour laquelle ceci est un script et pas une
    route. `signflow_worker` échouerait ici, et c'est exactement ce qu'on veut."""
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    return psycopg2.connect(dsn)


# ── archive ──────────────────────────────────────────────────────────────────

def cmd_archive(conn, args) -> int:
    at = audit_retention.cutoff(args.months)
    plan = audit_retention.survey(conn, at)
    print(plan.describe())
    if not plan.rows:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(f"audit-archive-{args.months}m-{stamp}.csv")
    if not args.apply:
        print(f"[simulation] écrirait {plan.rows} entrée(s) dans {out}")
        print("             relancez avec --apply pour écrire le fichier")
        return 0

    if out.exists() and not args.force:
        raise RetentionRefused(
            f"{out} existe déjà. Choisissez un autre nom ou passez --force : "
            "écraser une archive, c'est perdre l'histoire qu'elle portait."
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="" est exigé par le module csv ; sans lui, Windows transforme le \r\n de
    # l'écrivain en \r\r\n et le fichier s'ouvre avec une ligne vide sur deux.
    with out.open("w", encoding="utf-8", newline="") as handle:
        written = audit_retention.write_csv(handle, audit_retention.read_due(conn, at))

    if written != plan.rows:
        print(f"!! {written} entrée(s) écrite(s) pour {plan.rows} attendue(s)")
    print(f"OK  {written} entrée(s) archivée(s) dans {out}")
    audit_retention.trace(conn, "audit_archived",
                          {"cutoff": at.isoformat(), "rows": written, "file": out.name})
    conn.commit()
    return 0


# ── purge ────────────────────────────────────────────────────────────────────

def _count_archive(path: Path) -> int:
    if not path.exists():
        raise RetentionRefused(f"archive introuvable : {path}")
    return audit_retention.count_archive(path.read_text(encoding="utf-8"))


def cmd_purge(conn, args) -> int:
    at = audit_retention.cutoff(args.months)
    plan = audit_retention.survey(conn, at)
    print(plan.describe())
    if not plan.rows:
        return 0

    archived = _count_archive(Path(args.archive))
    print(f"    archive {args.archive} : {archived} entrée(s)")

    if not args.apply:
        print(f"[simulation] supprimerait {plan.rows} entrée(s)")
        if archived < plan.rows:
            print(f"!! et refuserait : l'archive n'en contient que {archived}")
        print("             relancez avec --apply pour supprimer")
        return 0

    removed = audit_retention.purge(conn, at, archived=archived)
    print(f"OK  {removed} entrée(s) purgée(s)")
    audit_retention.trace(conn, "audit_purged",
                          {"cutoff": at.isoformat(), "rows": removed,
                           "archive": Path(args.archive).name})
    conn.commit()
    return 0


# ── anonymise ────────────────────────────────────────────────────────────────

def cmd_anonymise(conn, args) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id_user, email FROM cms_users WHERE email = %s", (args.email,))
        row = cur.fetchone()
        if row is None:
            raise RetentionRefused(f"aucun compte pour {args.email}")
        id_user, email = row
        cur.execute("SELECT count(*) FROM cms_audit_log WHERE id_user = %s", (id_user,))
        rows = cur.fetchone()[0]

    print(f"{rows} entrée(s) rattachée(s) à {email}")
    if not rows:
        return 0
    if not args.apply:
        print("[simulation] les lignes seraient conservées, la personne n'y apparaîtrait plus")
        print("             relancez avec --apply")
        return 0

    touched = audit_retention.pseudonymise(conn, id_user=id_user)
    print(f"OK  {touched} entrée(s) anonymisée(s) — les actions restent, la personne "
          f"n'est plus identifiable")
    # La trace ne nomme personne : elle dit qu'une demande a été honorée, pas qui l'a faite.
    audit_retention.trace(conn, "audit_pseudonymised", {"rows": touched})
    conn.commit()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Archivage, purge et anonymisation du journal d'audit.",
        epilog="Sans --apply, rien n'est écrit : la simulation est le défaut.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    a = sub.add_parser("archive", help="écrit dans un CSV les entrées au-delà de la rétention")
    a.add_argument("--months", type=int, required=True,
                   help=f"rétention en mois (plancher {audit_retention.MIN_RETENTION_MONTHS})")
    a.add_argument("--out", help="fichier de destination (défaut : nom horodaté)")
    a.add_argument("--force", action="store_true", help="écrase une archive existante")
    a.add_argument("--apply", action="store_true")

    p = sub.add_parser("purge", help="supprime les entrées déjà archivées")
    p.add_argument("--months", type=int, required=True)
    p.add_argument("--archive", required=True,
                   help="archive produite par la commande archive, relue et comptée")
    p.add_argument("--apply", action="store_true")

    n = sub.add_parser("anonymise",
                       help="droit à l'effacement : les lignes restent, la personne s'efface")
    n.add_argument("--email", required=True)
    n.add_argument("--apply", action="store_true")

    args = ap.parse_args()
    conn = connect()
    try:
        handler = {"archive": cmd_archive, "purge": cmd_purge, "anonymise": cmd_anonymise}
        return handler[args.command](conn, args)
    except RetentionRefused as refusal:
        print(f"\nRefusé : {refusal}", file=sys.stderr)
        conn.rollback()
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
