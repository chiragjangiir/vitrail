"""Versions des renderers SERVIS par le serveur (BrightSign, ChromeOS) — §XXX / #4.

Ces plateformes n'ont pas de bundle à télécharger : leur code est un fichier statique de l'image
frontend (BS `RefreshRenderer` / ChromeOS `location.reload()`). Leur version est donc connue à la
CONSTRUCTION = constante du code (`signflow.js`). Ce manifeste la fige côté backend (image séparée du
frontend, qui ne peut pas lire `signflow.js` au runtime) ; un test (`test_served_player_versions.py`)
garantit qu'il ne DÉRIVE pas des constantes du code (même culture que `gen_role_matrix` /
`test_demo_guard`).

Il sert deux usages :
  1. **Déclaration** au catalogue (`POST /updates/served-versions/register`) : la version déclarée
     vient d'ici, jamais d'une saisie libre → on ne déclare que ce que le serveur sert réellement.
  2. **Résolution du pin** (`resolve_renderer_version`, cf. `ota.py`) : la version servie sert de
     DÉFAUT quand un player n'a jamais été déployé et n'a pas encore de version connue.

Les clés = `player_os` cible (`chromeos` / `brightsign`) → la garde plateforme de `create_deployment`
(`model_family == player_os`) route les déploiements sur les bons players, et le pin ne mélange jamais
deux plateformes.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parent.parent / "data" / "served_player_versions.json"


@lru_cache(maxsize=1)
def served_player_versions() -> dict[str, str]:
    """Map `player_os` → version servie, lue dans le manifeste baké dans l'image backend.

    Best-effort : un manifeste absent/illisible → dict vide (aucune plateforme servie exposée), jamais
    une exception au boot. Mis en cache (le fichier ne change pas au runtime)."""
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
