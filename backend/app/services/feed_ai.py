"""Résumé IA des items de feed (§XXV.3) via LiteLLM.

LiteLLM expose une API OpenAI-compatible (`/v1/chat/completions`) qui route vers Claude (modèles
déclarés dans `docker/litellm/config.yaml`). On l'utilise pour condenser un item RSS — titre +
description, souvent du HTML brut/tronqué — en UNE phrase lisible à l'écran, dans la langue de la
source.

Best-effort et synchrone (appelé depuis le worker Celery, lui-même synchrone) : toute erreur
(proxy injoignable, pas de clé API, timeout, réponse inattendue) → `None`. Le player retombe alors
sur la `description` d'origine — dégradation gracieuse, jamais d'écran vide.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_MAX_INPUT_CHARS = 4000   # borne l'entrée (coût + latence) — un item RSS dépasse rarement
_MIN_INPUT_CHARS = 12     # en deçà, rien à résumer

_SYSTEM_PROMPT = (
    "Tu es un assistant d'affichage dynamique (digital signage). On te donne un article de flux "
    "d'actualité (titre + contenu). Résume-le en UNE phrase claire et neutre, dans la MÊME langue "
    "que l'article, lisible d'un écran à distance. Pas de guillemets, pas de préfixe "
    "(« Résumé : »), pas d'emoji. Maximum 30 mots."
)


def _strip_html(s: str | None) -> str:
    return _TAG_RE.sub(" ", str(s or "")).replace("\xa0", " ")


def summarize(
    title: str | None,
    body: str | None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 20.0,
) -> str | None:
    """Retourne un résumé d'une phrase de l'item, ou None si indisponible/inutile.

    Si `api_key` (clé Anthropic propre à l'org, BYOK §XXVII) → appel DIRECT via le SDK
    litellm (le client paie). Sinon → proxy LiteLLM avec la clé plateforme (inchangé)."""
    text = _WS_RE.sub(" ", f"{_strip_html(title)}. {_strip_html(body)}").strip()
    text = text[:_MAX_INPUT_CHARS]
    if len(text) < _MIN_INPUT_CHARS:
        return None

    mdl = model or settings.CMS_FEED_SUMMARY_MODEL
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        if api_key:
            import litellm

            from app.services.ai_credentials import sdk_model_name

            resp = litellm.completion(
                model=sdk_model_name(mdl), messages=messages, max_tokens=120,
                temperature=0.3, api_key=api_key, timeout=timeout, drop_params=True,
            )
            data = resp.model_dump()
        else:
            headers = {}
            if settings.CMS_LITELLM_API_KEY:
                headers["Authorization"] = f"Bearer {settings.CMS_LITELLM_API_KEY}"
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{settings.CMS_LITELLM_URL.rstrip('/')}/v1/chat/completions",
                    headers=headers,
                    json={"model": mdl, "messages": messages, "max_tokens": 120, "temperature": 0.3},
                )
                resp.raise_for_status()
                data = resp.json()
        out = (data["choices"][0]["message"]["content"] or "").strip()
        # garde-fou : un modèle bavard peut ajouter des guillemets — on les retire en bordure
        out = out.strip().strip('"').strip("«»").strip()
        return out or None
    except Exception as exc:  # noqa: BLE001
        logger.info("feed_ai.summarize échec (%s): %s", mdl, exc)
        return None
