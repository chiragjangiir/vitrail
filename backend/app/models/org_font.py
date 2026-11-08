from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsOrgFont(Base):
    """Police personnalisée d'une organisation (Générateur Promo §12.7). 1 ligne par
    (id_org, family, weight). Le fichier (woff2/ttf/otf) vit dans MinIO (`org-fonts/`) ;
    `license_ack` = attestation utilisateur qu'il a le droit d'embarquer cette police.
    TENANT-SCOPED (RLS id_org)."""

    __tablename__ = "cms_org_fonts"

    id_font: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    family: Mapped[str] = mapped_column(String(80), nullable=False)
    weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=400)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    font_format: Mapped[str] = mapped_column(String(8), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    license_ack: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False,
                                              default=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
