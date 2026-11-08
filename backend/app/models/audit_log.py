from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsAuditLog(Base):
    __tablename__ = "cms_audit_log"

    id_audit: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("cms_organizations.id_org", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_user: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("cms_users.id_user", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Origine de l'action : 'cms' (back-office) ou 'local_control' (Store Control Panel §19.3)
    source: Mapped[str] = mapped_column(String(30), server_default="cms", default="cms", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
