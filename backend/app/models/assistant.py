"""AI Assistant RAG (§XXVII) — chunks de doc indexés, sessions, stats.

- `CmsDocChunk` : chunk de documentation produit (GLOBAL, filtré par rôle), avec
  embedding pgvector `nomic-embed-text` (768 dims). PAS tenant-scoped.
- `CmsAssistantSession` : historique conversationnel par utilisateur (TTL 24h),
  TENANT-scoped (RLS `id_org`).
- `CmsAssistantStat` : compteurs quotidiens d'usage par org (RLS `id_org`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsDocChunk(Base):
    """Chunk de documentation indexé en pgvector (recherche RAG, filtrage par rôle)."""

    __tablename__ = "cms_doc_chunks"

    id_chunk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Identité stable = hash(source_file + section) → upsert incrémental (re-index idempotent).
    chunk_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_anchor: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Rôles autorisés à voir ce chunk ; vide = visible par tous les rôles.
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), default=list, nullable=False
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), default=list, nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsAssistantSession(Base):
    """Session de chat de l'assistant (historique + contexte page), TTL 24h, tenant-scoped."""

    __tablename__ = "cms_assistant_sessions"

    id_session: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_user: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=False, index=True
    )
    messages: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list, nullable=False
    )
    page_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now() + interval '24 hours'"),
        nullable=False,
    )


class CmsAssistantStat(Base):
    """Compteurs quotidiens d'usage de l'assistant par org (messages + tokens), tenant-scoped."""

    __tablename__ = "cms_assistant_stats"

    id_stat: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(
        Date, server_default=text("current_date"), nullable=False
    )
    message_count: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    token_count: Mapped[int] = mapped_column(
        BigInteger, server_default="0", default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
