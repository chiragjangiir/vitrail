"""Déplace tout le contenu d'une organisation vers une NOUVELLE organisation.

Crée une org de destination (vierge — pas de seed de namespaces, pour éviter les
doublons de tags) puis réassigne `id_org` sur TOUTES les tables tenant (auto-
découvertes via information_schema). Les tables enfant (sans id_org) suivent leur
parent via leurs FK (id_player / id_media / id_playlist…), rien à toucher.

Tout se fait dans UNE transaction (rollback complet en cas d'erreur).

Usage (local) :
  MOVE_SRC_ORG=1 MOVE_DEST_NAME=Test MOVE_DEST_SLUG=test \
    docker compose -p cms_kahall exec -T \
      -e MOVE_SRC_ORG -e MOVE_DEST_NAME -e MOVE_DEST_SLUG \
      backend python3 - < backend/scripts/move_org.py

⚠️ Déplace AUSSI les utilisateurs de l'org source (donc l'admin) → ils se
connecteront désormais dans l'org de destination. L'org source devient une coquille
vide (on peut la laisser ou la supprimer). Faire un backup avant (cf. procédure).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

SRC = int(os.environ.get("MOVE_SRC_ORG", "1"))
DEST_NAME = os.environ.get("MOVE_DEST_NAME", "Test")
DEST_SLUG = os.environ.get("MOVE_DEST_SLUG", "test")


async def main() -> None:
    # Rôle worker (BYPASSRLS) : on écrit dans plusieurs orgs.
    engine = create_async_engine(settings.db_worker_url)
    async with engine.begin() as conn:  # transaction unique
        # 1. Org de destination VIERGE (pas de namespaces seedés → pas de doublon tag)
        row = (await conn.execute(
            text("SELECT id_org FROM cms_organizations WHERE org_slug = :s"), {"s": DEST_SLUG}
        )).first()
        if row:
            dest = row[0]
            print(f"Org destination existante : {DEST_NAME} (id_org={dest})")
        else:
            dest = (await conn.execute(
                text("INSERT INTO cms_organizations (org_name, org_slug) VALUES (:n, :s) RETURNING id_org"),
                {"n": DEST_NAME, "s": DEST_SLUG},
            )).scalar_one()
            print(f"Org destination créée : {DEST_NAME} (id_org={dest})")

        if dest == SRC:
            raise SystemExit("Source et destination identiques — abandon.")

        # 2. Toutes les tables tenant (colonne id_org), sauf cms_organizations elle-même.
        tables = [r[0] for r in (await conn.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE column_name='id_org' AND table_schema='public' "
            "AND table_name LIKE 'cms_%' AND table_name <> 'cms_organizations' "
            "ORDER BY table_name"
        )))]

        print(f"\nRéassignation id_org {SRC} -> {dest} sur {len(tables)} tables :")
        total = 0
        for t in tables:
            res = await conn.execute(
                text(f"UPDATE {t} SET id_org = :d WHERE id_org = :s"), {"d": dest, "s": SRC}
            )
            if res.rowcount:
                print(f"  {t:<34} {res.rowcount}")
                total += res.rowcount

        print(f"\nTotal lignes déplacées : {total}")
        print(f"Org source {SRC} est maintenant vide (coquille — à laisser ou supprimer).")
        # commit implicite à la sortie du `async with engine.begin()`

    await engine.dispose()
    print("OK (transaction validée).")


asyncio.run(main())
