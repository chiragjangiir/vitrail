"""
Proof of Play — crypto de preuve (§XXIV).

- P2 signature : chaque preuve est signée Ed25519 par la clé device du player. Le serveur
  reconstruit le MÊME message canonique et vérifie contre la clé publique enregistrée.
- P1 vérification / export : `merkle_root` agrège les hashes d'une période en une racine
  compacte vérifiable (arbre binaire) pour l'attestation certifiée.

Le message canonique signé doit être identique côté player et serveur. On utilise des entiers
robustes au formatage : `played_at` en millisecondes epoch (et non l'ISO, sensible au format).
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


def played_at_ms(dt: datetime) -> int:
    """Millisecondes epoch de played_at — base canonique commune player/serveur."""
    return int(dt.timestamp() * 1000)


def canonical_message(
    id_player: int, id_media: int | None, id_playlist: int | None,
    played_at_ms_val: int, duration_ms: int,
) -> bytes:
    """Message signé par le player (champs joints par '|', null = champ vide)."""
    return (
        f"{id_player}|{id_media if id_media is not None else ''}|"
        f"{id_playlist if id_playlist is not None else ''}|{played_at_ms_val}|{duration_ms}"
    ).encode()


def chain_hash(
    prev: str, id_player: int, id_media: int | None, played_at_iso: str, duration_ms: int,
) -> str:
    """Maillon de la chaîne de hachage anti-altération d'un player. Doit être identique
    partout (ingestion, /pop/verify, rapport PDF, archivage) : played_at en ISO UTC."""
    data = f"{prev}:{id_player}:{id_media or ''}:{played_at_iso}:{duration_ms}"
    return hashlib.sha256(data.encode()).hexdigest()


def verify_signature(public_key_pem: str, signature_b64: str, message: bytes) -> bool:
    """Vérifie une signature Ed25519 (base64) contre la clé publique PEM. False si invalide."""
    import base64
    try:
        pub = load_pem_public_key(public_key_pem.encode())
        if not isinstance(pub, Ed25519PublicKey):
            return False
        pub.verify(base64.b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def merkle_root(hashes: list[str]) -> str | None:
    """Racine de Merkle (arbre binaire sha256) d'une liste de hashes hex ordonnés.

    Permet d'attester en UN hash l'intégrité de toutes les preuves d'une période. Renvoie None
    si la liste est vide. Le dernier nœud impair est dupliqué (convention Bitcoin-like)."""
    if not hashes:
        return None
    level = [
        bytes.fromhex(h) if len(h) == 64 else hashlib.sha256(h.encode()).digest()
        for h in hashes
    ]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()
