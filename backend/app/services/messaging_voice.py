"""Jeanine VOCAL (Telegram) — STT fal.ai Whisper + réponse TTS ElevenLabs.

Un message vocal Telegram est transcrit (Whisper hébergé fal.run, clé BYOK org)
puis suit EXACTEMENT le flux texte de la passerelle ; la réponse part en texte
comme aujourd'hui ET en note vocale (ElevenLabs, best-effort — sans clé ou texte
trop long, le texte seul suffit). Strict BYOK des deux côtés (fal + elevenlabs =
jamais de clé plateforme, politique coffre §PLAN_BYOK) : sans clé fal, le vocal
répond « non configuré » — rien d'auto.

Bornes : durée ≤ VOICE_MAX_DURATION_S, fichier ≤ VOICE_MAX_BYTES (l'OGG/Opus
Telegram fait ~1 Mo/2 min), TTS ≤ TTS_MAX_CHARS (coût ElevenLabs au caractère).
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

VOICE_MAX_DURATION_S = 120
VOICE_MAX_BYTES = 3 * 1024 * 1024
TTS_MAX_CHARS = 700
FAL_WHISPER_MODEL = "fal-ai/whisper"

# Plafonds de dépense BYOK (P3.2) — estimation du coût des DEUX appels payants du vocal.
#
# ⚠️ Whisper n'est PAS au catalogue des modèles : le catalogue décrit ce qu'un utilisateur
# choisit dans l'interface, et la transcription n'est pas un choix. Son tarif vit donc ici,
# avec sa provenance — c'est le seul chiffre de ce module qui ne soit pas mesuré. Le
# réservataire n'apprend jamais le montant réel (fal ne le renvoie pas sur ce point de
# terminaison) : la ligne reste donc à l'estimation, et une erreur de tarif décale le
# plafond de quelques centimes sur ce seul chemin.
WHISPER_USD_PER_MINUTE = 0.0055   # tarif public fal.ai pour whisper (2026-08)


def whisper_cost_usd(duration_s: float | int | None) -> float:
    """Coût estimé d'une transcription, sur la durée RÉELLE du message vocal."""
    minutes = max(float(duration_s or 0), 1.0) / 60.0
    return round(WHISPER_USD_PER_MINUTE * minutes, 6)


def tts_cost_usd(text: str) -> float:
    """Coût estimé d'une réponse vocale ElevenLabs.

    🔑 Passe par le CATALOGUE (`elevenlabs/tts`, `per_1k_chars`) plutôt que par un tarif
    recopié : le jour où le prix change, il change à un seul endroit — celui que l'écran
    d'estimation utilise déjà."""
    from app.services.generation import catalog
    return catalog.estimate_cost("elevenlabs/tts", text=text)
FAL_REST = "https://rest.alpha.fal.ai"

# Émojis/symboles de service des réponses (✅ ⚠️ 🔐 •) — inutiles à voix haute.
_TTS_STRIP_RE = re.compile(r"[✅❌⚠️🔐🎤•]|https?://\S+")


def whisper_language(locale: str | None) -> str | None:
    """Locale du profil → code langue Whisper (ISO-639-1, ex. « fr-FR » → « fr »).
    None si inexploitable → Whisper détecte tout seul (comportement d'avant)."""
    lang = (locale or "").strip().lower()[:2]
    return lang if len(lang) == 2 and lang.isalpha() else None


async def download_telegram_voice(file_id: str) -> bytes | None:
    """Télécharge le fichier voix (getFile → /file/bot<token>/<path>). None si échec/trop gros."""
    token = settings.CMS_TELEGRAM_BOT_TOKEN
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta = await client.post(
                f"{settings.CMS_TELEGRAM_API_BASE}/bot{token}/getFile",
                json={"file_id": file_id},
            )
            if meta.status_code != 200:
                return None
            info = (meta.json().get("result") or {})
            path = info.get("file_path")
            if not path or (info.get("file_size") or 0) > VOICE_MAX_BYTES:
                return None
            resp = await client.get(
                f"{settings.CMS_TELEGRAM_API_BASE}/file/bot{token}/{path}")
            if resp.status_code != 200 or len(resp.content) > VOICE_MAX_BYTES:
                return None
            return resp.content
    except httpx.HTTPError as exc:
        logger.warning("jeanine vocal: téléchargement voix KO: %s", exc)
        return None


async def _fal_upload(
    client: httpx.AsyncClient, audio: bytes, fal_key: str, mime: str
) -> str | None:
    """Upload vers le storage fal (initiate → PUT) → URL CDN à donner au modèle.
    fal.run REFUSE les data URIs pour l'audio (422 « Unsupported data URL »,
    constaté prod 2026-07-13) — le storage est le chemin supporté."""
    r = await client.post(
        f"{FAL_REST}/storage/upload/initiate?storage_type=fal-cdn-v3",
        headers={"Authorization": f"Key {fal_key}"},
        json={"content_type": mime, "file_name": "voice.ogg"},
    )
    if r.status_code != 200:
        logger.warning("jeanine vocal: fal storage initiate %s %s",
                       r.status_code, r.text[:200])
        return None
    j = r.json()
    up = await client.put(j["upload_url"], content=audio,
                          headers={"Content-Type": mime})
    if up.status_code not in (200, 201):
        logger.warning("jeanine vocal: fal storage upload %s", up.status_code)
        return None
    return j["file_url"]


async def transcribe_voice(
    audio: bytes, fal_key: str, mime: str = "audio/ogg", language: str | None = None
) -> str | None:
    """STT Whisper via fal : upload storage puis appel synchrone fal.run.
    `language` (hint, code ISO-639-1 : la locale du profil) épargne à Whisper la
    détection auto — reco nettement meilleure sur les voix/accents ambigus.
    None si échec — l'appelant répond un message d'erreur localisé."""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            audio_url = await _fal_upload(client, audio, fal_key, mime)
            if audio_url is None:
                return None
            payload: dict = {"audio_url": audio_url, "task": "transcribe"}
            lang = whisper_language(language)
            if lang:
                payload["language"] = lang
            resp = await client.post(
                f"https://fal.run/{FAL_WHISPER_MODEL}",
                headers={"Authorization": f"Key {fal_key}"},
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning("jeanine vocal: whisper fal %s %s",
                               resp.status_code, resp.text[:200])
                return None
            text = (resp.json().get("text") or "").strip()
            return text or None
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("jeanine vocal: whisper fal KO: %s", exc)
        return None


async def send_telegram_voice(chat_id: str, audio: bytes, mime: str = "audio/mpeg") -> None:
    """Envoie une note vocale (sendVoice accepte OGG/Opus, MP3, M4A). Best-effort."""
    token = settings.CMS_TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.CMS_TELEGRAM_API_BASE}/bot{token}/sendVoice",
                data={"chat_id": chat_id},
                files={"voice": ("reply.mp3", audio, mime)},
            )
            if resp.status_code != 200:
                logger.warning("jeanine vocal: sendVoice %s → %s %s",
                               chat_id, resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        logger.warning("jeanine vocal: sendVoice %s KO: %s", chat_id, exc)


def tts_text(messages: list[str]) -> str | None:
    """Texte à vocaliser à partir des réponses du tour : nettoyé (émojis de service,
    URLs), borné à TTS_MAX_CHARS (au-delà, le texte affiché suffit — coût au caractère)."""
    raw = " ".join(m.strip() for m in messages if m and m.strip())
    cleaned = _TTS_STRIP_RE.sub("", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or len(cleaned) > TTS_MAX_CHARS:
        return None
    return cleaned
