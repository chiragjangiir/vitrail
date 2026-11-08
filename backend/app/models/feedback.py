"""Retours utilisateurs (feedback) — modèle (§ retours UI).

Tenant-scoped (RLS `id_org`). Un utilisateur signale un bug / une suggestion / etc. depuis
l'UI ; le triage IA (catégorie/sévérité/résumé) est rempli best-effort par le worker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsFeedback(Base):
    __tablename__ = "cms_feedback"

    id_feedback: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_user: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=False
    )
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Auto-contexte capté côté front.
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    route: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    console_errors: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list, nullable=False
    )
    # Clés MinIO (bucket média, préfixe `feedback/{id_org}/`) des captures jointes par l'user.
    screenshot_keys: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list, nullable=False
    )
    severity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), server_default="new", default="new", nullable=False
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Triage IA (best-effort).
    ai_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_severity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
