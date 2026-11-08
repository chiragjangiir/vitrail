"""Amorçage du catalogue de MAJ players chez un CLIENT (§XXX #4) — déverse un dossier de bundles.

POURQUOI CE SCRIPT EXISTE
-------------------------
Sur une installation neuve, `cms_player_update_versions` est **vide** et le MinIO du client n'a
aucun bundle : le client ne peut mettre à jour AUCUN de ses players, correctif de sécurité compris
(constat du 2026-07-20, re-mesuré le 2026-07-27 sur le banc Lenovo pourtant à jour en 1.0.14).
La prod, elle, a son catalogue rempli **à la main** au fil des mois.

Les bundles voyagent désormais dans une image OCI `signflow-player-bundles:<version serveur>` du
registre (mêmes identifiants que les images du serveur, lecture seule, aucune infrastructure
nouvelle). `install-ubuntu.sh` et `update.sh` la tirent, en extraient le dossier et appellent ce
script — qui écrit par le MÊME service que l'import manuel de l'opérateur
(`services.bundle_import.import_bundle`), donc la même clé de stockage et le même `download_url`
RELATIF (le player tire depuis SON serveur).

IDEMPOTENT : rejouable à chaque mise à jour. Un bundle déjà présent (artefact + ligne) n'est ni
re-téléversé ni redupliqué ; il est compté « déjà là ».

BEST-EFFORT PAR BUNDLE : un fichier illisible ou refusé n'interrompt pas les autres — on le
signale et on continue. Le code de sortie n'est non nul que si AUCUN bundle n'a pu être traité
alors que le dossier en contenait, pour qu'une mise à jour serveur ne casse jamais sur ce motif.

Usage (dans le conteneur backend) :
    python scripts/seed_player_bundles.py /tmp/player-bundles [--dry-run]

Le dossier attendu contient les artefacts à plat, nommés selon la convention
`signflow-player-<os>-<ver>.<tar.gz|apk>` (la plateforme et la version se déduisent du nom ; pour
les tar.gz la version est confirmée par le `package.json` interne).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Exécutable depuis n'importe quel cwd du conteneur (même besoin que publish_player_bundle.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")

from app.db.session import WorkerSessionLocal  # noqa: E402
from app.services import bundle_import  # noqa: E402

# .zip = renderers BS/ChromeOS (décision 3 « canal unique ») : import_bundle les extrait dans
# MinIO (player-renderers/) en plus d'archiver le zip — même définition unique que l'opérateur.
_SUFFIXES = (".tar.gz", ".apk", ".zip")


async def seed(directory: Path, dry_run: bool) -> int:
    files = sorted(
        p for p in directory.iterdir() if p.is_file() and p.name.endswith(_SUFFIXES)
    )
    if not files:
        print(f"Aucun bundle dans {directory} (rien à amorcer).")
        return 0

    created = already = failed = 0
    # Session worker (BYPASSRLS) : `cms_player_update_versions` est une table GLOBALE (aucun
    # id_org — un bundle vaut pour toutes les organisations du serveur) et le script tourne
    # hors requête HTTP, donc sans utilisateur ni org courante.
    async with WorkerSessionLocal() as db:
        for path in files:
            try:
                data = path.read_bytes()
                res = await bundle_import.import_bundle(
                    db, data=data, filename=path.name, dry_run=dry_run
                )
            except bundle_import.BundleImportError as exc:
                failed += 1
                print(f"  IGNORE {path.name} : {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 — stockage indispo, fichier tronqué…
                failed += 1
                print(f"  ECHEC  {path.name} : {exc}")
                continue
            if res.already_registered and res.artifact_present:
                already += 1
                print(f"  deja   {res.platform} {res.version}")
            else:
                created += 1
                verb = "simule" if dry_run else "ajoute"
                print(f"  {verb} {res.platform} {res.version} ({res.size_bytes} octets)")

    print(f"Bundles : {created} ajoute(s), {already} deja present(s), {failed} en echec.")
    # Echec franc UNIQUEMENT si rien n'est passé alors qu'il y avait de la matière : sinon une
    # MAJ serveur s'interromprait pour un bundle exotique, ce qui serait pire que le trou comblé.
    return 1 if (created == 0 and already == 0 and failed > 0) else 0


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv[1:]
    if not args:
        print("usage: seed_player_bundles.py <dossier> [--dry-run]", file=sys.stderr)
        sys.exit(2)
    directory = Path(args[0])
    if not directory.is_dir():
        print(f"dossier introuvable : {directory}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(seed(directory, dry_run)))


if __name__ == "__main__":
    main()
