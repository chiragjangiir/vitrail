"""« Jeanine » — passerelle messagerie vers l'agent assistant (§XXVII). POC Telegram.

Réutilise TOUT le moteur existant : `run_agent` (RAG + intents + préparation d'actions),
`sign_batch`/`verify_batch`/`consume_action_token`/`execute_batch` (confirmation par jeton
signé usage-unique, RBAC re-vérifié par étape), quotas `cms_assistant_stats`, BYOK.

Ce module n'ajoute que le canal : webhook entrant → identité (opt-in par code de liaison)
→ agent → réponse sortante ; les propositions d'actions deviennent une question « OUI/NON »
dont le OUI retrouve le jeton stocké sur l'identité (état de conversation par fil).

Abstraction multi-canaux : tout ce qui est spécifique Telegram est confiné dans
`send_telegram` + le parsing de l'update ; le flux (`_handle_message`) est réutilisable
tel quel pour WhatsApp/Twilio (même contrat : external_user_id, chat_id, text).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial

import anyio
import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_password
from app.db.session import AsyncSessionLocal, WorkerSessionLocal
from app.models.messaging import CmsMessagingIdentity
from app.models.organization import CmsOrganization
from app.models.user import CmsUser
from app.services import messaging_voice as mv
from app.services import rbac, spend
from app.services.spend import SpendCapExceeded
from app.services.ai_credentials import resolve_ai_credentials
from app.services.assistant_actions import (
    ACTION_TTL_S,
    PIN_REQUIRED_ACTIONS,
    consume_action_token,
    execute_batch,
    sign_batch,
    verify_batch,
)
from app.services.assistant_agent import run_agent
from app.services.assistant_quota import quota_status, usage_in_period

logger = logging.getLogger(__name__)

LINK_CODE_TTL_S = 600          # code de liaison opt-in : 10 min
BOT_USERNAME_TTL_S = 24 * 3600  # username public du bot (getMe), caché Redis
HISTORY_TTL_S = 24 * 3600      # historique de conversation par fil (Redis)
HISTORY_MAX_MESSAGES = 12      # derniers échanges gardés (borne le prompt)
TELEGRAM_MAX_CHARS = 3900      # limite API 4096 — marge
# PIN actions sensibles (migr 0090, décisions Ed 2026-07-13) : 6 chiffres,
# valable pour UNE action, ~2 min pour le saisir, 3 essais puis verrou 15 min.
PIN_TTL_S = 120
PIN_MAX_ATTEMPTS = 3
PIN_LOCK_MINUTES = 15
_PIN_RE = re.compile(r"^\d{6}$")

_YES = {"oui", "yes", "ok", "confirme", "confirm", "go", "y", "👍", "d'accord", "daccord"}
_NO = {"non", "no", "annule", "annuler", "cancel", "stop", "n"}

# Messages de service de la passerelle (hors réponses de l'agent, qui suivent déjà la
# locale du profil). fr/en seulement pour le POC — même repli que le widget (en).
_MSG = {
    "not_linked": {
        "fr": "Ce compte Telegram n'est lié à aucun utilisateur Vitrail. "
              "Générez un code de liaison dans le CMS puis envoyez : /link VOTRECODE",
        "en": "This Telegram account is not linked to any Vitrail user. "
              "Generate a link code in the CMS, then send: /link YOURCODE",
    },
    "linked": {
        "fr": "✅ Compte lié ! Je suis Jeanine, l'assistante Vitrail. "
              "Posez-moi une question ou demandez-moi une action.",
        "en": "✅ Account linked! I'm Jeanine, the Vitrail assistant. "
              "Ask me a question or request an action.",
    },
    "bad_code": {
        "fr": "Code de liaison invalide ou expiré. Générez-en un nouveau dans le CMS.",
        "en": "Invalid or expired link code. Generate a new one in the CMS.",
    },
    "confirm_prompt": {
        "fr": "Répondez OUI pour confirmer, NON pour annuler.",
        "en": "Reply YES to confirm, NO to cancel.",
    },
    "cancelled": {
        "fr": "D'accord, j'annule. Rien n'a été modifié.",
        "en": "Okay, cancelled. Nothing was changed.",
    },
    "expired": {
        "fr": "La proposition a expiré. Reformulez votre demande.",
        "en": "The proposal has expired. Please rephrase your request.",
    },
    "done": {"fr": "✅ C'est fait.", "en": "✅ Done."},
    "failed": {"fr": "❌ Échec :", "en": "❌ Failed:"},
    "ai_disabled": {
        "fr": "L'IA n'est pas configurée pour votre organisation (clé API manquante).",
        "en": "AI is not configured for your organization (missing API key).",
    },
    "quota": {
        "fr": "Le quota IA de votre organisation est épuisé pour la période en cours.",
        "en": "Your organization's AI quota is exhausted for the current period.",
    },
    "error": {
        "fr": "Désolée, une erreur est survenue. Réessayez dans un instant.",
        "en": "Sorry, something went wrong. Please try again shortly.",
    },
    # PIN actions sensibles (migr 0090)
    "pin_prompt": {
        "fr": "🔐 Action sensible : envoyez votre code PIN à 6 chiffres pour exécuter "
              "(ou NON pour annuler). Valable 2 minutes.",
        "en": "🔐 Sensitive action: send your 6-digit PIN code to execute "
              "(or NO to cancel). Valid for 2 minutes.",
    },
    "pin_reminder": {
        "fr": "J'attends votre code PIN à 6 chiffres (ou NON pour annuler).",
        "en": "I'm waiting for your 6-digit PIN code (or NO to cancel).",
    },
    "pin_required": {
        "fr": "Cette action est sensible et exige un code PIN. Définissez-le dans votre "
              "profil CMS (carte Messagerie), puis refaites votre demande.",
        "en": "This action is sensitive and requires a PIN code. Set one in your CMS "
              "profile (Messaging card), then make your request again.",
    },
    "pin_wrong": {
        "fr": "Code incorrect. Il reste {n} essai(s).",
        "en": "Wrong code. {n} attempt(s) left.",
    },
    "pin_locked": {
        "fr": "Trop d'essais : le PIN est verrouillé 15 minutes et la proposition est annulée.",
        "en": "Too many attempts: PIN locked for 15 minutes and the proposal is cancelled.",
    },
    "pin_locked_active": {
        "fr": "Votre PIN est temporairement verrouillé (trop d'essais). Réessayez plus tard.",
        "en": "Your PIN is temporarily locked (too many attempts). Try again later.",
    },
    # Vocal (STT fal Whisper + TTS ElevenLabs, strict BYOK)
    "voice_unavailable": {
        "fr": "Le vocal n'est pas configuré pour votre organisation (clé fal.ai manquante "
              "dans Paramètres → IA). Écrivez-moi en texte.",
        "en": "Voice is not configured for your organization (missing fal.ai key in "
              "Settings → AI). Please write to me in text.",
    },
    "voice_too_long": {
        "fr": "Message vocal trop long (2 minutes max).",
        "en": "Voice message too long (2 minutes max).",
    },
    # Plafond de dépense BYOK atteint (P3.2). On le DIT plutôt que de rester muet : un
    # silence se lit comme une panne, et l'utilisateur réessaierait indéfiniment.
    "voice_spend_cap": {
        "fr": "Le plafond de dépense IA de votre organisation est atteint pour la période "
              "en cours. Le vocal est suspendu ; écrivez-moi en texte.",
        "en": "Your organization's AI spending cap has been reached for the current period. "
              "Voice is paused; write to me instead.",
        "es": "Se alcanzó el límite de gasto de IA de su organización en el periodo actual. "
              "La voz está pausada; escríbame.",
        "pt": "O limite de despesa de IA da sua organização foi atingido no período atual. "
              "A voz está suspensa; escreva-me.",
        "de": "Das KI-Ausgabenlimit Ihrer Organisation ist für den aktuellen Zeitraum "
              "erreicht. Die Sprachausgabe pausiert; schreiben Sie mir stattdessen.",
    },
    "voice_failed": {
        "fr": "Je n'ai pas réussi à comprendre ce message vocal. Réessayez ou écrivez-moi.",
        "en": "I couldn't understand that voice message. Try again or write to me.",
    },
    "voice_pin": {
        "fr": "🔐 Le code PIN se saisit au clavier, jamais à la voix.",
        "en": "🔐 The PIN code must be typed, never spoken.",
    },
}


def _t(locale: str, key: str) -> str:
    lang = (locale or "en").split("-")[0]
    return _MSG[key].get(lang, _MSG[key]["en"])


# ── Seams de session (monkeypatchés par les tests, cf. conftest sans RLS) ────────────


@asynccontextmanager
async def _worker_session():
    """Session BYPASSRLS — résolution d'identité cross-org (le webhook n'a pas d'user)."""
    async with WorkerSessionLocal() as session:
        yield session


@asynccontextmanager
async def _org_session(id_org: int):
    """Session app RLS posée sur l'org de l'identité résolue (miroir de deps.get_db)."""
    async with AsyncSessionLocal() as session:
        session.info["current_org_id"] = id_org
        await session.connection()
        yield session


# ── Canal Telegram (envoi sortant) ────────────────────────────────────────────────────


async def send_telegram(chat_id: str, message: str) -> None:
    """Envoie un message texte (découpé si > limite API). Best-effort : loggue l'échec."""
    token = settings.CMS_TELEGRAM_BOT_TOKEN
    if not token:
        return
    chunks = [message[i:i + TELEGRAM_MAX_CHARS]
              for i in range(0, len(message), TELEGRAM_MAX_CHARS)] or [""]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                resp = await client.post(
                    f"{settings.CMS_TELEGRAM_API_BASE}/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                )
                if resp.status_code != 200:
                    logger.warning("jeanine: sendMessage %s → %s %s",
                                   chat_id, resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        logger.warning("jeanine: sendMessage %s KO: %s", chat_id, exc)


async def delete_telegram(chat_id: str, message_id: int) -> None:
    """Supprime un message du fil — hygiène : le code PIN saisi ne doit pas rester
    lisible dans l'historique Telegram. Best-effort (autorisé en chat privé < 48 h)."""
    token = settings.CMS_TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.CMS_TELEGRAM_API_BASE}/bot{token}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
            )
    except httpx.HTTPError as exc:
        logger.info("jeanine: deleteMessage %s KO: %s", chat_id, exc)


async def get_bot_username() -> str | None:
    """Username public du bot (`getMe`), caché Redis 24 h — best-effort (None si échec).

    Sert à l'UI settings pour afficher le lien t.me/<bot> ; aucune fonctionnalité n'en
    dépend (la liaison marche sans)."""
    token = settings.CMS_TELEGRAM_BOT_TOKEN
    if not token:
        return None
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        cached = await r.get("signflow:msg:botname")
        if cached:
            return cached.decode() if isinstance(cached, bytes) else str(cached)
        username = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{settings.CMS_TELEGRAM_API_BASE}/bot{token}/getMe")
                if resp.status_code == 200:
                    username = (resp.json().get("result") or {}).get("username")
        except Exception as exc:  # noqa: BLE001 — réseau/JSON : purement cosmétique
            logger.info("jeanine: getMe indisponible: %s", exc)
        if username:
            await r.setex("signflow:msg:botname", BOT_USERNAME_TTL_S, username)
        return username
    finally:
        await r.aclose()


# ── Liaison opt-in (code généré côté CMS, consommé par /link) ─────────────────────────


async def create_link_code(id_user: int, id_org: int) -> str:
    """Génère un code de liaison usage-unique (Redis, TTL 10 min) pour l'utilisateur."""
    code = secrets.token_hex(4).upper()  # 8 hex — dictable sur un téléphone
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        await r.setex(
            f"signflow:msg:linkcode:{code}", LINK_CODE_TTL_S,
            json.dumps({"uid": id_user, "org": id_org}),
        )
    finally:
        await r.aclose()
    return code


async def _consume_link_code(code: str) -> dict | None:
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        key = f"signflow:msg:linkcode:{code.upper()}"
        raw = await r.get(key)
        if raw is None:
            return None
        await r.delete(key)  # usage unique
        return json.loads(raw)
    finally:
        await r.aclose()


# ── Historique de conversation par fil (Redis, TTL 24 h) ─────────────────────────────


async def _load_history(id_identity: int) -> list[dict]:
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        raw = await r.get(f"signflow:msg:hist:{id_identity}")
        return json.loads(raw) if raw else []
    finally:
        await r.aclose()


async def _save_history(id_identity: int, history: list[dict]) -> None:
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        await r.setex(f"signflow:msg:hist:{id_identity}", HISTORY_TTL_S,
                      json.dumps(history[-HISTORY_MAX_MESSAGES:], ensure_ascii=False))
    finally:
        await r.aclose()


# ── Contexte IA (miroir de la politique du chat widget — BYOK/quota/désactivé) ───────


async def _resolve_ai_context(
    db: AsyncSession, user: CmsUser, roles: list[str]
) -> tuple[str | None, bool, bool]:
    """→ (byok_key, ai_disabled, quota_blocked) — même politique « rien d'auto » que
    POST /assistant/chat (super-admin = clé plateforme sans quota ; byok = clé client
    sans quota ; platform = quota ; strict sans clé = IA coupée)."""
    if "CMS_SUPER_ADMIN" in roles:
        return None, False, False
    org = (await db.execute(
        select(CmsOrganization).where(CmsOrganization.id_org == user.id_org)
    )).scalar_one_or_none()
    resolved = await resolve_ai_credentials(db, org, "anthropic") if org is not None else None
    if resolved is None:
        return None, True, False
    if resolved.byok:
        return resolved.api_key, False, False
    usage = await usage_in_period(db, user.id_org, org.ai_quota_period, datetime.now(UTC).date())
    return None, False, quota_status(org, usage["tokens"])["blocked"]


async def _record_usage(db: AsyncSession, id_org: int, tokens: int) -> None:
    """Alimente cms_assistant_stats (le quota lit ces stats) — même compteur best-effort
    que `_persist_exchange` du widget."""
    try:
        await db.execute(
            text(
                "INSERT INTO cms_assistant_stats (id_org, stat_date, message_count, token_count) "
                "VALUES (:org, current_date, 1, :tok) "
                "ON CONFLICT (id_org, stat_date) DO UPDATE SET "
                "  message_count = cms_assistant_stats.message_count + 1, "
                "  token_count = cms_assistant_stats.token_count + EXCLUDED.token_count, "
                "  updated_at = now()"
            ),
            {"org": id_org, "tok": tokens},
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("jeanine: stats d'usage non enregistrées: %s", exc)
        await db.rollback()


# ── Flux principal ────────────────────────────────────────────────────────────────────


async def process_telegram_update(update: dict) -> None:
    """Point d'entrée background du webhook. Ne lève jamais (loggue et répond un message
    d'erreur générique si possible)."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = str(msg.get("chat", {}).get("id", ""))
    external_id = str(msg.get("from", {}).get("id", ""))
    display_name = " ".join(filter(None, [
        msg.get("from", {}).get("first_name"), msg.get("from", {}).get("last_name"),
    ]))[:120] or None
    # Message VOCAL → STT Whisper (fal, BYOK) puis même flux que le texte.
    if isinstance(msg.get("voice"), dict) and chat_id and external_id:
        try:
            await _handle_voice(msg["voice"], external_id, chat_id, display_name)
        except Exception:  # noqa: BLE001
            logger.exception("jeanine: échec de traitement d'un message vocal")
            await send_telegram(chat_id, _t("en", "error"))
        return
    if not isinstance(msg.get("text"), str):
        return  # stickers, photos, membres… hors périmètre
    text_in = msg["text"].strip()
    if not chat_id or not external_id or not text_in:
        return
    message_id = msg.get("message_id")

    async def _delete_incoming() -> None:
        if message_id is not None:
            await delete_telegram(chat_id, message_id)

    try:
        await _handle_message("telegram", external_id, chat_id, display_name,
                              text_in, send=send_telegram, delete=_delete_incoming)
    except Exception:  # noqa: BLE001 — le webhook a déjà répondu 200, on ne peut que logguer
        logger.exception("jeanine: échec de traitement de l'update telegram")
        await send_telegram(chat_id, _t("en", "error"))


async def _handle_voice(
    voice: dict, external_id: str, chat_id: str, display_name: str | None,
) -> None:
    """Message vocal : identité → clé fal (BYOK strict) → STT → écho « 🎤 … » →
    flux texte habituel → réponse texte + note vocale ElevenLabs (best-effort).

    Le PIN ne se dit JAMAIS à la voix : en attente de code, le vocal est refusé
    (sinon le code partirait chez fal et son écho resterait lisible dans le fil)."""
    async with _worker_session() as wdb:
        identity = (await wdb.execute(
            select(CmsMessagingIdentity).where(
                CmsMessagingIdentity.channel == "telegram",
                CmsMessagingIdentity.external_user_id == external_id,
                CmsMessagingIdentity.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if identity is None:
            await send_telegram(chat_id, _t("en", "not_linked") + "\n\n" + _t("fr", "not_linked"))
            return
        user = (await wdb.execute(
            select(CmsUser).where(CmsUser.id_user == identity.id_user,
                                  CmsUser.is_active == True)  # noqa: E712
        )).scalar_one_or_none()
        if user is None:
            await send_telegram(chat_id, _t("en", "not_linked"))
            return
        locale = user.locale or "en"
        if identity.pending_token and identity.pending_stage == "pin":
            await send_telegram(chat_id, _t(locale, "voice_pin"))
            return
        org = (await wdb.execute(
            select(CmsOrganization).where(CmsOrganization.id_org == identity.id_org)
        )).scalar_one_or_none()
        fal_key = await resolve_ai_credentials(wdb, org, "fal") if org is not None else None
        el_key = await resolve_ai_credentials(wdb, org, "elevenlabs") if org is not None else None

    if fal_key is None:
        await send_telegram(chat_id, _t(locale, "voice_unavailable"))
        return
    if (voice.get("duration") or 0) > mv.VOICE_MAX_DURATION_S:
        await send_telegram(chat_id, _t(locale, "voice_too_long"))
        return
    audio = await mv.download_telegram_voice(voice.get("file_id") or "")
    if audio is None:
        await send_telegram(chat_id, _t(locale, "voice_failed"))
        return
    # Plafond de dépense BYOK (P3.2) : la transcription Whisper passe par fal et est
    # FACTURÉE. Ce chemin n'écrivait aucune trace de coût — un client pouvait solliciter
    # Jeanine par messagerie sans aucune limite.
    try:
        id_spend = await _reserve_voice_spend(
            identity.id_org, user.id_user, provider="fal", kind="voice",
            model=mv.FAL_WHISPER_MODEL,
            # Estimation sur la durée RÉELLE du message vocal, pas sur le maximum autorisé :
            # réserver 60 s pour un message de 3 s viderait le plafond pour rien.
            estimated_usd=mv.whisper_cost_usd(voice.get("duration")))
    except SpendCapExceeded:
        await send_telegram(chat_id, _t(locale, "voice_spend_cap"))
        return
    # Hint de langue = locale du profil (fr/en/es/pt/de) → Whisper ne devine plus.
    transcript = await mv.transcribe_voice(
        audio, fal_key.api_key, voice.get("mime_type") or "audio/ogg",
        language=locale)
    await _settle_voice_spend(id_spend)
    if not transcript:
        await send_telegram(chat_id, _t(locale, "voice_failed"))
        return
    # Écho de ce qui a été compris (hors TTS) — l'utilisateur voit/corrige.
    await send_telegram(chat_id, f"🎤 « {transcript} »")

    replies: list[str] = []

    async def _send_and_collect(cid: str, message: str) -> None:
        await send_telegram(cid, message)
        replies.append(message)

    await _handle_message("telegram", external_id, chat_id, display_name,
                          transcript, send=_send_and_collect)

    # Réponse en voix (best-effort) : clé ElevenLabs org + texte raisonnable.
    if el_key is None:
        return
    tts = mv.tts_text(replies)
    if not tts:
        return
    try:
        from app.services.generation.elevenlabs import generate_voice

        # La réponse TEXTE est déjà partie : un plafond atteint ne doit pas la défaire, il
        # supprime seulement la version vocale. On ne redit rien à l'utilisateur ici — il
        # vient de recevoir sa réponse, un second message serait du bruit.
        id_spend = await _reserve_voice_spend(
            identity.id_org, user.id_user, provider="elevenlabs", kind="voice",
            model=None, estimated_usd=mv.tts_cost_usd(tts))
        audio_out, _ctype, cost = await anyio.to_thread.run_sync(
            partial(generate_voice, text=tts, api_key=el_key.api_key))
        await _settle_voice_spend(id_spend, cost)
        await mv.send_telegram_voice(chat_id, audio_out)
    except SpendCapExceeded:
        logger.info("jeanine vocal: plafond de dépense atteint — réponse texte seule")
    except Exception as exc:  # noqa: BLE001 — la réponse texte est déjà partie
        logger.info("jeanine vocal: TTS ElevenLabs KO: %s", exc)


async def _reserve_voice_spend(
    id_org: int, id_user: int | None, *, provider: str, kind: str,
    model: str | None, estimated_usd: float,
) -> int:
    """Réserve une dépense pour le vocal (P3.2), dans sa PROPRE session.

    La session de lecture est déjà refermée à ce stade, et une réservation doit être
    committée AVANT l'appel fournisseur pour tenir face à un second message simultané —
    la garder dans une transaction ouverte pendant l'appel réseau ne réserverait rien.
    """
    # ⚠️ Passe par `_worker_session()` et JAMAIS par `WorkerSessionLocal` directement : ce
    # module expose cette indirection précisément pour que les tests puissent y substituer
    # leur session. L'avoir contournée faisait écrire dans la base APPLICATIVE depuis un test
    # qui vit dans la base de TEST — clé étrangère en violation, et le vocal cassé.
    async with _worker_session() as db:
        id_spend = await spend.reserve(
            db, id_org=id_org, id_user=id_user, provider=provider, kind=kind,
            model=model, estimated_usd=estimated_usd)
        await db.commit()
        return id_spend


async def _settle_voice_spend(id_spend: int, actual_usd: float | None = None) -> None:
    async with _worker_session() as db:
        await spend.settle(db, id_spend, actual_usd)
        await db.commit()


def _clear_pending(identity: CmsMessagingIdentity) -> None:
    identity.pending_token = identity.pending_summary = None
    identity.pending_expires_at = None
    identity.pending_stage = "confirm"


async def _handle_message(
    channel: str, external_id: str, chat_id: str, display_name: str | None,
    text_in: str, send, delete=None,
) -> None:
    """Cœur canal-agnostique : identité → (link | confirmation [PIN] | agent) → réponse.

    `delete` (optionnel) : suppression du message ENTRANT dans le fil — utilisé sur
    la saisie du PIN (le code ne doit pas rester lisible dans l'historique)."""
    # 1. Identité (session worker : on ne connaît pas encore l'org).
    async with _worker_session() as wdb:
        identity = (await wdb.execute(
            select(CmsMessagingIdentity).where(
                CmsMessagingIdentity.channel == channel,
                CmsMessagingIdentity.external_user_id == external_id,
                CmsMessagingIdentity.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        # /link CODE — liaison opt-in (avant tout le reste : fonctionne sans identité).
        low = text_in.lower()
        if low.startswith("/link"):
            code = text_in.split(maxsplit=1)[1].strip() if len(text_in.split()) > 1 else ""
            payload = await _consume_link_code(code) if code else None
            if payload is None:
                await send(chat_id, _t("en", "bad_code") + "\n" + _t("fr", "bad_code"))
                return
            user = (await wdb.execute(
                select(CmsUser).where(CmsUser.id_user == payload["uid"])
            )).scalar_one_or_none()
            if user is None or not user.is_active:
                await send(chat_id, _t("en", "bad_code"))
                return
            if identity is None:
                identity = CmsMessagingIdentity(
                    id_org=payload["org"], id_user=payload["uid"], channel=channel,
                    external_user_id=external_id, chat_id=chat_id,
                    display_name=display_name,
                )
                wdb.add(identity)
            else:  # re-liaison : même compte Telegram vers un autre user CMS
                identity.id_org, identity.id_user = payload["org"], payload["uid"]
                identity.chat_id, identity.display_name = chat_id, display_name
                _clear_pending(identity)
            await wdb.commit()
            await send(chat_id, _t(user.locale, "linked"))
            return

        if identity is None:
            await send(chat_id, _t("en", "not_linked") + "\n\n" + _t("fr", "not_linked"))
            return

        user = (await wdb.execute(
            select(CmsUser).where(CmsUser.id_user == identity.id_user,
                                  CmsUser.is_active == True)  # noqa: E712
        )).scalar_one_or_none()
        if user is None:
            await send(chat_id, _t("en", "not_linked"))
            return
        identity.last_seen_at = datetime.now(UTC)
        identity.chat_id = chat_id  # suit les migrations de chat (groupe→privé…)
        pending_token = identity.pending_token
        pending_expired = (identity.pending_expires_at is not None
                           and identity.pending_expires_at < datetime.now(UTC))
        id_identity, id_org, id_user = identity.id_identity, identity.id_org, identity.id_user
        locale = user.locale or "en"

        # Compte lié : /start ou /help = simple rappel de présence (pas de tour d'agent).
        if low in ("/start", "/help"):
            await wdb.commit()
            await send(chat_id, _t(locale, "linked"))
            return

        # Exécution d'un lot confirmé (chemin commun OUI-non-sensible / PIN correct).
        async def _execute_pending(token: str) -> None:
            steps = verify_batch(token, user)
            if steps is None or not await consume_action_token(token):
                await send(chat_id, _t(locale, "expired"))
                return
            async with _org_session(id_org) as odb:
                result = await execute_batch(odb, user, steps)
            ok, message = result.get("ok"), result.get("message") or result.get("error") or ""
            await send(chat_id, f"{_t(locale, 'done')} {message}".strip() if ok
                       else f"{_t(locale, 'failed')} {message}".strip())

        # 2a. Étape PIN : OUI déjà reçu sur une action SENSIBLE — on attend le code
        # (6 chiffres, 2 min, 3 essais puis verrou — décisions Ed 2026-07-13).
        norm = low.rstrip(".!… ")
        if pending_token and identity.pending_stage == "pin":
            if norm in _NO or low == "/cancel":
                _clear_pending(identity)
                await wdb.commit()
                await send(chat_id, _t(locale, "cancelled"))
                return
            if _PIN_RE.fullmatch(text_in):
                # Hygiène : le code saisi ne reste pas lisible dans le fil (best-effort).
                if delete is not None:
                    await delete()
                if pending_expired:
                    _clear_pending(identity)
                    await wdb.commit()
                    await send(chat_id, _t(locale, "expired"))
                    return
                if user.assistant_pin_hash and verify_password(text_in, user.assistant_pin_hash):
                    _clear_pending(identity)
                    identity.pin_attempts = 0
                    await wdb.commit()
                    await _execute_pending(pending_token)
                    return
                identity.pin_attempts += 1
                if identity.pin_attempts >= PIN_MAX_ATTEMPTS:
                    _clear_pending(identity)
                    identity.pin_attempts = 0
                    identity.pin_locked_until = (
                        datetime.now(UTC) + timedelta(minutes=PIN_LOCK_MINUTES))
                    await wdb.commit()
                    await send(chat_id, _t(locale, "pin_locked"))
                    return
                remaining = PIN_MAX_ATTEMPTS - identity.pin_attempts
                await wdb.commit()
                await send(chat_id, _t(locale, "pin_wrong").format(n=remaining))
                return
            await wdb.commit()
            await send(chat_id, _t(locale, "pin_reminder"))
            return

        # 2b. Confirmation / annulation d'une proposition en attente.
        if pending_token and (norm in _YES or norm in _NO or low == "/cancel"):
            if norm in _NO or low == "/cancel":
                _clear_pending(identity)
                await wdb.commit()
                await send(chat_id, _t(locale, "cancelled"))
                return
            if pending_expired:
                _clear_pending(identity)
                await wdb.commit()
                await send(chat_id, _t(locale, "expired"))
                return
            steps_preview = verify_batch(pending_token, user)
            if steps_preview is None:
                _clear_pending(identity)
                await wdb.commit()
                await send(chat_id, _t(locale, "expired"))
                return
            # OUI sur un lot contenant une action sensible → 2e facteur PIN.
            if any(s.get("act") in PIN_REQUIRED_ACTIONS for s in steps_preview):
                if (identity.pin_locked_until is not None
                        and identity.pin_locked_until > datetime.now(UTC)):
                    _clear_pending(identity)
                    await wdb.commit()
                    await send(chat_id, _t(locale, "pin_locked_active"))
                    return
                if not user.assistant_pin_hash:
                    _clear_pending(identity)
                    await wdb.commit()
                    await send(chat_id, _t(locale, "pin_required"))
                    return
                identity.pending_stage = "pin"
                identity.pin_attempts = 0
                identity.pending_expires_at = datetime.now(UTC) + timedelta(seconds=PIN_TTL_S)
                await wdb.commit()
                await send(chat_id, _t(locale, "pin_prompt"))
                return
            _clear_pending(identity)
            await wdb.commit()
            await _execute_pending(pending_token)
            return
        await wdb.commit()  # last_seen/chat_id même sans confirmation

    # 3. Tour d'agent (session RLS org — mêmes gardes BYOK/quota que le widget).
    async with _org_session(id_org) as odb:
        roles = await rbac.get_user_role_keys(odb, id_user)
        byok_key, ai_disabled, quota_blocked = await _resolve_ai_context(odb, user, roles)
        if ai_disabled:
            await send(chat_id, _t(locale, "ai_disabled"))
            return
        if quota_blocked:
            await send(chat_id, _t(locale, "quota"))
            return

        history = await _load_history(id_identity)
        history.append({"role": "user", "content": text_in})
        usage: dict[str, int] = {}
        proposals: list[dict] = []
        parts: list[str] = []
        async for frag in run_agent(
            odb, id_org=id_org, id_user=id_user, roles=roles, locale=locale,
            messages=history, usage_out=usage, proposals_out=proposals, byok_key=byok_key,
        ):
            parts.append(frag)
        answer = "".join(parts).strip()

        if usage.get("total"):
            await _record_usage(odb, id_org, usage["total"])

    # 4. Réponse + proposition éventuelle (le jeton attend le OUI sur l'identité).
    reply = answer or ""
    if proposals:
        steps = [{"act": p["action_type"], "params": p["params"]} for p in proposals]
        token = sign_batch(id_user, id_org, steps)
        lines = []
        for p in proposals:
            lines.append(f"• {p['description']}")
            lines.extend(f"  ⚠️ {w}" for w in p.get("warnings", []))
        reply = "\n".join(filter(None, [reply, "", *lines, "", _t(locale, "confirm_prompt")]))
        async with _worker_session() as wdb:
            row = (await wdb.execute(
                select(CmsMessagingIdentity)
                .where(CmsMessagingIdentity.id_identity == id_identity)
            )).scalar_one()
            row.pending_token = token
            row.pending_summary = [p["description"] for p in proposals]
            row.pending_expires_at = datetime.now(UTC) + timedelta(seconds=ACTION_TTL_S)
            row.pending_stage = "confirm"
            await wdb.commit()

    history.append({"role": "assistant", "content": answer})
    await _save_history(id_identity, history)
    if reply:
        await send(chat_id, reply)
