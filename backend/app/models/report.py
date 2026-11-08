from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsReportBranding(Base):
    """Personnalisation white-label du rapport exécutif + hypothèses ROI (§XXIV). 1/org. RLS."""

    __tablename__ = "cms_report_branding"

    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), primary_key=True)
    logo_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str] = mapped_column(
        String(7), server_default="#4875B4", nullable=False)
    report_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    report_subtitle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    roi_hours_per_day: Mapped[float] = mapped_column(
        Numeric(4, 1), server_default="12", nullable=False)
    roi_contacts_hour: Mapped[int] = mapped_column(
        Integer, server_default="50", nullable=False)
    roi_cpm_eur: Mapped[float] = mapped_column(Numeric(8, 2), server_default="5", nullable=False)
    roi_paper_eur: Mapped[float] = mapped_column(Numeric(8, 2), server_default="50", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)


class CmsReportShareLink(Base):
    """Lien de partage sans login d'un dashboard (§24.4) — token opaque révocable, TTL. RLS."""

    __tablename__ = "cms_report_share_links"

    id_share: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period_days: Mapped[int] = mapped_column(Integer, server_default="30", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Options avancées (§24.4) : NULL = pas de mot de passe / pas de restriction IP.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_allowlist: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # liste de CIDR
    # Type du lien (migr 0076) : executive (défaut) | campaign (rapport annonceur §2.8 S4)
    report_type: Mapped[str] = mapped_column(
        String(30), server_default="executive", default="executive", nullable=False)
    id_campaign: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_campaigns.id_campaign", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)


class CmsReportSchedule(Base):
    """Rapport exécutif planifié (§24.3) — génération PDF + envoi email récurrent. RLS."""

    __tablename__ = "cms_report_schedules"

    id_schedule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    report_type: Mapped[str] = mapped_column(String(30), server_default="executive",
                                             nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), server_default="monthly", nullable=False)
    send_hour: Mapped[int] = mapped_column(SmallInteger, server_default="7", nullable=False)
    send_dow: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)
    send_dom: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, server_default="30", nullable=False)
    language: Mapped[str] = mapped_column(String(5), server_default="fr", nullable=False)
    recipients: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"), nullable=False,
                                             default=list)
    include_roi: Mapped[bool] = mapped_column(Boolean, server_default=text("true"),
                                              nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False,
                                          default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)


class CmsReportHistory(Base):
    """Trace d'un rapport généré/envoyé (§24.3). RLS."""

    __tablename__ = "cms_report_history"

    id_history: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    id_schedule: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_report_schedules.id_schedule", ondelete="SET NULL"),
        nullable=True)
    report_type: Mapped[str] = mapped_column(String(30), server_default="executive",
                                             nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    recipients: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"), nullable=False,
                                             default=list)
    status: Mapped[str] = mapped_column(String(10), server_default="sent", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
