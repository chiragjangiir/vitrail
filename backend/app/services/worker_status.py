"""Capacités du worker média publiées vers le backend — définition UNIQUE de la clé.

Le backend n'a **ni ffmpeg ni ffprobe** (allègement des images du 2026-07-19) et ne voit
pas le GPU : il ne peut donc RIEN dire de lui-même sur la capacité d'encodage du serveur.
Seul le worker le sait. Il publie donc périodiquement ce qu'il constate, et le backend le
relaie à la page « Serveur ».

Redis + TTL, comme la progression d'encodage, pour la même raison : c'est un état vivant,
pas une donnée à conserver. Le TTL donne aussi la bonne réponse quand le worker meurt —
la page dit « aucun worker ne répond » au lieu d'afficher éternellement les capacités d'une
machine éteinte. C'est précisément le genre de silence qui a coûté cher sur les bundles
players (« best-effort » qui échoue sans rien arrêter).
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

_PREFIX = "signflow:worker:media:"
# 3× la cadence de publication (60 s) : un worker occupé peut rater une passe sans être
# déclaré mort pour autant.
TTL_S = 180


def key(hostname: str) -> str:
    return f"{_PREFIX}{hostname}"


def publish(hostname: str, data: dict) -> None:
    """Best-effort — un Redis indisponible ne doit jamais faire échouer le worker."""
    try:
        import redis

        from app.core.config import settings

        r = redis.from_url(settings.REDIS_URL)
        try:
            r.set(key(hostname), json.dumps({**data, "at": int(time.time())}), ex=TTL_S)
        finally:
            r.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("worker_status.publish failed: %s", exc)


async def read_all() -> list[dict]:
    """Tous les workers média qui se sont manifestés récemment (liste vide = aucun)."""
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            keys = [k async for k in r.scan_iter(match=f"{_PREFIX}*", count=100)]
            if not keys:
                return []
            raw = await r.mget(keys)
    except Exception as exc:  # noqa: BLE001
        logger.debug("worker_status.read_all failed: %s", exc)
        return []
    out: list[dict] = []
    for value in raw:
        if not value:
            continue
        try:
            out.append(json.loads(value))
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda w: w.get("hostname") or "")
