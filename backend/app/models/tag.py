from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsTagNamespace(Base):
    """Namespace de tags par organisation (§XVII.3) — ex. resolution, region, language."""

    __tablename__ = "cms_tag_namespaces"

    id_namespace: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False, index=True
    )
    namespace_key: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # any : OR dans le namespace (≥1 tag commun) | all : AND (réservé, non utilisé au runtime actuel)
    match_mode: Mapped[str] = mapped_column(String(10), server_default="any", default="any", nullable=False)
    # [] = tous types, ou ['video','image',...]
    applies_to: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("id_org", "namespace_key", name="uq_tag_ns_per_org"),)


class CmsTagValue(Base):
    """Valeur d'un namespace de tags (§XVII.3)."""

    __tablename__ = "cms_tag_values"

    id_tag: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_namespace: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_namespaces.id_namespace", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_value: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)

    __table_args__ = (UniqueConstraint("id_namespace", "tag_value", name="uq_tag_value_per_ns"),)


class CmsMediaTagValue(Base):
    """Jonction média ↔ tag (§XVII.3)."""

    __tablename__ = "cms_media_tag_values"

    id_media: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media", ondelete="CASCADE"), primary_key=True
    )
    id_tag: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_values.id_tag", ondelete="CASCADE"), primary_key=True
    )


class CmsPlaylistItemTag(Base):
    """Tag additif (ou de remplacement si override) sur un item de playlist (§XVII.3)."""

    __tablename__ = "cms_playlist_item_tags"

    id_item: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_playlist_items.id_item", ondelete="CASCADE"), primary_key=True
    )
    id_tag: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_values.id_tag", ondelete="CASCADE"), primary_key=True
    )


class CmsPlaylistItemNsOverride(Base):
    """Namespace en mode override pour un item (absent = mode additif par défaut) (§XVII.3)."""

    __tablename__ = "cms_playlist_item_ns_overrides"

    id_item: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_playlist_items.id_item", ondelete="CASCADE"), primary_key=True
    )
    id_namespace: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_namespaces.id_namespace", ondelete="CASCADE"), primary_key=True
    )


class CmsPlayerTagFilter(Base):
    """Profil de réception d'un player : tags acceptés par namespace (§XVII.3)."""

    __tablename__ = "cms_player_tag_filters"

    id_player: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player", ondelete="CASCADE"), primary_key=True
    )
    id_namespace: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_namespaces.id_namespace", ondelete="CASCADE"), nullable=False
    )
    id_tag: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_tag_values.id_tag", ondelete="CASCADE"), primary_key=True
    )
