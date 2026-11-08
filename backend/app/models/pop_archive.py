from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Date, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsPopArchive(Base):
    """Index permanent d'une période de Proof of Play sortie hors base (§XXIV, archivage).

    Une ligne = un lot archivé (org × période journalière). Porte le `merkle_root` de la
    période — preuve cryptographique compacte de tout le lot, conservée à vie même après
    expiration du blob froid (MinIO). Voir PLAN_POP_ARCHIVAL.
    """

    __tablename__ = "cms_pop_archives"

    id_archive: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)   # borne incluse
    period_end: Mapped[date] = mapped_column(Date, nullable=False)     # borne excluse
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    merkle_root: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    csv_key: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bytes_csv: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    players: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
