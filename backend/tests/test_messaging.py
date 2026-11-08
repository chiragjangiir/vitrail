"""Tests « Jeanine » (POC Telegram) — passerelle messagerie vers l'agent assistant.

- webhook : 503 sans config, 403 mauvais secret, 200 avec le bon.
- liaison opt-in : /link CODE (code Redis usage-unique) crée l'identité ; code invalide refusé.
- non-lié : message → réponse « not linked », aucun tour d'agent.
- tour d'agent : réponse relayée + proposition → jeton signé stocké en attente sur l'identité.
- confirmation : « oui » exécute le lot (execute_batch) et purge l'attente ; « non » annule.
- UI settings : GET /status (configuré + bot + identités du user courant) ; déliaison self
  bornée à ses propres identités (404 sinon).
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.messaging_gateway as mg
import app.services.messaging_voice as mv
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.messaging import CmsMessagingIdentity
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.user import CmsUser
from app.services.ai_credentials import ResolvedKey
from app.services.assistant_actions import sign_batch


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Jeanine", org_slug=f"msg-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    u = CmsUser(id_org=org.id_org, email=f"msg-{uuid.uuid4().hex[:8]}@t.com",
                password_hash=hash_password("Password1!"), is_active=True, locale="fr")
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture(autouse=True)
def _sessions_on_test_db(monkeypatch, db_session: AsyncSession):
    """La passerelle ouvre ses propres sessions (worker + org RLS) — en test, tout passe
    par la session de test (RLS non activé par create_all, comme le reste de la suite)."""
    @asynccontextmanager
    async def _fake_session(*_args):
        yield db_session

    monkeypatch.setattr(mg, "_worker_session", _fake_session)
    monkeypatch.setattr(mg, "_org_session", _fake_session)


class _SendSpy:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, chat_id: str, message: str) -> None:
        self.sent.append((chat_id, message))

    @property
    def last(self) -> str:
        return self.sent[-1][1] if self.sent else ""


async def _linked_identity(db, org, user, external_id=None):
    """Identité liée avec un id externe UNIQUE par test (contrainte channel+external_user_id
    — la base de test est partagée entre les tests du module)."""
    external_id = external_id or uuid.uuid4().hex[:12]
    ident = CmsMessagingIdentity(
        id_org=org.id_org, id_user=user.id_user, channel="telegram",
        external_user_id=external_id, chat_id=external_id, display_name="Ed")
    db.add(ident)
    await db.commit()
    return ident


# ── Webhook (auth par secret) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_unconfigured_503(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", None)
    resp = await client.post("/api/v1/messaging/telegram/webhook", json={"update_id": 1})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_bad_secret_403(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(settings, "CMS_TELEGRAM_WEBHOOK_SECRET", "s3cret")
    resp = await client.post("/api/v1/messaging/telegram/webhook", json={"update_id": 1},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_ok(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(settings, "CMS_TELEGRAM_WEBHOOK_SECRET", "s3cret")
    # update sans message texte → le handler background sort immédiatement.
    resp = await client.post("/api/v1/messaging/telegram/webhook", json={"update_id": 1},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ── Liaison opt-in ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_code_endpoint_and_link_flow(client: AsyncClient, db_session, org, user,
                                                monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", "t")
    token = create_access_token(user.id_user)
    resp = await client.post("/api/v1/messaging/link-code",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    code = resp.json()["code"]

    send = _SendSpy()
    await mg._handle_message("telegram", "777", "777", "Ed", f"/link {code}", send=send)
    assert "✅" in send.last

    ident = (await db_session.execute(select(CmsMessagingIdentity).where(
        CmsMessagingIdentity.external_user_id == "777"))).scalar_one()
    assert ident.id_user == user.id_user
    assert ident.id_org == org.id_org

    # Le code est usage-unique : rejouer la liaison échoue.
    await mg._handle_message("telegram", "778", "778", "Bob", f"/link {code}", send=send)
    assert "invalide" in send.last or "Invalid" in send.last


@pytest.mark.asyncio
async def test_unlinked_message_gets_link_instructions(db_session, org):
    send = _SendSpy()
    await mg._handle_message("telegram", "999", "999", None, "bonjour", send=send)
    assert "/link" in send.last


# ── Tour d'agent + proposition + confirmation ─────────────────────────────────


@pytest.mark.asyncio
async def test_agent_answer_and_proposal_pending(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)

    async def fake_resolve(_db, _user, _roles):
        return None, False, False  # clé plateforme, pas de quota

    async def fake_agent(_db, **kw):
        kw["proposals_out"].append({
            "action_type": "play_vod", "params": {"id_media": 1, "player_ids": [1],
                                                  "mode": "once"},
            "description": "Lancer « promo.mp4 » sur 1 player", "warnings": ["attention"],
        })
        kw["usage_out"]["total"] = 42
        yield "Je vous propose de lancer la vidéo."

    monkeypatch.setattr(mg, "_resolve_ai_context", fake_resolve)
    monkeypatch.setattr(mg, "run_agent", fake_agent)

    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "lance la promo", send=send)
    assert "Je vous propose" in send.last
    assert "Lancer « promo.mp4 »" in send.last
    assert "OUI" in send.last  # invite de confirmation (locale fr)

    await db_session.refresh(ident)
    assert ident.pending_token is not None
    assert ident.pending_summary == ["Lancer « promo.mp4 » sur 1 player"]


@pytest.mark.asyncio
async def test_confirm_yes_executes_batch(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)
    ident.pending_token = sign_batch(user.id_user, org.id_org,
                                     [{"act": "play_vod", "params": {"id_media": 1}}])
    ident.pending_summary = ["Lancer la promo"]
    ident.pending_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    calls = []

    async def fake_execute(_db, _user, steps):
        calls.append(steps)
        return {"ok": True, "message": "VOD lancée."}

    monkeypatch.setattr(mg, "execute_batch", fake_execute)

    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "Oui", send=send)
    assert calls and calls[0][0]["act"] == "play_vod"
    assert "✅" in send.last

    await db_session.refresh(ident)
    assert ident.pending_token is None


@pytest.mark.asyncio
async def test_confirm_no_cancels(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)
    ident.pending_token = sign_batch(user.id_user, org.id_org,
                                     [{"act": "play_vod", "params": {}}])
    ident.pending_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    async def fake_execute(*_a):  # ne doit PAS être appelé
        raise AssertionError("execute_batch appelé après un NON")

    monkeypatch.setattr(mg, "execute_batch", fake_execute)

    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "non", send=send)
    assert "annule" in send.last.lower()

    await db_session.refresh(ident)
    assert ident.pending_token is None


# ── UI settings : /status + déliaison self ────────────────────────────────────


@pytest.mark.asyncio
async def test_status_lists_own_identities(client: AsyncClient, db_session, org, user,
                                           monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", "t")

    import app.api.v1.endpoints.messaging as ep

    async def fake_botname():
        return "ExampleSignageBot"

    monkeypatch.setattr(ep, "get_bot_username", fake_botname)
    ident = await _linked_identity(db_session, org, user)

    token = create_access_token(user.id_user)
    resp = await client.get("/api/v1/messaging/status",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["bot_username"] == "ExampleSignageBot"
    assert [i["id_identity"] for i in data["identities"]] == [ident.id_identity]


@pytest.mark.asyncio
async def test_status_unconfigured(client: AsyncClient, user, monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", None)
    token = create_access_token(user.id_user)
    resp = await client.get("/api/v1/messaging/status",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "bot_username": None, "identities": [],
                           "pin_set": False}


@pytest.mark.asyncio
async def test_delete_own_identity_only(client: AsyncClient, db_session, org, user):
    ident = await _linked_identity(db_session, org, user)
    other = CmsUser(id_org=org.id_org, email=f"msg-{uuid.uuid4().hex[:8]}@t.com",
                    password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(other)
    await db_session.commit()
    other_ident = await _linked_identity(db_session, org, other)

    token = create_access_token(user.id_user)
    headers = {"Authorization": f"Bearer {token}"}

    # L'identité d'un autre utilisateur = 404 (et reste en base).
    resp = await client.delete(f"/api/v1/messaging/identities/me/{other_ident.id_identity}",
                               headers=headers)
    assert resp.status_code == 404

    # Sa propre identité = déliée.
    resp = await client.delete(f"/api/v1/messaging/identities/me/{ident.id_identity}",
                               headers=headers)
    assert resp.status_code == 200
    remaining = (await db_session.execute(select(CmsMessagingIdentity).where(
        CmsMessagingIdentity.id_org == org.id_org))).scalars().all()
    assert [i.id_identity for i in remaining] == [other_ident.id_identity]


@pytest.mark.asyncio
async def test_expired_pending_rejected(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)
    ident.pending_token = sign_batch(user.id_user, org.id_org,
                                     [{"act": "play_vod", "params": {}}])
    ident.pending_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send)
    assert "expiré" in send.last or "expired" in send.last

    await db_session.refresh(ident)
    assert ident.pending_token is None


# ── PIN actions sensibles (migr 0090 — 6 chiffres, 1 action, 2 min, 3 essais) ──


async def _sensitive_pending(db, org, user, act="reboot_player"):
    ident = await _linked_identity(db, org, user)
    ident.pending_token = sign_batch(user.id_user, org.id_org,
                                     [{"act": act, "params": {"id_player": 1}}])
    ident.pending_summary = ["Redémarrer le player"]
    ident.pending_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db.commit()
    return ident


@pytest.mark.asyncio
async def test_pin_endpoints_and_status(client: AsyncClient, db_session, user, monkeypatch):
    monkeypatch.setattr(settings, "CMS_TELEGRAM_BOT_TOKEN", None)
    token = create_access_token(user.id_user)
    headers = {"Authorization": f"Bearer {token}"}

    # 5 chiffres / lettres = 422 ; 6 chiffres = OK.
    resp = await client.post("/api/v1/messaging/pin", json={"pin": "12345"}, headers=headers)
    assert resp.status_code == 422
    resp = await client.post("/api/v1/messaging/pin", json={"pin": "abc123"}, headers=headers)
    assert resp.status_code == 422
    resp = await client.post("/api/v1/messaging/pin", json={"pin": "654321"}, headers=headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/messaging/status", headers=headers)
    assert resp.json()["pin_set"] is True

    resp = await client.delete("/api/v1/messaging/pin", headers=headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/messaging/status", headers=headers)
    assert resp.json()["pin_set"] is False


@pytest.mark.asyncio
async def test_sensitive_yes_asks_pin_then_executes(db_session, org, user, monkeypatch):
    """OUI sur une action sensible → demande de PIN (pas d'exécution) ; code correct
    → exécution ; le message contenant le PIN est supprimé du fil (delete appelé)."""
    user.assistant_pin_hash = hash_password("654321")
    ident = await _sensitive_pending(db_session, org, user)

    calls, deleted = [], []

    async def fake_execute(_db, _user, steps):
        calls.append(steps)
        return {"ok": True, "message": "Reboot lancé."}

    async def fake_delete():
        deleted.append(True)

    monkeypatch.setattr(mg, "execute_batch", fake_execute)

    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send, delete=fake_delete)
    assert "PIN" in send.last
    assert not calls  # pas d'exécution sans le code
    await db_session.refresh(ident)
    assert ident.pending_stage == "pin"
    assert ident.pending_token is not None

    # Texte quelconque pendant l'attente = rappel, pas d'exécution.
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "c'est quoi déjà ?", send=send, delete=fake_delete)
    assert "PIN" in send.last and not calls

    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "654321", send=send, delete=fake_delete)
    assert calls and calls[0][0]["act"] == "reboot_player"
    assert "✅" in send.last
    assert deleted  # hygiène : le message du PIN a été supprimé
    await db_session.refresh(ident)
    assert ident.pending_token is None
    assert ident.pending_stage == "confirm"


@pytest.mark.asyncio
async def test_sensitive_yes_without_pin_refused(db_session, org, user, monkeypatch):
    ident = await _sensitive_pending(db_session, org, user)

    async def fake_execute(*_a):
        raise AssertionError("exécuté sans PIN configuré")

    monkeypatch.setattr(mg, "execute_batch", fake_execute)
    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send)
    assert "profil" in send.last.lower() or "profile" in send.last.lower()
    await db_session.refresh(ident)
    assert ident.pending_token is None


@pytest.mark.asyncio
async def test_pin_three_wrong_attempts_lock(db_session, org, user, monkeypatch):
    user.assistant_pin_hash = hash_password("654321")
    ident = await _sensitive_pending(db_session, org, user)

    async def fake_execute(*_a):
        raise AssertionError("exécuté avec un PIN faux")

    monkeypatch.setattr(mg, "execute_batch", fake_execute)
    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send)
    for _ in range(2):
        await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                                 "111111", send=send)
        assert "essai" in send.last or "attempt" in send.last
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "111111", send=send)
    assert "verrouillé" in send.last or "locked" in send.last
    await db_session.refresh(ident)
    assert ident.pending_token is None
    assert ident.pin_locked_until is not None

    # Verrou actif : un nouveau OUI sensible est refusé direct.
    ident2 = await _sensitive_pending(db_session, org, user)
    # même identité rechargée : _sensitive_pending crée une NOUVELLE identité — re-poser
    # la proposition sur l'identité verrouillée à la place.
    ident.pending_token = ident2.pending_token
    ident.pending_summary = ident2.pending_summary
    ident.pending_expires_at = ident2.pending_expires_at
    await db_session.commit()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send)
    assert "verrouillé" in send.last or "locked" in send.last


@pytest.mark.asyncio
async def test_pin_stage_expiry(db_session, org, user, monkeypatch):
    user.assistant_pin_hash = hash_password("654321")
    ident = await _sensitive_pending(db_session, org, user)
    ident.pending_stage = "pin"
    ident.pending_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    async def fake_execute(*_a):
        raise AssertionError("exécuté après expiration du PIN")

    monkeypatch.setattr(mg, "execute_batch", fake_execute)
    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "654321", send=send)
    assert "expiré" in send.last or "expired" in send.last
    await db_session.refresh(ident)
    assert ident.pending_token is None


# ── Vocal (STT fal Whisper + TTS ElevenLabs, strict BYOK) ─────────────────────


def _voice_update(external_id: str, duration: int = 5) -> dict:
    return {"message": {
        "message_id": 42,
        "chat": {"id": external_id},
        "from": {"id": external_id, "first_name": "Ed"},
        "voice": {"file_id": "F1", "duration": duration, "mime_type": "audio/ogg"},
    }}


@pytest.mark.asyncio
async def test_voice_without_fal_key_unavailable(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)

    async def no_key(*_a, **_k):
        return None

    async def fail_download(*_a, **_k):  # ne doit PAS être appelé sans clé
        raise AssertionError("téléchargement sans clé fal")

    monkeypatch.setattr(mg, "resolve_ai_credentials", no_key)
    monkeypatch.setattr(mv, "download_telegram_voice", fail_download)
    send = _SendSpy()
    monkeypatch.setattr(mg, "send_telegram", send)
    await mg.process_telegram_update(_voice_update(ident.external_user_id))
    assert "fal.ai" in send.last


@pytest.mark.asyncio
async def test_voice_transcribes_echoes_and_speaks(db_session, org, user, monkeypatch):
    """Voix → STT → écho « 🎤 » → tour d'agent normal → réponse texte + note vocale."""
    ident = await _linked_identity(db_session, org, user)

    async def fake_keys(_db, _org, provider):
        return ResolvedKey(api_key=f"k-{provider}", byok=True, source="org")

    async def fake_download(_file_id):
        return b"OGGDATA"

    async def fake_stt(_audio, key, _mime="audio/ogg", language=None):
        assert key == "k-fal"
        # Hint de langue = locale du profil (fixture user : locale="fr").
        assert language == "fr"
        return "quels players sont en ligne ?"

    async def fake_resolve(_db, _user, _roles):
        return None, False, False

    async def fake_agent(_db, **kw):
        kw["usage_out"]["total"] = 10
        yield " 3 players sont en ligne."

    voices: list[bytes] = []

    async def fake_send_voice(_chat, audio, mime="audio/mpeg"):
        voices.append(audio)

    def fake_tts(*, text, api_key):
        assert api_key == "k-elevenlabs" and "3 players" in text
        return b"MP3", "audio/mpeg", 0.01

    import app.services.generation.elevenlabs as el

    monkeypatch.setattr(mg, "resolve_ai_credentials", fake_keys)
    monkeypatch.setattr(mv, "download_telegram_voice", fake_download)
    monkeypatch.setattr(mv, "transcribe_voice", fake_stt)
    monkeypatch.setattr(mv, "send_telegram_voice", fake_send_voice)
    monkeypatch.setattr(el, "generate_voice", fake_tts)
    monkeypatch.setattr(mg, "_resolve_ai_context", fake_resolve)
    monkeypatch.setattr(mg, "run_agent", fake_agent)
    send = _SendSpy()
    monkeypatch.setattr(mg, "send_telegram", send)

    await mg.process_telegram_update(_voice_update(ident.external_user_id))
    texts = [m for _c, m in send.sent]
    assert any(m.startswith("🎤") and "quels players" in m for m in texts)
    assert any("3 players sont en ligne" in m for m in texts)
    assert voices == [b"MP3"]


@pytest.mark.asyncio
async def test_voice_refused_while_awaiting_pin(db_session, org, user, monkeypatch):
    """Le PIN ne se dit jamais à la voix : en attente de code, le vocal est refusé
    AVANT tout téléchargement/transcription."""
    user.assistant_pin_hash = hash_password("654321")
    ident = await _sensitive_pending(db_session, org, user)
    ident.pending_stage = "pin"
    await db_session.commit()

    async def fail_download(*_a, **_k):
        raise AssertionError("le vocal ne doit rien télécharger en attente de PIN")

    monkeypatch.setattr(mv, "download_telegram_voice", fail_download)
    send = _SendSpy()
    monkeypatch.setattr(mg, "send_telegram", send)
    await mg.process_telegram_update(_voice_update(ident.external_user_id))
    assert "clavier" in send.last or "typed" in send.last


@pytest.mark.asyncio
async def test_voice_too_long_rejected(db_session, org, user, monkeypatch):
    ident = await _linked_identity(db_session, org, user)

    async def fake_keys(_db, _org, provider):
        return ResolvedKey(api_key=f"k-{provider}", byok=True, source="org")

    monkeypatch.setattr(mg, "resolve_ai_credentials", fake_keys)
    send = _SendSpy()
    monkeypatch.setattr(mg, "send_telegram", send)
    await mg.process_telegram_update(_voice_update(ident.external_user_id, duration=300))
    assert "2 minutes" in send.last


def test_whisper_language_normalizes_locale():
    assert mv.whisper_language("fr") == "fr"
    assert mv.whisper_language("pt-BR") == "pt"
    assert mv.whisper_language("EN") == "en"
    assert mv.whisper_language("") is None
    assert mv.whisper_language(None) is None
    assert mv.whisper_language("1x") is None


def test_tts_text_cleanup_and_cap():
    assert mv.tts_text(["✅ C'est fait. Reboot lancé."]) == "C'est fait. Reboot lancé."
    assert mv.tts_text(["voir https://example.com/x ok"]) == "voir ok"
    assert mv.tts_text(["x" * 2000]) is None  # au-delà du cap → texte seul
    assert mv.tts_text([]) is None


@pytest.mark.asyncio
async def test_non_sensitive_yes_skips_pin(db_session, org, user, monkeypatch):
    """Une action NON sensible s'exécute sur le OUI comme avant, même sans PIN."""
    ident = await _linked_identity(db_session, org, user)
    ident.pending_token = sign_batch(user.id_user, org.id_org,
                                     [{"act": "play_vod", "params": {}}])
    ident.pending_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    calls = []

    async def fake_execute(_db, _user, steps):
        calls.append(steps)
        return {"ok": True, "message": "OK."}

    monkeypatch.setattr(mg, "execute_batch", fake_execute)
    send = _SendSpy()
    await mg._handle_message("telegram", ident.external_user_id, ident.chat_id, "Ed",
                             "oui", send=send)
    assert calls and "✅" in send.last
