from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsPromoTemplate(Base):
    """Modèle promo réutilisable (Générateur Promo Phase C). Instantané nommé de l'état de
    l'éditeur (`config` JSONB : template built-in, format/résolution, textes+styles+calques,
    fond/produit). TENANT-SCOPED (RLS id_org)."""

    __tablename__ = "cms_promo_templates"

    id_promo_template: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False,
                                         default=dict)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=func.now(), nullable=False)
