"""Assistant de rédaction de prompt (§ génération — assistant de prompt + negative prompt).

Claude aide l'utilisateur à transformer une idée (FR/EN/…, parfois une méta-instruction
maladroite) en un **prompt optimisé en anglais** adapté au MODÈLE visé, plus un **negative
prompt** quand le modèle le supporte. C'est un coup de pouce OPTIONNEL : le champ prompt reste
libre, le résultat est toujours éditable.

Le service est *model-aware* (via `catalog.get_model`) — un i2v veut du mouvement/caméra, un
t2i veut une scène, un i2i une transformation, l'audio des consignes sonores. Bonnes pratiques
intégrées (Kling/Veo/Wan) : formule sujet+action+caméra+lumière, 3-5 éléments max, mots
simples, une seule intention caméra, et pour le negative prompt les défauts utiles
(text/banner/warped faces/jittery camera…) qui évitent le piège « bandeau de texte incrusté ».

Deux modes : `one_shot` (idée → prompt direct) et `conversational` (l'agent peut poser 1-3
questions avant de livrer). Sortie JSON structurée (comme `plan_campaign`).

Appel LLM via LiteLLM (OpenAI-compatible), MÊME politique BYOK que l'assistant/campagne : clé
org (byok) → SDK litellm direct ; sinon → proxy plateforme. Best-effort : toute erreur → repli
gracieux (le prompt brut de l'utilisateur, non assisté). En mode strict (pas de clé), le caller
n'appelle même pas ce service et renvoie le repli.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.core.config import settings
from app.services import brand_kit
from app.services.generation import catalog

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_MAX_QUESTIONS = 3

# Consignes par CATÉGORIE de modèle (déduite du kind + présence d'une référence).
_GUIDANCE: dict[str, str] = {
    "t2i": (
        "IMAGE (texte→image). Décris une SCÈNE fixe : sujet précis, décor, composition/cadrage, "
        "lumière, palette, style visuel. Pas de texte/lettres incrustés ni de logo."
    ),
    "i2i": (
        "IMAGE→IMAGE (une image de référence est fournie). Décris la TRANSFORMATION à appliquer "
        "à l'image (style, ambiance, retouche, mise en scène), pas une scène repartant de zéro. "
        "Pas de texte incrusté."
    ),
    "t2v": (
        "VIDÉO (texte→vidéo). Formule : Sujet + Action + Contexte + (Caméra + Lumière + Ambiance). "
        "Un SEUL mouvement de caméra (ex. slow dolly in, gentle pan). Décris ce qui BOUGE. "
        "Évite les nombres, les actions complexes, le texte/bandeau incrusté."
    ),
    "i2v": (
        "IMAGE→VIDÉO (une image de référence est animée). NE re-décris PAS la scène : décris "
        "UNIQUEMENT le MOUVEMENT à insuffler — mouvement ambiant subtil (eau, nuages, feuillage, "
        "vapeur, scintillement de lumière) + au plus un léger mouvement de caméra (slow push-in). "
        "Bannis « promotional/screens/text/banner/poster » : ces mots font peindre du texte."
    ),
    "music": (
        "MUSIQUE. Décris en anglais le genre, l'ambiance, le tempo, les instruments, l'usage "
        "(ex. background in-store). Pas de paroles."
    ),
    "voice": (
        "VOIX (le prompt = le TEXTE à dire). Rédige un script de voix-off COURT (1-3 phrases), "
        "naturel à l'oral, dans la LANGUE demandée par l'utilisateur. Pas de didascalies."
    ),
}

_DEFAULT_NEGATIVE = {
    "image": "text, captions, watermark, logo, letters, lowres, blurry, deformed, extra fingers",
    "video": "text, captions, banner, watermark, letters, melting background, warped faces, "
             "jittery camera, flicker",
}

_SYSTEM_PROMPT = (
    "Tu es un expert en rédaction de prompts pour des modèles génératifs (digital signage / "
    "publicité en magasin). On te donne l'IDÉE d'un utilisateur (dans n'importe quelle langue, "
    "parfois une méta-instruction maladroite) et le type de modèle visé. Ton rôle : produire un "
    "PROMPT FINAL clair, EN ANGLAIS, optimisé pour ce modèle.\n"
    "Règles de qualité : mots simples et concrets ; 3 à 5 éléments de contexte au maximum ; "
    "décris le sujet, l'action, le style, et (vidéo) la caméra/lumière ; JAMAIS de méta-langage "
    "(« promotional content », « display on screens »…) ni de demande de texte incrusté.\n"
    "Réponds UNIQUEMENT en JSON valide (sans markdown), de la forme : "
    '{"ready": true|false, "questions": ["..."], "prompt": "...", "negative_prompt": "...", '
    '"notes": "..."}.\n'
    "- `prompt` : le prompt final en ANGLAIS (null si tu poses des questions).\n"
    "- `negative_prompt` : ce qu'il faut éviter (anglais) SI le modèle le supporte, sinon null.\n"
    "- `notes` : 1 phrase de conseil dans la LANGUE de l'utilisateur (pourquoi ce prompt, ou ce "
    "qu'il peut ajuster).\n"
    "- `questions` : en mode conversationnel UNIQUEMENT, 1 à 3 questions courtes (langue de "
    "l'utilisateur) si l'idée est vague ; alors ready=false et prompt=null. Sinon ready=true.\n"
    "En mode one-shot, ne pose JAMAIS de question : ready=true, questions=[]."
)


def _category(kind: str, reference_present: bool) -> str:
    if kind == "video":
        return "i2v" if reference_present else "t2v"
    if kind == "image":
        return "i2i" if reference_present else "t2i"
    return kind  # music | voice


def supports_negative_for(model_id: str | None, kind: str) -> bool:
    """Le modèle accepte-t-il un negative prompt ? (flag catalogue, défaut prudent = non)."""
    spec = catalog.get_model(model_id) if model_id else None
    return bool(spec and spec.get("supports_negative_prompt"))


def fallback(intent: str, *, ready: bool = True) -> dict:
    """Repli gracieux (LLM indisponible / mode strict) : le prompt brut, non assisté."""
    return {
        "ready": ready,
        "questions": [],
        "prompt": intent.strip() or None,
        "negative_prompt": None,
        "notes": "",
        "assisted": False,
    }


def _coerce(data: dict, *, supports_negative: bool, one_shot: bool) -> dict:
    ready = bool(data.get("ready", True))
    questions = data.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    questions = [str(q).strip() for q in questions if str(q).strip()][:_MAX_QUESTIONS]
    if one_shot:  # en one-shot on ne pose jamais de question
        ready, questions = True, []
    prompt = str(data.get("prompt") or "").strip() or None
    if not ready and questions:
        prompt = None  # questions en attente → pas encore de prompt
    elif prompt is None:
        ready = True  # pas de question et pas de prompt → considérer prêt (repli plus haut)
    neg = str(data.get("negative_prompt") or "").strip() or None
    if not supports_negative:
        neg = None
    notes = str(data.get("notes") or "").strip()
    return {
        "ready": ready,
        "questions": questions,
        "prompt": prompt,
        "negative_prompt": neg,
        "notes": notes,
        "assisted": True,
    }


async def assist_prompt(
    *,
    kind: str,
    model_id: str | None,
    reference_present: bool,
    mode: str,
    intent: str | None = None,
    messages: list[dict] | None = None,
    locale: str = "en",
    model: str | None = None,
    byok_key: str | None = None,
    brand: dict | None = None,
    timeout: float = 40.0,
) -> dict:
    """Retourne {ready, questions[], prompt, negative_prompt, notes, assisted}. Best-effort.

    `brand` = charte de marque effective (P3.4). Elle entre dans le prompt système comme
    **atmosphère à viser** ; le logo, le nom et les mentions restent hors du travail du modèle
    (`brand_kit.prompt_block`). Absente ⇒ l'assistant est exactement ce qu'il était."""
    one_shot = mode != "conversational"
    cat = _category(kind, reference_present)
    supports_negative = supports_negative_for(model_id, kind)
    raw_intent = (intent or (messages[-1]["content"] if messages else "") or "").strip()

    guidance = _GUIDANCE.get(cat, _GUIDANCE["t2i"])
    neg_hint = _DEFAULT_NEGATIVE.get(kind)
    brand_hint = brand_kit.prompt_block(brand)
    sys = (
        f"{_SYSTEM_PROMPT}\n\nType de modèle visé : {guidance}\n"
        f"Langue de l'utilisateur (pour `notes`/`questions`) : {locale}.\n"
        + (
            f"Ce modèle SUPPORTE un negative prompt — propose-en un utile "
            f"(par défaut autour de : {neg_hint}).\n"
            if supports_negative else
            "Ce modèle ne supporte PAS de negative prompt — mets negative_prompt à null.\n"
        )
        + ("Mode ONE-SHOT : produis directement le prompt final.\n"
           if one_shot else
           "Mode CONVERSATIONNEL : pose 1-3 questions si l'idée est vague, sinon livre.\n")
        + (f"\n{brand_hint}" if brand_hint else "")
    )

    llm_messages: list[dict] = [{"role": "system", "content": sys}]
    if one_shot:
        llm_messages.append({
            "role": "user",
            "content": f"Idée de l'utilisateur :\n{raw_intent}\n\nProduis le JSON final.",
        })
    else:
        for m in (messages or []):
            role = "assistant" if m.get("role") == "assistant" else "user"
            llm_messages.append({"role": role, "content": str(m.get("content") or "")})
        if not messages:
            llm_messages.append({"role": "user", "content": raw_intent})

    mdl = model or settings.CMS_ASSISTANT_MODEL
    try:
        if byok_key:
            import litellm

            from app.services.ai_credentials import sdk_model_name

            resp = litellm.completion(
                model=sdk_model_name(mdl), messages=llm_messages, max_tokens=800,
                temperature=0.6, api_key=byok_key, timeout=timeout, drop_params=True,
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
                        "model": mdl, "messages": llm_messages,
                        "max_tokens": 800, "temperature": 0.6,
                    },
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("assist_prompt LLM indisponible (%s) → repli brut", exc.__class__.__name__)
        return fallback(raw_intent)

    m = _JSON_RE.search(content or "")
    if not m:
        return fallback(raw_intent)
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback(raw_intent)
    return _coerce(data, supports_negative=supports_negative, one_shot=one_shot)
