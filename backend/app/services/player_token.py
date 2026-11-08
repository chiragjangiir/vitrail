"""Politique de token machine des players (« Option B », 2026-06-26).

Le token player a une durée de vie finie (`CMS_PLAYER_TOKEN_EXPIRE_DAYS`) mais l'expiration
ne coupe JAMAIS un écran : elle déclenche une *rotation*. Deux mécanismes assurent qu'aucune
saisie manuelle n'est jamais requise pour cause d'expiration :

- **Auto-refresh proactif** : `check_player_health` fait tourner le token des players *online*
  quand il reste ≤ `CMS_PLAYER_TOKEN_REFRESH_DAYS` jours, et pousse `token:refresh`.
- **Grâce-à-la-reconnexion** : un player qui était offline pendant sa fenêtre de refresh se
  reconnecte avec un token expiré → le WS l'accepte (signature valide + identité connue +
  non révoqué) et le fait tourner immédiatement.

La révocation reste assurée par la correspondance avec le token stocké (`player_token`), avec
une fenêtre de grâce (`player_token_prev` valable jusqu'à `player_token_prev_until`) pour
couvrir un push raté ou un player offline au moment de la rotation.

Ce module ne contient que des fonctions PURES : chaque appelant (WS via SQLAlchemy, worker via
psycopg2) réalise ses propres écritures, mais partage la logique de décision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import settings

# Identité du token présenté vis-à-vis du player stocké.
IDENTITY_CURRENT = "current"  # = player_token courant
IDENTITY_PREV = "prev"        # = player_token_prev, encore dans la fenêtre de grâce
IDENTITY_UNKNOWN = "unknown"  # ni l'un ni l'autre → révoqué / fuité → rejet


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def token_identity(
    presented: str,
    player_token: str | None,
    player_token_prev: str | None,
    player_token_prev_until: datetime | None,
    now: datetime,
) -> str:
    """Classe le token présenté. `player_token` NULL = player jamais provisionné → on laisse
    passer (IDENTITY_CURRENT) pour préserver le comportement historique."""
    if not player_token:
        return IDENTITY_CURRENT
    if presented == player_token:
        return IDENTITY_CURRENT
    until = _aware(player_token_prev_until)
    if player_token_prev and presented == player_token_prev and until and until > now:
        return IDENTITY_PREV
    return IDENTITY_UNKNOWN


def needs_rotation(token_expires_at: datetime | None, now: datetime) -> bool:
    """Faut-il faire tourner le token ? Vrai si :
    - expiré ou proche de l'expiration (≤ REFRESH_DAYS) ;
    - legacy (token_expires_at NULL, ou ≫ EXPIRE_DAYS → ancien token « 100 ans » à migrer)."""
    exp = _aware(token_expires_at)
    if exp is None:
        return True  # legacy / inconnu → migrer vers un token à durée finie
    days_left = (exp - now).total_seconds() / 86400
    if days_left <= settings.CMS_PLAYER_TOKEN_REFRESH_DAYS:
        return True
    # Token dont l'expiration dépasse largement la politique → ancien token permanent à migrer.
    legacy_threshold = (
        settings.CMS_PLAYER_TOKEN_EXPIRE_DAYS + settings.CMS_PLAYER_TOKEN_GRACE_DAYS + 1
    )
    return days_left > legacy_threshold


def grace_until(now: datetime) -> datetime:
    """Échéance de la fenêtre de grâce pour l'ancien token après une rotation."""
    return now + timedelta(days=settings.CMS_PLAYER_TOKEN_GRACE_DAYS)
