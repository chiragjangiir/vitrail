"""Campagne de génération one-shot (§ génération — Phase 4).

Claude = directeur créatif : il transforme un brief en langage naturel en une SPEC
structurée = une liste de « concepts » visuels, chacun avec un prompt d'image soigné
(prêt pour fal). Le fan-out génère ensuite chaque concept dans chaque ratio choisi.

Claude NE génère PAS les pixels — il ne fait que le plan (prompts). La génération passe
par les jobs `cms_generation_jobs` + le worker (réutilise tout l'existant Phase 1/3).

Appel LLM via LiteLLM (OpenAI-compatible), même politique BYOK que l'assistant : clé org
(byok) → SDK litellm direct ; sinon → proxy plateforme. Best-effort : toute erreur → la
liste de repli (un concept = le brief tel quel) pour ne jamais bloquer.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_CONCEPTS = 6
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = (
    "Tu es directeur artistique pour de l'affichage dynamique (digital signage). On te donne "
    "un brief de campagne et les TYPES de contenu à produire. Réponds UNIQUEMENT en JSON valide "
    "(sans markdown) de la forme : "
    '{"concepts":[{"title":"...","prompt":"..."}], "video_prompt":"...", '
    '"voiceover":"...", "music_prompt":"..."}.\n'
    "- `concepts` (toujours) : des concepts visuels distincts et percutants ; chaque `prompt` "
    "décrit une image en ANGLAIS (sujet, ambiance, lumière, style, composition), SANS texte "
    "incrusté ni logo ; `title` = étiquette courte dans la langue du brief.\n"
    "- `video_prompt` (si vidéo demandée) : description en ANGLAIS d'un court plan animé.\n"
    "- `voiceover` (si voix demandée) : un script de voix-off COURT (2-3 phrases) dans la "
    "LANGUE du brief, prêt à être lu.\n"
    "- `music_prompt` (si musique demandée) : style/ambiance musical en ANGLAIS.\n"
    "N'inclus que les champs demandés par les types."
)


def fallback_concepts(brief: str, n: int) -> list[dict]:
    """Repli (LLM indisponible ou org en mode strict) : un concept = le brief tel quel."""
    return [{"title": f"Concept {i + 1}", "prompt": brief.strip()} for i in range(max(1, n))]


_fallback = fallback_concepts


def fallback_plan(brief: str, n: int, types: list[str]) -> dict:
    """Repli multi-type : concepts = brief ; prompts vidéo/voix/musique = brief si type demandé."""
    b = brief.strip()
    return {
        "concepts": fallback_concepts(brief, n),
        "video_prompt": b if "video" in types else None,
        "voiceover": b if "voice" in types else None,
        "music_prompt": b if "music" in types else None,
    }


def _parse_concepts(content: str, brief: str, n: int) -> list[dict]:
    m = _JSON_RE.search(content or "")
    if not m:
        return _fallback(brief, n)
    try:
        data = json.loads(m.group(0))
        raw = data.get("concepts") or []
        out = []
        for c in raw[:MAX_CONCEPTS]:
            prompt = str(c.get("prompt") or "").strip()
            if prompt:
                title = str(c.get("title") or "Concept").strip()[:80]
                out.append({"title": title, "prompt": prompt})
        return out or _fallback(brief, n)
    except (ValueError, TypeError):
        return _fallback(brief, n)


def _parse_plan(content: str, brief: str, n: int, types: list[str]) -> dict:
    m = _JSON_RE.search(content or "")
    if not m:
        return fallback_plan(brief, n, types)
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback_plan(brief, n, types)
    concepts = _parse_concepts(content, brief, n)

    def _opt(field: str, requested: str) -> str | None:
        if requested not in types:
            return None
        v = str(data.get(field) or "").strip()
        return v or brief.strip()

    return {
        "concepts": concepts,
        "video_prompt": _opt("video_prompt", "video"),
        "voiceover": _opt("voiceover", "voice"),
        "music_prompt": _opt("music_prompt", "music"),
    }


async def plan_campaign(
    *,
    brief: str,
    n_concepts: int,
    types: list[str] | None = None,
    model: str | None = None,
    byok_key: str | None = None,
    timeout: float = 40.0,
) -> dict:
    """Retourne le plan {concepts, video_prompt?, voiceover?, music_prompt?}. Best-effort."""
    n = max(1, min(int(n_concepts or 1), MAX_CONCEPTS))
    types = types or ["image"]
    mdl = model or settings.CMS_ASSISTANT_MODEL
    user = (
        f"Brief de campagne :\n{brief.strip()}\n\n"
        f"Types de contenu demandés : {', '.join(types)}.\n"
        f"Propose EXACTEMENT {n} concept(s) visuel(s) distinct(s)."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    try:
        if byok_key:
            import litellm

            from app.services.ai_credentials import sdk_model_name

            resp = litellm.completion(
                model=sdk_model_name(mdl), messages=messages, max_tokens=1200,
                temperature=0.8, api_key=byok_key, timeout=timeout, drop_params=True,
            )
            content = resp.model_dump()["choices"][0]["message"]["content"]
        else:
            headers = {}
            if settings.CMS_LITELLM_API_KEY:
                headers["Authorization"] = f"Bearer {settings.CMS_LITELLM_API_KEY}"
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    f"{settings.CMS_LITELLM_URL.rstrip('/')}/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": mdl, "messages": messages,
                        "max_tokens": 1200, "temperature": 0.8,
                    },
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_campaign LLM indisponible (%s) → repli brut", exc.__class__.__name__)
        return fallback_plan(brief, n, types)
    return _parse_plan(content, brief, n, types)
