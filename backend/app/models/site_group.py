from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsSiteGroup(Base):
    """Groupe de SITES (région, enseigne, typologie…) — miroir des groupes de players.

    Cible canonique `site_group` (targeting.py) : un nouveau player posé dans un site
    membre est adressé automatiquement (le groupe vit au niveau site, pas player).
    """

    __tablename__ = "cms_site_groups"

    id_site_group: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_org", "group_name", name="uq_site_group_name_per_org"),
    )


class CmsSiteGroupMember(Base):
    __tablename__ = "cms_site_group_members"

    id_site_group: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_site_groups.id_site_group", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )
    id_site: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )
    # Dénormalisé pour la policy RLS standard (pattern 0074) — évite la policy par jointure.
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
