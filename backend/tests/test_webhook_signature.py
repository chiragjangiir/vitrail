"""Webhooks signés + réessai — P1.7 (2026-08-05).

Le canal webhook postait un JSON nu : rien ne permettait au destinataire de distinguer une
alerte SignFlow d'un appel fabriqué par quiconque connaît l'URL — et une URL n'est pas un
secret, elle traîne dans les journaux, les tickets et les captures d'écran.

Ce que ce fichier verrouille, dans l'ordre d'importance :

  1. ce qui est signé est **exactement ce qui part sur le réseau** (l'erreur classique est
     de signer une re-sérialisation, dont le destinataire ne peut pas retrouver les octets) ;
  2. l'horodatage entre dans l'empreinte, donc un enregistrement capturé ne se rejoue pas
     indéfiniment ;
  3. changer l'URL d'un canal **ne régénère pas son secret** — sinon le destinataire
     rejetterait toutes les alertes suivantes comme des faux, sans que personne ne comprenne ;
  4. on ne réessaie que ce qui a une chance d'aboutir : un 404 ne deviendra jamais un 200,
     et le renvoyer quatre fois ne fait que masquer une erreur de configuration.
"""

import json
import time

import pytest

from app.api.v1.endpoints.notifications import _validated_config
from app.services import notifications
from app.services.webhook_signature import (
    HEADER_ATTEMPT,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    headers_for,
    new_secret,
    verify,
)


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


@pytest.fixture
def captured(monkeypatch):
    """Intercepte l'appel HTTP et garde les OCTETS réellement transmis."""
    seen: dict = {}

    def fake_post(url, content=None, headers=None, timeout=None, **kw):
        seen.update(url=url, content=content, headers=headers or {})
        return _Resp(seen.pop("_status", 200) if "_status" in seen else 200)

    monkeypatch.setattr(notifications.httpx, "post", fake_post)
    return seen


# ── ① Signer ce qu'on envoie, pas une reconstruction ───────────────────────────────

def test_the_signature_covers_the_exact_bytes_that_are_sent(captured):
    secret = new_secret()
    ok, detail, retry = notifications.webhook_post(
        "https://example.test/hook", {"event": "test", "n": 1}, secret=secret,
        event_type="test")

    assert ok and not retry
    raw = captured["content"]
    assert isinstance(raw, bytes), "le corps doit partir en octets (content=), jamais json="
    # La vérification de référence — celle qu'on publie — accepte cet envoi.
    assert verify(secret, captured["headers"], raw)
    # Et c'est bien un JSON exploitable, pas seulement une suite d'octets signés.
    assert json.loads(raw.decode())["event"] == "test"


def test_a_tampered_body_or_a_wrong_secret_is_refused(captured):
    secret = new_secret()
    notifications.webhook_post("https://example.test/hook", {"event": "test"},
                               secret=secret, event_type="test")
    raw, headers = captured["content"], captured["headers"]

    assert verify(secret, headers, raw)
    assert not verify(secret, headers, raw + b" "), "corps modifié : doit être refusé"
    assert not verify(new_secret(), headers, raw), "autre secret : doit être refusé"


def test_an_old_capture_cannot_be_replayed_forever():
    """L'horodatage est DANS l'empreinte : le déplacer invalide la signature, et le laisser
    tel quel fait sortir l'appel de la fenêtre de tolérance."""
    secret, raw = new_secret(), b'{"event":"test"}'
    old = headers_for(secret, raw, "test", timestamp=int(time.time()) - 3600)

    assert not verify(secret, old, raw), "un envoi vieux d'une heure doit être refusé"
    # Le rejeu « rafraîchi » ne marche pas non plus : l'horodatage est signé.
    forged = dict(old)
    forged[HEADER_TIMESTAMP] = str(int(time.time()))
    assert not verify(secret, forged, raw)


def test_a_channel_without_secret_still_works_unsigned(captured):
    """Rétro-compatibilité : les canaux créés avant P1.7 n'ont pas de secret. Cesser
    d'émettre pour eux transformerait un durcissement en panne d'alertes."""
    ok, _, _ = notifications.webhook_post("https://example.test/hook", {"event": "test"})
    assert ok
    assert HEADER_SIGNATURE not in captured["headers"]
    assert HEADER_TIMESTAMP not in captured["headers"]


def test_the_attempt_number_travels_so_the_receiver_can_deduplicate(captured):
    notifications.webhook_post("https://example.test/hook", {"event": "test"},
                               secret=new_secret(), event_type="test", attempt=3)
    assert captured["headers"][HEADER_ATTEMPT] == "3"


# ── ② Réessayer ce qui peut aboutir, et rien d'autre ───────────────────────────────

@pytest.mark.parametrize(
    "status_code, expected",
    [(500, True), (502, True), (503, True), (429, True), (408, True),
     (400, False), (401, False), (403, False), (404, False), (422, False)],
)
def test_only_transient_failures_are_worth_retrying(monkeypatch, status_code, expected):
    monkeypatch.setattr(notifications.httpx, "post",
                        lambda *a, **k: _Resp(status_code))
    ok, _, retryable = notifications.webhook_post("https://example.test/h", {"event": "t"})
    assert not ok
    assert retryable is expected, (
        f"HTTP {status_code} : un 4xx ne deviendra pas un 2xx en le renvoyant ; "
        "un 5xx/429/408, si"
    )


def test_no_response_at_all_is_retryable(monkeypatch):
    """Réseau coupé, DNS muet, délai dépassé : c'est le cas que le réessai sert."""
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(notifications.httpx, "post", boom)
    ok, detail, retryable = notifications.webhook_post("https://example.test/h", {"event": "t"})
    assert (ok, retryable) == (False, True)
    assert "connection refused" in detail


def test_the_retry_chain_stops_instead_of_hammering(monkeypatch):
    """Le worker rejoue, puis ABANDONNE. Une boucle sans fin sur un serveur en panne est
    une attaque par déni de service qu'on s'infligerait à soi-même."""
    from app.workers import notification_worker as w

    requeued: list[int] = []
    monkeypatch.setattr(w, "webhook_post", lambda *a, **k: (False, "HTTP 503", True))
    monkeypatch.setattr(w, "_log", lambda *a, **k: None)
    monkeypatch.setattr(w.celery_app, "send_task",
                        lambda name, args=None, **k: requeued.append(args[-1]))

    # Une tentative intermédiaire re-programme la suivante…
    out = w.retry_webhook("https://e.test/h", {"event": "t"}, "s", "t", 1, None, 2)
    assert out["requeued"] is True and requeued == [3]

    # …la dernière ne re-programme plus rien.
    requeued.clear()
    out = w.retry_webhook("https://e.test/h", {"event": "t"}, "s", "t", 1, None, w.MAX_ATTEMPTS)
    assert out.get("requeued") is None and requeued == []


def test_a_definitive_failure_is_not_requeued(monkeypatch):
    from app.workers import notification_worker as w

    requeued: list = []
    monkeypatch.setattr(w, "webhook_post", lambda *a, **k: (False, "HTTP 404", False))
    monkeypatch.setattr(w, "_log", lambda *a, **k: None)
    monkeypatch.setattr(w.celery_app, "send_task", lambda *a, **k: requeued.append(a))

    out = w.retry_webhook("https://e.test/h", {"event": "t"}, "s", "t", 1, None, 2)
    assert out["ok"] is False and out["retryable"] is False and requeued == []


# ── ③ Le secret ne disparaît pas dans le dos de l'intégrateur ──────────────────────

def test_updating_the_url_keeps_the_secret():
    """Le défaut qu'on évite : `_validated_config` reconstruit le dictionnaire de zéro.
    Sans passer l'ancienne config, changer l'URL régénérerait le secret EN SILENCE et le
    destinataire rejetterait ensuite toutes les alertes comme des faux."""
    first = _validated_config("webhook", {"url": "https://example.com/a"})
    assert first["secret"].startswith("whsec_")

    updated = _validated_config("webhook", {"url": "https://example.com/b"}, first)
    assert updated["url"].endswith("/b")
    assert updated["secret"] == first["secret"], "le secret a changé sans qu'on le demande"


def test_the_secret_rotates_only_when_asked():
    first = _validated_config("webhook", {"url": "https://example.com/a"})
    rotated = _validated_config(
        "webhook", {"url": "https://example.com/a", "rotate_secret": True}, first)
    assert rotated["secret"] != first["secret"]
    assert rotated["secret"].startswith("whsec_")


def test_a_caller_cannot_impose_its_own_secret():
    """Un secret venu de l'extérieur est faible, réutilisé, ou déjà passé par un ticket."""
    cfg = _validated_config("webhook", {"url": "https://example.com/a", "secret": "1234"})
    assert cfg["secret"] != "1234"
    assert len(cfg["secret"]) > 30


def test_an_existing_channel_gains_a_secret_on_first_update():
    """Les canaux d'avant P1.7 n'en ont pas : ils en reçoivent un sans geste particulier."""
    legacy = {"url": "https://example.com/a"}
    cfg = _validated_config("webhook", {"url": "https://example.com/a"}, legacy)
    assert cfg["secret"].startswith("whsec_")
