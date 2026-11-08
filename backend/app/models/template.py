from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, BigInteger, Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsTemplate(Base):
    """Template de mise en page (zones) — §XIII."""

    __tablename__ = "cms_templates"

    id_template: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # { layout_type: "full"|"split_h"|"split_v"|"sidebar_r",
    #   zones: [{index, x, y, w, h, label}] }  — coordonnées en px 1920×1080
    layout: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    preview_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # P3.6 — où s'affiche un spot de campagne sur un écran MULTI-ZONES (migr 0124) :
    # `fullscreen` = le spot recouvre tout l'écran (seul mode cohérent avec la tarification
    # au SOV) · `zone` = le spot s'insère dans la zone principale, les autres continuent.
    # Sans effet sur un template mono-zone, qui a toujours reçu les spots en plein écran.
    campaign_placement: Mapped[str] = mapped_column(
        String(20), server_default="fullscreen", default="fullscreen", nullable=False)
    # Gouvernance §XVIII (phase 4 de l'audit 2026-07-27, migr 0112). NULL = template
    # d'organisation, partagé par tous (comportement historique). Non NULL = seul un admin
    # du nœud ou d'un de ses ancêtres l'édite — un responsable de magasin ne casse plus une
    # maquette nationale (défaut N3 : template partagé 5 modifié en 200).
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    # ⚠️ `DateTime(timezone=True)` EXPLICITE : la colonne est TIMESTAMPTZ, mais sans ce type
    # SQLAlchemy déduit de l'annotation un TIMESTAMP SANS fuseau et asyncpg refuse alors
    # tout datetime aware. C'est exactement ce qui rendait la mise sous embargo d'un média
    # inutilisable (500 à chaque appel, corrigé le 2026-07-28) — le piège était ici aussi,
    # simplement latent tant que personne n'écrivait ces colonnes.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
