"""Avancement d'un encodage ffmpeg — définition UNIQUE de la clé et du format.

Le worker publie (sync, `redis`), le backend lit (async, `redis.asyncio`). Les deux
passent par ce module : deux écritures de la clé, ou deux formes de payload, finiraient
par diverger sur un des deux chemins (même discipline que `rbac.user_is_server_operator`).

🔑 **Pourquoi Redis et pas une colonne de `cms_media`** : un encodage publie son avancement
environ toutes les secondes, pendant des heures pour une source lourde. En colonne, c'est
une écriture par seconde et par encodage simultané sur la table la plus lue du produit
(médiathèque, résolution du payload player) — pour une donnée qui ne vaut rien passé la
minute. Le TTL donne en prime le bon mode de panne : worker tué, machine redémarrée, la
progression **disparaît d'elle-même** et l'écran retombe sur « en cours » sans barre, au
lieu d'afficher éternellement « 47 % » d'un encodage qui n'existe plus.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# TTL volontairement court : un encodage vivant réécrit sa clé ~1×/s. Toute valeur plus
# vieille que ça décrit un processus mort — on préfère ne rien afficher qu'un chiffre faux.
TTL_S = 120


def key(id_media: int) -> str:
    return f"signflow:media:{int(id_media)}:enc"


def payload(
    *,
    pct: float | None,
    eta_s: int | None,
    speed: float | None,
    phase: str,
    profile: str | None = None,
) -> dict:
    """Forme canonique publiée. `pct` reste None tant qu'on ne connaît pas la durée totale
    (source sans durée sondable) : on montre alors une activité, jamais un pourcentage faux."""
    out: dict = {"phase": phase, "at": int(time.time())}
    if pct is not None:
        out["pct"] = round(max(0.0, min(100.0, float(pct))), 1)
    if eta_s is not None:
        out["eta_s"] = max(0, int(eta_s))
    if speed is not None:
        out["speed"] = round(float(speed), 2)
    if profile:
        out["profile"] = profile
    return out


# ── Écriture (worker, client sync) ────────────────────────────────────────────


def publish(id_media: int, data: dict) -> None:
    """Best-effort : Redis indisponible ne doit JAMAIS faire échouer un encodage.
    On perd l'affichage de la barre, pas le média."""
    try:
        import redis  # import local : le backend n'a pas besoin du client sync

        from app.core.config import settings

        r = redis.from_url(settings.REDIS_URL)
        try:
            r.set(key(id_media), json.dumps(data), ex=TTL_S)
        finally:
            r.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("encode_progress.publish(%s) failed: %s", id_media, exc)


def clear(id_media: int) -> None:
    """Fin d'encodage : on efface au lieu d'attendre le TTL, sinon la barre reste
    affichée jusqu'à 2 min après un média déjà marqué `done`."""
    try:
        import redis

        from app.core.config import settings

        r = redis.from_url(settings.REDIS_URL)
        try:
            r.delete(key(id_media))
        finally:
            r.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("encode_progress.clear(%s) failed: %s", id_media, exc)


# ── Lecture (backend, client async) ───────────────────────────────────────────


async def read_many(ids: list[int]) -> dict[int, dict]:
    """Progression des médias demandés. Liste vide → **aucun appel Redis** : c'est le cas
    courant (rien en cours d'encodage), et la médiathèque est une page très fréquentée."""
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw = await r.mget([key(i) for i in ids])
    except Exception as exc:  # noqa: BLE001
        logger.debug("encode_progress.read_many failed: %s", exc)
        return {}
    out: dict[int, dict] = {}
    for id_media, value in zip(ids, raw):
        if not value:
            continue
        try:
            out[id_media] = json.loads(value)
        except (TypeError, ValueError):
            continue
    return out
