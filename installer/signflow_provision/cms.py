"""Client API CMS pour l'installeur terrain (§XXIX).

Minimal, basé sur `requests`. L'opérateur fournit l'URL du CMS + un token bearer org-admin
(scopé provisioning). Le client sait : identifier l'org, générer un payload, et vérifier
qu'un player est passé online.
"""

from __future__ import annotations

import time
from typing import Any

import requests


class CmsError(RuntimeError):
    pass


class CmsClient:
    def __init__(self, base_url: str, token: str, verify_tls: bool = True, timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.token = token
        self.verify = verify_tls
        self.timeout = timeout

    # ── HTTP ──────────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _get(self, path: str) -> Any:
        r = requests.get(self.base + path, headers=self._headers(),
                         verify=self.verify, timeout=self.timeout)
        if r.status_code == 401:
            raise CmsError("Authentification CMS refusée (token invalide/expiré).")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> Any:
        r = requests.post(self.base + path, json=body, headers=self._headers(),
                          verify=self.verify, timeout=self.timeout)
        if r.status_code == 401:
            raise CmsError("Authentification CMS refusée (token invalide/expiré).")
        if r.status_code >= 400:
            raise CmsError(f"{r.status_code} {path} — {r.text[:200]}")
        return r.json()

    # ── API ───────────────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        # Endpoint scopé provisioning : marche avec un JWT org-admin OU une clé opérateur sfk_.
        return self._get("/api/v1/provisioning/whoami")

    def create_payload(self, id_org: int, *, ref: str, os: str, backend_url: str,
                       network: dict | None = None, options: dict | None = None,
                       id_player: int | None = None, expires_in_days: int = 30) -> dict:
        body: dict = {"ref": ref, "os": os, "backend_url": backend_url,
                      "expires_in_days": expires_in_days}
        if network:
            body["network"] = network
        if options:
            body["options"] = options
        if id_player is not None:
            body["id_player"] = id_player
        return self._post(f"/api/v1/orgs/{id_org}/provisioning-payload", body)

    def player(self, id_player: int) -> dict:
        # Endpoint scopé provisioning (statut seul), utilisable par la clé opérateur.
        return self._get(f"/api/v1/provisioning/players/{id_player}/status")

    def wait_online(self, id_player: int, *, timeout_s: int = 180, poll_s: int = 5,
                    on_tick=None) -> bool:
        """Poll le statut du player jusqu'à `online` (ou timeout). Renvoie True si online."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                st = self.player(id_player).get("status")
            except Exception:
                st = None
            if on_tick:
                on_tick(st)
            if st == "online":
                return True
            time.sleep(poll_s)
        return False
