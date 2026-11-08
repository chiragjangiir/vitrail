"""Publie un bundle OTA de player vers MinIO (§XXX Slice 2b / productisation OTA-depuis-serveur).

Prend une archive tar.gz DÉJÀ construite (le `tar` se fait côté hôte, car le conteneur backend ne
monte que `backend/`), l'uploade dans le bucket média sous `player-bundles/<platform>/<version>.tar.gz`
et affiche `storage_key` + `sha256` + le **download_url RELATIF** à renseigner dans une version du
catalogue OTA (download_url + sha256 + model_family=<platform>).

⚠️ Utiliser le **download_url RELATIF** (`/api/v1/updates/bundles/<platform>/<version>`) : le player
prend sa MAJ sur SON serveur (endpoint authentifié `download_bundle`) et résout ce chemin contre son
propre `backend_url`. Portable d'un client à l'autre, jamais GitHub, sans expiration ni exposition
MinIO. (L'URL pré-signée n'est plus imprimée : elle expirait à 7 j et exigeait MinIO public.)

Le bundle DOIT contenir `package.json` (version cible) + `src/` à sa racine, pour que
`tar -xzf bundle -C <appRoot>` du player remplace bien ces éléments et fasse monter la version.

Usage (dans le conteneur backend, cwd /app) :
  python scripts/publish_player_bundle.py <tar_path> <version> <platform>

Exemple complet côté hôte /opt/signflow :
  tar -czf backend/_ota_bundle.tgz -C player-linux package.json src
  docker compose exec -T backend python scripts/publish_player_bundle.py _ota_bundle.tgz 1.5.2 linux
  rm -f backend/_ota_bundle.tgz
"""

import os
import sys

# Exécutable depuis n'importe quel cwd du conteneur : `python scripts/publish_player_bundle.py`
# met /app/scripts (pas /app) sur sys.path → l'import `app.*` échouait sans PYTHONPATH=/app.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.services import bundle_import, media  # noqa: E402


def main() -> None:
    if len(sys.argv) < 4:
        print("usage: publish_player_bundle.py <tar_path> <version> <platform>")
        sys.exit(2)
    tar_path, version, platform = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(tar_path, "rb") as f:
        data = f.read()
    sha = media.compute_sha256(data)
    # 🔴 Extension et type SELON LA PLATEFORME, jamais `.tar.gz` en dur (corrigé le 2026-07-30).
    # Android livre un `.apk` et ChromeOS/BrightSign un `.zip` : ce script écrivait
    # `player-bundles/android/<ver>.tar.gz` alors que l'endpoint `download_bundle` RELIT la clé
    # via `BUNDLE_ARTIFACT` (donc `<ver>.apk`) → le player aurait reçu un 404 à la mise à jour,
    # sans que rien n'échoue à la publication. La table est importée de `bundle_import` : une
    # copie locale finirait par diverger (c'est exactement ce qui s'est produit ici).
    ext, mime = bundle_import.BUNDLE_ARTIFACT[platform]
    key = f"player-bundles/{platform}/{version}{ext}"
    media._s3().put_object(
        Bucket=settings.MINIO_BUCKET_MEDIA, Key=key, Body=data, ContentType=mime
    )
    # download_url RELATIF : servi par l'endpoint authentifié `download_bundle`, résolu côté player
    # contre son backend_url. Portable, sans expiration, sans exposer MinIO.
    download_url = f"/api/v1/updates/bundles/{platform}/{version}"
    print(f"size_bytes={len(data)}")
    print(f"storage_key={key}")
    print(f"sha256={sha}")
    print(f"download_url={download_url}")
    print(f"model_family={platform}")


if __name__ == "__main__":
    main()
