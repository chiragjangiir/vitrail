"""Triage IA des retours utilisateurs (best-effort) via LiteLLM.

Calqué sur `feed_ai` : appel OpenAI-compatible `/v1/chat/completions`. Renvoie une catégorie,
une sévérité (1-3) et un résumé court. Best-effort : toute erreur (LiteLLM indisponible, JSON
illisible) → None, et les colonnes `ai_*` restent NULL (le tri manuel reste possible).
"""

from __future__ import annotations

import json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_CATEGORIES = ["bug", "ux", "feature", "performance", "content", "other"]

_SYSTEM_PROMPT = (
    "Tu tries des retours d'utilisateurs d'un logiciel d'affichage dynamique (digital "
    "signage). Pour le retour fourni, réponds UNIQUEMENT par un objet JSON, sans texte "
    "autour, avec exactement ces clés :\n"
    '  "category" : une de ["bug","ux","feature","performance","content","other"]\n'
    '  "severity" : entier 1 (mineur) à 3 (critique)\n'
    '  "summary"  : résumé en une phrase courte, neutre, en français\n'
    'Exemple : {"category":"bug","severity":3,"summary":"La playlist ne se sauvegarde pas."}'
)


def _parse(content: str) -> dict | None:
    """Extrait l'objet JSON de la réponse (tolère d'éventuels ```fences```)."""
    txt = content.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
    start, end = txt.find("{"), txt.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(txt[start : end + 1])
    except json.JSONDecodeError:
        return None


def triage(
    feedback_type: str, description: str, *, api_key: str | None = None, timeout: float = 20.0
) -> dict | None:
    """Catégorie + sévérité + résumé pour un retour. None si indisponible.

    Si `api_key` (clé Anthropic propre à l'org, BYOK §XXVII) → appel DIRECT via le SDK
    litellm (le client paie). Sinon → proxy LiteLLM avec la clé plateforme (inchangé)."""
    model = settings.CMS_FEED_SUMMARY_MODEL
    user = f"Type déclaré : {feedback_type}\nRetour :\n{description}"
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    try:
        if api_key:
            import litellm

            from app.services.ai_credentials import sdk_model_name

            resp = litellm.completion(
                model=sdk_model_name(model), messages=messages, max_tokens=160,
                temperature=0.1, api_key=api_key, timeout=timeout, drop_params=True,
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
                    json={"model": model, "messages": messages, "max_tokens": 160, "temperature": 0.1},
                )
                resp.raise_for_status()
                data = resp.json()
        parsed = _parse(data["choices"][0]["message"]["content"] or "")
        if not parsed:
            return None
        category = str(parsed.get("category", "")).lower()
        if category not in _CATEGORIES:
            category = "other"
        sev_raw = parsed.get("severity")
        try:
            severity = int(sev_raw)
        except (TypeError, ValueError):
            severity = None
        if severity not in (1, 2, 3):
            severity = None
        summary = (str(parsed.get("summary", "")).strip() or None)
        return {"category": category, "severity": severity, "summary": summary}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.info("feedback triage indisponible: %s", exc)
        return None
