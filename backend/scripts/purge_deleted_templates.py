"""Purge les templates restés en suppression LOGIQUE avant le passage à la suppression réelle.

Décision d'Ed (2026-07-28) : « quand on efface, on efface ». Le code ne crée plus de
lignes fantômes — mais celles d'avant sont toujours là : ni visibles, ni listées, ni
restaurables. Ce script solde l'héritage.

    docker compose exec -T backend python scripts/purge_deleted_templates.py          # inventaire
    docker compose exec -T backend python scripts/purge_deleted_templates.py --apply  # purge

⚠️ SANS `--apply` il n'écrit RIEN : on regarde d'abord ce qui va disparaître. Un template
encore référencé par une playlist vivante est ÉPARGNÉ et signalé — le détacher est une
décision, pas un effet de bord de nettoyage.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

from sqlalchemy import select

from app.db.session import WorkerSessionLocal
from app.models.playlist import CmsPlaylist
from app.models.template import CmsTemplate

APPLY = "--apply" in sys.argv


async def main() -> None:
    async with WorkerSessionLocal() as db:
        rows = list((await db.execute(
            select(CmsTemplate).where(CmsTemplate.is_deleted.is_(True))
            .order_by(CmsTemplate.id_org, CmsTemplate.id_template)
        )).scalars().all())
        if not rows:
            print("Aucun template en suppression logique — rien à faire.")
            return

        print(f"{len(rows)} template(s) en suppression logique :\n")
        purgeable, kept = [], []
        for t in rows:
            used = list((await db.execute(
                select(CmsPlaylist.playlist_name).where(
                    CmsPlaylist.id_template == t.id_template,
                    CmsPlaylist.is_deleted.is_(False),
                )
            )).scalars().all())
            zones = len((t.layout or {}).get("zones") or [])
            flag = f"  ⚠️ RÉFÉRENCÉ par : {', '.join(used)}" if used else ""
            print(f"  org {t.id_org} · #{t.id_template} « {t.template_name} » "
                  f"({zones} zone(s), créé le {t.created_at:%Y-%m-%d}){flag}")
            (kept if used else purgeable).append(t)

        print(f"\n  purgeables : {len(purgeable)}   épargnés (référencés) : {len(kept)}")
        if not APPLY:
            print("\nSimulation — relancer avec --apply pour purger.")
            return
        for t in purgeable:
            await db.delete(t)
        await db.commit()
        print(f"\n{len(purgeable)} template(s) purgé(s) définitivement.")


asyncio.run(main())
