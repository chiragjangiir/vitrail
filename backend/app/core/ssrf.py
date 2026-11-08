"""Garde anti-SSRF partagée (§25.6).

Centralise la logique anti-SSRF (historiquement `feed_worker._host_is_safe`, appliquée
seulement aux vignettes/YouTube) pour la réutiliser sur TOUS les fetch influencés par
l'utilisateur : import stock, téléchargement de feed, capture d'écran d'URL Display.

`host_is_safe` résout l'hôte et refuse toute IP privée/loopback/lien-local/réservée
(bloque metadata cloud 169.254.169.254, services internes Docker minio/litellm/redis,
localhost…). `url_is_safe` y ajoute la validation du schéma et, optionnellement, une
liste blanche de suffixes d'hôtes (ex. n'autoriser que *.unsplash.com).

⚠️ Limite connue (TOCTOU / DNS rebinding) : la résolution faite ici peut différer de
celle effectuée par le client HTTP au moment de la connexion. On atténue en DÉSACTIVANT
les redirections côté appelant (un 3xx vers une IP interne ne serait pas re-validé).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def host_is_safe(host: str) -> bool:
    """False si l'hôte résout (même partiellement) vers une IP non publique."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


def url_is_safe(
    url: str,
    *,
    schemes: tuple[str, ...] = ("http", "https"),
    allowed_host_suffixes: tuple[str, ...] | None = None,
) -> bool:
    """Valide schéma + (option) liste blanche de domaines + sûreté IP de l'hôte."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in schemes or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if allowed_host_suffixes is not None:
        if not any(host == s or host.endswith("." + s) for s in allowed_host_suffixes):
            return False
    return host_is_safe(host)
