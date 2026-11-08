"""Cloche « MAJ serveur disponible » — service de comparaison + endpoint protégé.

Le service est testé en unitaire (aucune DB) sur tous les cas ; l'endpoint
/meta/update est simplement vérifié PROTÉGÉ (contrairement à /meta qui est public).
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import update_check
from app.services.update_check import check_for_update, parse_version


# ── parse_version ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.0.5", (1, 0, 5)),
        ("2.13.0", (2, 13, 0)),
        ("dev", None),
        ("", None),
        (None, None),
        ("1.0", None),
        ("1.0.5-beta", None),
        ("v1.0.5", None),
    ],
)
def test_parse_version(value, expected) -> None:
    assert parse_version(value) == expected


def _manifest(monkeypatch, manifest):
    async def _fake():
        return manifest

    monkeypatch.setattr(update_check, "_fetch_manifest", _fake)


# ── check_for_update ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bell_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", False)
    out = await check_for_update("1.0.4")
    assert out == {"enabled": False, "current": "1.0.4", "update_available": False}


@pytest.mark.asyncio
async def test_source_build_is_silent(monkeypatch) -> None:
    # Un build source ("dev") n'a pas de version comparable → jamais de cloche,
    # même manifeste présent. C'est ce qui garde la prod SaaS muette.
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(monkeypatch, {"latest": "1.0.5", "releases": [{"version": "1.0.5"}]})
    out = await check_for_update("dev")
    assert out["enabled"] is True
    assert out["update_available"] is False


@pytest.mark.asyncio
async def test_manifest_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(monkeypatch, None)
    out = await check_for_update("1.0.4")
    assert out["update_available"] is False


@pytest.mark.asyncio
async def test_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(monkeypatch, {"latest": "1.0.5", "releases": [{"version": "1.0.5"}]})
    out = await check_for_update("1.0.5")
    assert out["update_available"] is False
    assert out["latest"] == "1.0.5"


@pytest.mark.asyncio
async def test_update_available_with_security_and_notes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(
        monkeypatch,
        {
            "latest": "1.0.5",
            "releases": [
                {
                    "version": "1.0.5",
                    "date": "2026-07-20",
                    "security": True,
                    "notes": {"en": "Security fix.", "fr": "Correctif de sécurité."},
                },
                {"version": "1.0.4", "date": "2026-07-19", "notes": {"en": "UI."}},
                {"version": "1.0.3", "date": "2026-07-18"},  # ancienne, ignorée
            ],
        },
    )
    out = await check_for_update("1.0.3", locale="fr")
    assert out["update_available"] is True
    assert out["latest"] == "1.0.5"
    assert out["security"] is True
    # Seules les versions > 1.0.3, plus récente d'abord.
    versions = [r["version"] for r in out["releases"]]
    assert versions == ["1.0.5", "1.0.4"]
    # Notes localisées (fr demandé).
    assert out["releases"][0]["notes"] == "Correctif de sécurité."
    # Repli sur en quand la locale manque.
    assert out["releases"][1]["notes"] == "UI."


@pytest.mark.asyncio
async def test_latest_only_fallback(monkeypatch) -> None:
    # Manifeste réduit à {"latest": ...} sans liste de releases.
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(monkeypatch, {"latest": "1.0.6"})
    out = await check_for_update("1.0.4")
    assert out["update_available"] is True
    assert out["latest"] == "1.0.6"
    assert out["security"] is False


@pytest.mark.asyncio
async def test_no_security_flag_when_none_flagged(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(
        monkeypatch,
        {"latest": "1.0.5", "releases": [{"version": "1.0.5", "notes": {"en": "x"}}]},
    )
    out = await check_for_update("1.0.4")
    assert out["security"] is False


@pytest.mark.asyncio
async def test_canary_and_pending_are_ignored(monkeypatch) -> None:
    # Cœur de la barrière 2 : une version en cours de validation (canary/pending)
    # ne doit JAMAIS déclencher la cloche d'un client. Le bell ne lit que
    # latest + releases[] → un serveur déjà à `latest` reste muet même si un
    # canary plus récent existe. C'est ce qui garantit qu'un client ne voit que
    # des versions promues (donc validées sur un vrai serveur).
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_BELL", True)
    _manifest(
        monkeypatch,
        {
            "latest": "1.0.13",
            "canary": "1.0.14",
            "pending": [
                {
                    "version": "1.0.14",
                    "date": "2026-07-25",
                    "security": True,
                    "notes": {"en": "Canary — not yet promoted."},
                }
            ],
            "releases": [{"version": "1.0.13", "notes": {"en": "x"}}],
        },
    )
    out = await check_for_update("1.0.13")
    assert out["update_available"] is False
    assert out["latest"] == "1.0.13"
    # Une fois promue (pending -> releases, canary -> latest), la cloche sonne.
    _manifest(
        monkeypatch,
        {
            "latest": "1.0.14",
            "canary": None,
            "pending": [],
            "releases": [
                {"version": "1.0.14", "date": "2026-07-25", "security": True,
                 "notes": {"en": "Promoted."}},
                {"version": "1.0.13", "notes": {"en": "x"}},
            ],
        },
    )
    out = await check_for_update("1.0.13")
    assert out["update_available"] is True
    assert out["latest"] == "1.0.14"
    assert out["security"] is True


# ── Cache du manifeste (cadence + requête conditionnelle) ────────────────────
def _reset_cache() -> None:
    update_check._cache.update({"at": 0.0, "manifest": None, "etag": None})


def test_cache_ttl_is_15_minutes() -> None:
    # Garde anti-dérive : un correctif de sécurité promu doit être annoncé en
    # ≤ 15 min. L'ancien TTL de 6 h a été vécu comme « cloche muette » (1.0.18).
    # Si quelqu'un rallonge ce TTL, ce test le lui fait dire explicitement.
    assert update_check._CACHE_TTL_SECONDS == 15 * 60


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, etag: str | None = None):
        self.status_code = status_code
        self._json = json_data
        self.headers = {"etag": etag} if etag else {}

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Remplace httpx.AsyncClient : rejoue une liste de réponses préparées et
    enregistre les en-têtes envoyés (pour prouver le If-None-Match)."""

    responses: list[_FakeResponse] = []
    seen_headers: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        _FakeClient.seen_headers.append(dict(headers or {}))
        return _FakeClient.responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_stores_etag_then_sends_if_none_match(monkeypatch) -> None:
    _reset_cache()
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_MANIFEST_URL", "https://example.invalid/versions.json")
    monkeypatch.setattr(update_check.httpx, "AsyncClient", _FakeClient)
    _FakeClient.seen_headers = []

    # 1er passage : 200 + ETag → manifeste et etag mis en cache.
    _FakeClient.responses = [_FakeResponse(200, {"latest": "1.0.22"}, etag='W/"abc"')]
    out = await update_check._fetch_manifest()
    assert out == {"latest": "1.0.22"}
    assert update_check._cache["etag"] == 'W/"abc"'
    assert "If-None-Match" not in _FakeClient.seen_headers[0]

    # TTL expiré : la sonde suivante est CONDITIONNELLE, et un 304 (sans corps)
    # conserve le manifeste en cache tout en rafraîchissant l'horodatage.
    # Horodatage RELATIF : `time.monotonic()` part de ~0 au démarrage de la machine, donc
    # « 0.0 » ne valait « expiré » que sur un hôte allumé depuis plus de 15 min.
    update_check._cache["at"] = update_check.time.monotonic() - update_check._CACHE_TTL_SECONDS - 1
    _FakeClient.responses = [_FakeResponse(304)]
    out = await update_check._fetch_manifest()
    assert out == {"latest": "1.0.22"}
    assert _FakeClient.seen_headers[1].get("If-None-Match") == 'W/"abc"'
    assert update_check._cache["at"] > update_check.time.monotonic() - 5


@pytest.mark.asyncio
async def test_fetch_within_ttl_does_not_hit_network(monkeypatch) -> None:
    _reset_cache()
    monkeypatch.setattr(settings, "SIGNFLOW_UPDATE_MANIFEST_URL", "https://example.invalid/versions.json")
    monkeypatch.setattr(update_check.httpx, "AsyncClient", _FakeClient)
    _FakeClient.seen_headers = []
    _FakeClient.responses = [_FakeResponse(200, {"latest": "1.0.22"}, etag='W/"abc"')]
    await update_check._fetch_manifest()

    # Cache frais : aucune réponse préparée — un accès réseau ferait IndexError.
    out = await update_check._fetch_manifest()
    assert out == {"latest": "1.0.22"}
    assert len(_FakeClient.seen_headers) == 1


# ── Endpoint protégé ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_update_endpoint_requires_auth(client: AsyncClient) -> None:
    # /meta est public ; /meta/update ne l'est pas (org-admin only).
    resp = await client.get("/api/v1/meta/update")
    assert resp.status_code in (401, 403)
