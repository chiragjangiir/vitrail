"""Publie un renderer SERVI (ChromeOS / BrightSign) au catalogue — côté conteneur backend.

Pendant de `publish_player_bundle.py` pour les deux plateformes qui ne déballent pas une archive
mais consomment des fichiers individuels par HTTP. Prend un zip DÉJÀ construit (le zip se fait côté
hôte : le conteneur backend ne monte que `backend/`), et le passe à `bundle_import.import_bundle`,
qui est la **définition unique** de « enregistrer un bundle chez le client » : artefact dans MinIO,
fichiers extraits sous `player-renderers/<plat>/<ver>/`, ligne catalogue à `download_url` RELATIF.

⛔ NE PAS refaire ce travail à la main ni le réécrire ici. C'est précisément l'absence d'outil qui a
produit le défaut du 2026-08-09 : l'étape était rejouée de mémoire à chaque publication (trois
conventions de nom en trois séances, visibles dans le catalogue), et elle a fini par être oubliée
deux fois dans la même journée — les renderers 2.0.14/2.0.15 et 2.0.33/2.0.34 sont arrivés au
catalogue SANS artefact, donc épinglables en apparence et servant des 404.

Usage (appelé par `deploy/registry/publish-renderer.sh`, qui construit le zip) :
  python scripts/publish_renderer.py <zip_path> <platform> <version>
"""

import asyncio
import os
import sys

# Exécutable depuis n'importe quel cwd du conteneur (cf. publish_player_bundle.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import WorkerSessionLocal  # noqa: E402
from app.services import bundle_import  # noqa: E402


async def run(zip_path: str, platform: str, version: str) -> None:
    with open(zip_path, "rb") as f:
        data = f.read()
    async with WorkerSessionLocal() as db:
        res = await bundle_import.import_bundle(
            db,
            data=data,
            filename=f"signflow-player-{platform}-{version}.zip",
            platform=platform,
            version=version,
        )
    print(f"platform={res.platform}")
    print(f"version={res.version}")
    print(f"id_version={res.id_version}")
    print(f"size_bytes={res.size_bytes}")
    print(f"sha256={res.sha256}")
    print(f"download_url={res.download_url}")
    print(f"files_extracted={res.files_extracted}")
    print(f"already_registered={res.already_registered}")
    # Reprise de la garde BOS (BrightSign) : affichée pour qu'une valeur héritée reste vérifiable.
    print(f"min_firmware_version={res.min_firmware_version or ''}")


def main() -> None:
    if len(sys.argv) < 4:
        print("usage: publish_renderer.py <zip_path> <platform> <version>", file=sys.stderr)
        sys.exit(2)
    zip_path, platform, version = sys.argv[1], sys.argv[2], sys.argv[3]
    if platform not in bundle_import.RENDERER_PLATFORMS:
        print(f"plateforme invalide : {platform} "
              f"(attendu {'/'.join(sorted(bundle_import.RENDERER_PLATFORMS))})", file=sys.stderr)
        sys.exit(2)
    try:
        asyncio.run(run(zip_path, platform, version))
    except bundle_import.BundleImportError as exc:
        print(f"import refuse : {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
