"""Chemin lisible d'un dossier de médias — une seule définition.

« Video / Divers » plutôt que « Divers » : deux dossiers homonymes sous des parents
différents sont sinon indiscernables. C'est ce qui a corrigé le tiroir de classement le
2026-07-28, et c'est la même chose qu'attend la recherche globale (P2.5) pour distinguer
six médias nommés « Fond promo IA ». Extrait de `endpoints/media_folders.py` le
2026-08-05 pour que les deux surfaces ne puissent pas diverger.
"""

from __future__ import annotations

from app.models.media_folder import CmsMediaFolder

_MAX_DEPTH = 32  # garde-fou anti-cycle : une donnée incohérente ne doit pas boucler


def folder_full_paths(folders: list[CmsMediaFolder]) -> dict[int, str]:
    """`id_folder` → « Racine / Enfant / Petit-enfant ».

    Un dossier dont le parent est absent de `folders` (ou une chaîne trop profonde) rend
    son seul nom : mieux vaut un chemin partiel qu'une exception sur un chemin d'affichage.
    """
    by_id = {f.id_folder: f for f in folders}
    cache: dict[int, str] = {}

    def resolve(f: CmsMediaFolder, guard: int = 0) -> str:
        if f.id_folder in cache:
            return cache[f.id_folder]
        parent = by_id.get(f.parent_id) if f.parent_id is not None else None
        if parent is None or guard > _MAX_DEPTH:
            value = f.folder_name
        else:
            value = f"{resolve(parent, guard + 1)} / {f.folder_name}"
        cache[f.id_folder] = value
        return value

    return {f.id_folder: resolve(f) for f in folders}
