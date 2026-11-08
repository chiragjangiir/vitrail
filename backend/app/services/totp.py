"""Service TOTP RFC 6238 (§2.1.1) — pyotp + qrcode."""

import base64
import io
import secrets
import string

import pyotp
import qrcode
from passlib.context import CryptContext

from app.core import crypto

_backup_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_BACKUP_CODE_LEN = 10
_BACKUP_CODE_COUNT = 10


# ── Chiffrement au repos du secret TOTP (audit 2026-06-24) ───────────────────────
# Le secret TOTP était stocké en clair. On le chiffre via le coffre Fernet (core.crypto),
# avec REPLI plaintext systématique : si le coffre est indisponible (à l'écriture) ou si la
# valeur stockée n'est pas un token Fernet (legacy en clair), on reste fonctionnel — JAMAIS
# de verrouillage d'un compte à 2FA forcée. La migration est paresseuse (cf. login).

def protect_totp_secret(secret: str) -> str:
    """Chiffre le secret TOTP si le coffre est disponible, sinon le renvoie tel quel."""
    if crypto.vault_available():
        return crypto.encrypt_secret(secret)
    return secret


def secret_is_encrypted(stored: str | None) -> bool:
    """True si `stored` est un token Fernet déchiffrable (≠ legacy en clair)."""
    if not stored:
        return False
    try:
        crypto.decrypt_secret(stored)
        return True
    except (crypto.VaultKeyMissing, crypto.VaultDecryptError):
        return False


def reveal_totp_secret(stored: str | None) -> str:
    """Renvoie le secret TOTP en clair : déchiffre si c'est un token Fernet, sinon (legacy)
    renvoie la valeur telle quelle. Tolérant à l'absence de coffre."""
    if not stored:
        return ""
    try:
        return crypto.decrypt_secret(stored)
    except (crypto.VaultKeyMissing, crypto.VaultDecryptError):
        return stored


def generate_totp_secret(user_email: str, org_name: str) -> dict:
    """Génère un secret TOTP et retourne le secret + QR code en base64."""
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(
        user_email, issuer_name=f"Vitrail – {org_name}"
    )
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return {
        "secret": secret,
        "qr_b64": base64.b64encode(buf.getvalue()).decode(),
    }


def verify_totp(secret: str, code: str) -> bool:
    """Vérifie un code TOTP avec fenêtre ±1 période (§2.1.1)."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes() -> tuple[list[str], list[str]]:
    """Retourne (codes_clairs, codes_hashés) — stocker uniquement les hashés."""
    alphabet = string.ascii_uppercase + string.digits
    plain = [
        "".join(secrets.choice(alphabet) for _ in range(_BACKUP_CODE_LEN))
        for _ in range(_BACKUP_CODE_COUNT)
    ]
    hashed = [_backup_ctx.hash(code) for code in plain]
    return plain, hashed


def verify_backup_code(code: str, hashed_codes: list[str]) -> int | None:
    """Vérifie et retourne l'index du code valide, ou None si invalide."""
    for idx, h in enumerate(hashed_codes):
        if _backup_ctx.verify(code, h):
            return idx
    return None
