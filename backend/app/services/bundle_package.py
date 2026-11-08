"""Ce que le colis de bundles players DOIT contenir — et ce qu'il manque quand il ne le contient pas.

Le colis (`signflow-player-bundles:<version serveur>`, image OCI) est ce qui permet à un client
d'installer et de mettre à jour ses players : sans lui, `cms_player_update_versions` est vide chez
lui et il ne peut mettre à jour AUCUN écran, correctif de sécurité compris.

🔴 POURQUOI CE MODULE EXISTE (défaut trouvé le 2026-08-09 par une question d'Ed sur un VPS client :
« j'ai les updates pour windows, linux, android et rpi mais pas chromeos et BS, normal ? »).
La sélection vivait dans un heredoc Python à l'intérieur du script shell de publication, et son
traitement d'une plateforme non embarquable était un `continue` avec une ligne sur stderr — dans
une étape appelée en **best-effort**, qui réussissait donc quand même. Résultat mesuré : le colis
de la 1.0.32 ne contenait que 4 plateformes sur 6, et **rien n'a distingué « ChromeOS a été sauté »
de « ChromeOS n'est pas une plateforme gérée »**. Le client garde des écrans qui fonctionnent (ils
chargent leur renderer depuis les fichiers statiques de son serveur) mais perd le CONTRÔLE :
plus d'épinglage de version, plus de canary sur un seul écran.

D'où deux fonctions PURES, testables hors de tout script : ce qu'on prévoit d'embarquer, et ce qui
manque à l'arrivée. Le script ne décide plus, il exécute et rapporte.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.services import bundle_import, ota


@dataclass(frozen=True)
class PlannedBundle:
    """Un artefact attendu dans le colis : la dernière version stable d'une plateforme."""

    platform: str
    version: str
    storage_key: str


def plan_package(rows: Iterable) -> list[PlannedBundle]:
    """Le contenu attendu du colis : la DERNIÈRE version stable de chaque plateforme connue.

    `rows` = lignes de `cms_player_update_versions` filtrées sur `track='player'` et
    `channel='stable'` (une beta ne part pas chez un client). On distribue un point de départ sain,
    pas tout l'historique : le client importe ensuite ses propres versions.

    Les plateformes hors de `BUNDLE_ARTIFACT` sont ignorées SANS bruit — elles n'ont pas d'artefact
    par construction (ex. une ligne `track='player'` d'une famille qui n'en distribue pas). C'est le
    seul silence légitime ici, et il est décidé sur une table explicite, pas sur un échec d'I/O.
    """
    best: dict[str, PlannedBundle] = {}
    for row in rows:
        platform = (getattr(row, "model_family", None) or "").lower()
        artifact = bundle_import.BUNDLE_ARTIFACT.get(platform)
        if artifact is None:
            continue
        ext, _mime = artifact
        version = getattr(row, "version", "") or ""
        current = best.get(platform)
        if current is not None and ota.semver_key(current.version) >= ota.semver_key(version):
            continue
        best[platform] = PlannedBundle(
            platform=platform,
            version=version,
            storage_key=f"player-bundles/{platform}/{version}{ext}",
        )
    return [best[p] for p in sorted(best)]


def package_shortfall(
    planned: Iterable[PlannedBundle], embedded_platforms: Iterable[str]
) -> list[PlannedBundle]:
    """Les plateformes prévues qui ne sont PAS dans le colis, pour être NOMMÉES.

    ⛔ Volontairement pas de repli sur une version plus ancienne qui aurait, elle, son artefact :
    le client recevrait un renderer plus vieux que celui que son propre serveur sert, et le colis
    aurait l'air complet. Une plateforme absente d'un colis ne doit pas être indiscernable d'une
    plateforme non gérée — c'est tout le défaut qu'on ferme ici.
    """
    have = {p.lower() for p in embedded_platforms}
    return [b for b in planned if b.platform not in have]
