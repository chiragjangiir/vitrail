from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsMessagingIdentity(Base):
    """Identité messagerie « Jeanine » : compte de canal externe ↔ CmsUser (opt-in). RLS.

    Porte aussi l'état de conversation : le lot d'actions proposé (jeton signé) attend le
    « OUI » du fil — une seule proposition en attente par identité (la suivante remplace).
    """

    __tablename__ = "cms_messaging_identities"
    __table_args__ = (UniqueConstraint("channel", "external_user_id"),)

    id_identity: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    id_user: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(20), server_default="telegram", default="telegram", nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False)
    pending_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_summary: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pending_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Étape de la proposition (migr 0090) : 'confirm' = attend OUI/NON ;
    # 'pin' = OUI reçu sur une action SENSIBLE, attend le code à 6 chiffres
    # (pending_expires_at resserré à PIN_TTL_S).
    pending_stage: Mapped[str] = mapped_column(
        String(10), server_default="confirm", default="confirm", nullable=False)
    # Anti force brute du PIN : 3 essais puis verrou 15 min.
    pin_attempts: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", default=0, nullable=False)
    pin_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
