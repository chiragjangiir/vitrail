"""Endpoint public /api/v1/meta — version de la release servie par le serveur."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_meta_is_public_and_returns_version(client: AsyncClient) -> None:
    # Non authentifié : la page de login l'affiche avant toute connexion.
    resp = await client.get("/api/v1/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    # Défaut "dev" en test (aucun SIGNFLOW_VERSION injecté) — non vide dans tous les cas.
    assert isinstance(body["version"], str) and body["version"]

