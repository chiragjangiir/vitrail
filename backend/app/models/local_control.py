from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsLocalControlProfile(Base):
    """Profil d'accès au Store Control Panel LAN d'un player (§19.3).

    Le CMS génère un profil (token + permissions + expiration) ; le token est
    encodé dans un QR code. Le serveur HTTP embarqué du player valide ce token
    et ouvre une session locale. Le token est en clair (faible sensibilité :
    scopé à 1 player, expirable, révocable).
    """

    __tablename__ = "cms_local_control_profiles"

    id_profile: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_player: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), server_default="CMS_STORE_OPERATOR", default="CMS_STORE_OPERATOR", nullable=False
    )
    # NULL = tous les paniers actifs du player
    allowed_basket_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    can_edit_ratio: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    can_set_volume: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    can_trigger_event: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
