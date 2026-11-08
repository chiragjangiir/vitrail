from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsPlayerGroup(Base):
    __tablename__ = "cms_player_groups"

    id_group: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # content (players visuels) | audio (players audio-capables) | mixed (les deux)
    group_type: Mapped[str] = mapped_column(
        String(20), server_default="content", default="content", nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_org", "group_name", name="uq_player_group_name_per_org"),
    )


class CmsPlayerGroupMember(Base):
    __tablename__ = "cms_player_group_members"

    id_group: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_player_groups.id_group", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )
    id_player: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
