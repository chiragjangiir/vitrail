from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsUser(Base):
    __tablename__ = "cms_users"

    id_user: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fernet-chiffré (§XVI.1)
    totp_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # 10 codes de secours hashés bcrypt (§2.1.1)
    totp_backup_codes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"), nullable=False)
    # PIN 6 chiffres (bcrypt) — 2e facteur du « OUI » pour les actions SENSIBLES
    # demandées par messagerie (Jeanine, migr 0090). NULL = pas de PIN défini.
    assistant_pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Compteur/verrou du PIN pour les actions CMS (commandes players EN MASSE, migr 0097).
    # Distinct de l'état PAR IDENTITÉ Telegram (cms_messaging_identities) : une session CMS
    # n'a pas d'identité de messagerie. Cf. services/pin_guard.py.
    assistant_pin_attempts: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    assistant_pin_locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Borne de révocation des sessions (P1.1, migr 0122). Tout jeton utilisateur émis
    # AVANT cet instant est refusé — accès, rafraîchissement et enrôlement 2FA. NULL =
    # aucune révocation n'a jamais eu lieu ⇒ comportement inchangé (c'est l'état de tous
    # les comptes au déploiement). ⚠️ TOUJOURS la poser via
    # `session_revocation.revocation_bound()` : elle est TRONQUÉE À LA SECONDE, parce que
    # `iat` compte des secondes entières — une borne au microseconde près rendrait « plus
    # vieux qu'elle » un jeton émis dans la même seconde, et l'utilisateur repartirait en
    # boucle de reconnexion.
    sessions_valid_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Locale embarquée dans le JWT (§XXVIII)
    locale: Mapped[str] = mapped_column(String(5), server_default="en", nullable=False)
    # Préférence de thème jour/nuit (§ Thème) — light|dark, persistée cross-device
    theme: Mapped[str] = mapped_column(
        String(5), server_default="light", default="light", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    # Compte démo (§II) : navigue en lecture comme un Org Admin, toute écriture bloquée par le
    # middleware DemoGuard (message localisé), sauf auth / langue du profil / feedback.
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Portail annonceur (S7 Phase B, migr 0080) : user EXTERNE lié à UN annonceur
    # (1 user = 1 annonceur, décision Ed 2026-07-10). NULL = user retailer normal.
    # L'isolation intra-org est applicative (endpoints campagnes) : cross-annonceur = 404.
    id_advertiser: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_advertisers.id_advertiser", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsApiKey(Base):
    __tablename__ = "cms_api_keys"

    id_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_user: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scopes: Mapped[list] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    # NULL = illimité ; utilisé pour les provisioning tokens (§XXIX)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # §XXIX installeur terrain : si non NULL, le provisioning token RÉ-ATTACHE le device à ce
    # player existant (anti-doublon) au lieu d'en créer un nouveau.
    provision_target_player: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
