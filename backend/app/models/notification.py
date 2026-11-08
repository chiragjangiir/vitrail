from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsNotificationChannel(Base):
    """Destination d'alerte d'une org (§XXII) — MVP webhook (config {url}). TENANT-SCOPED (RLS)."""

    __tablename__ = "cms_notification_channels"

    id_channel: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(20), server_default="webhook", nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False,
                                         default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False,
                                          default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsAlertRule(Base):
    """Règle (type d'événement → canal) active (§XXII). TENANT-SCOPED (RLS)."""

    __tablename__ = "cms_alert_rules"

    id_rule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    id_channel: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_notification_channels.id_channel", ondelete="CASCADE"),
        nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False,
                                         default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False,
                                          default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsNotificationLog(Base):
    """Trace d'un envoi d'alerte (§XXII). TENANT-SCOPED (RLS)."""

    __tablename__ = "cms_notification_log"

    id_log: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    id_rule: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_alert_rules.id_rule", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="sent", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
