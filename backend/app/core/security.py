import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

# P2.5 — passlib 1.7.4 sonde la version de bcrypt via `bcrypt.__about__`, attribut disparu
# en bcrypt 4.1. Il ATTRAPE l'erreur (son propre message dit « trapped ») et poursuit
# normalement — le hachage fonctionne, ce n'est pas une panne — mais il en journalise la
# **trace Python complète**, au niveau WARNING.
#
# Pourquoi ça mérite d'être traité : cette trace sort à l'étape « compte administrateur »
# de l'installation client, c'est-à-dire au moment précis où l'opérateur se demande si son
# serveur s'est bien installé. Un traceback à cet endroit se lit comme un échec, et fait
# rappeler le support pour une installation parfaitement réussie.
#
# On ne coupe QUE ce bruit-là : le niveau ERROR laisse passer toute vraie erreur du même
# module. ⛔ Écarté : épingler bcrypt < 4.1 — on renoncerait aux correctifs de la
# bibliothèque qui hache les mots de passe pour faire taire un message cosmétique.
logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _issued_at() -> int:
    """Date d'émission d'un jeton, en secondes entières.

    Portée par TOUS les jetons utilisateurs depuis P1.1 : c'est elle que compare
    `services/session_revocation` à `cms_users.sessions_valid_from` pour refuser un
    jeton antérieur à une coupure de session. Un jeton SANS `iat` est traité comme
    antérieur à toute borne — donc n'en retirer aucun, sous peine de déconnecter les
    porteurs à la première révocation venue.
    """
    return int(datetime.now(timezone.utc).timestamp())


def create_access_token(subject: Any, extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.CMS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": str(subject), "exp": expire, "iat": _issued_at(), "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.CMS_JWT_SECRET, algorithm=settings.CMS_JWT_ALGORITHM)


def create_refresh_token(subject: Any) -> str:
    """⚠️ `iat` n'est pas décoratif ici : sans lui, la révocation serait DÉCORATIVE.
    Un jeton d'accès refusé déclenche un rafraîchissement automatique côté front, qui
    rendrait un jeton neuf — et la session survivrait à sa propre révocation."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.CMS_JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": str(subject), "exp": expire, "iat": _issued_at(), "type": "refresh"}
    return jwt.encode(payload, settings.CMS_JWT_SECRET, algorithm=settings.CMS_JWT_ALGORITHM)


def create_enrolment_token(subject: Any) -> str:
    """Jeton d'enrôlement 2FA — délivré par /auth/login à un compte à qui le second facteur
    est OBLIGATOIRE et qui ne l'a pas encore.

    Il est refusé par `get_current_user` : seule `get_user_for_totp_enrolment` l'accepte, et
    elle ne garde que /auth/totp/setup et /auth/totp/verify. Sans lui, un tel compte est
    **définitivement** hors de l'application — la connexion répond 403, et l'enrôlement exige
    un jeton d'accès que ce 403 empêche justement d'obtenir. C'est exactement ce trou qu'il
    bouche, et rien d'autre : il n'est émis qu'APRÈS vérification du mot de passe, donc il
    n'accorde rien que le mot de passe n'accordait déjà.

    ⚠️ Ne pas élargir sa portée. Un jeton d'enrôlement qui ouvrirait une autre surface
    rendrait la 2FA obligatoire contournable par quiconque détient le mot de passe.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.CMS_JWT_ENROLMENT_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(subject), "exp": expire, "iat": _issued_at(), "type": "totp_enrolment"
    }
    return jwt.encode(payload, settings.CMS_JWT_SECRET, algorithm=settings.CMS_JWT_ALGORITHM)


def decode_token(token: str, verify_exp: bool = True) -> dict:
    # verify_exp=False : réservé aux tokens machine des players (type=player), qui sont
    # des identifiants de device longue durée. La révocation se fait par correspondance
    # du token stocké (player.player_token), pas par expiration — cf. get_current_player
    # et ws_player. Les tokens utilisateurs gardent la vérification d'expiration (défaut).
    return jwt.decode(
        token,
        settings.CMS_JWT_SECRET,
        algorithms=[settings.CMS_JWT_ALGORITHM],
        options={"verify_exp": verify_exp},
    )


def create_player_token(id_player: int) -> tuple[str, datetime]:
    # Token machine de player = identifiant de device à durée FINIE (politique « Option B »
    # décidée 2026-06-26). L'expiration ne coupe jamais un écran : elle déclenche une rotation
    # (auto-refresh des players online + grâce-à-la-reconnexion sur le WS). La révocation
    # reste assurée par la correspondance avec le token stocké (player_token).
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.CMS_PLAYER_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(id_player), "exp": expires_at, "iat": now, "type": "player"}
    token = jwt.encode(payload, settings.CMS_JWT_SECRET, algorithm=settings.CMS_JWT_ALGORITHM)
    return token, expires_at
