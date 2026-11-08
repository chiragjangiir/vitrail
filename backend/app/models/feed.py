"""Feed Display (§XXV.3) — source de flux RSS/Atom + items agrégés.

Un **feed** (`cms_datafeeds`) = une source pollée par Celery selon `polling_interval_s` ;
ses items dédupliqués (par `item_guid`) vivent dans `cms_feed_items`. Le contenu schedulable
est un `cms_media` (`media_type='feed_display'`, `metadata.id_feed`+`display_mode`+config) —
comme URL Display, il réutilise la machinerie média + le module RBAC `media`.

Première tranche : `feed_type` ∈ rss|atom|google_news ; `display_mode` ∈ ticker|card_carousel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsDatafeed(Base):
    """Source de flux pollable (RSS/Atom/Google News pour la tranche feed_display)."""

    __tablename__ = "cms_datafeeds"

    id_feed: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    feed_name: Mapped[str] = mapped_column(String(255), nullable=False)
    feed_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    polling_interval_s: Mapped[int] = mapped_column(
        Integer, server_default="900", default=900, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="active", default="active", nullable=False
    )
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    # ── colonnes feed_display ──
    display_mode: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    display_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    moderation_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    max_items: Mapped[int] = mapped_column(Integer, server_default="10", default=10, nullable=False)
    dedup_window_h: Mapped[int] = mapped_column(Integer, server_default="24", default=24, nullable=False)
    lang_filter: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    ai_summary_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsFeedItem(Base):
    """Item normalisé + dédupliqué d'un feed (cache local, modération optionnelle)."""

    __tablename__ = "cms_feed_items"

    id_item: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_feed: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_datafeeds.id_feed", ondelete="CASCADE"), nullable=False, index=True
    )
    item_guid: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_ai: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_s3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── valeurs numériques (data_chart §25.3) — NULL pour les feeds RSS/Atom ──
    value_num: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    series: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    categories: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    moderation_status: Mapped[str] = mapped_column(
        String(20), server_default="approved", default="approved", nullable=False
    )
    is_shown: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    show_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    last_shown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
