from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsBrandKit(Base):
    """Charte de marque (P3.4, migr 0128) — couleurs, police, nom, logo, mentions et ton.

    Déclarée UNE fois, puis pré-remplit le générateur promo (§12) et l'assistant de prompt.
    **Deux rattachements, jamais les deux** : `id_advertiser IS NULL` = charte de l'ORGANISATION,
    `id_advertiser` renseigné = charte de cet ANNONCEUR ; un visuel fait pour un annonceur prend
    la sienne, sinon celle de l'org. Au plus une de chaque — garanti par deux index UNIQUE
    partiels, pas par une garde applicative.

    ⚠️ Toute valeur nulle signifie « la charte ne dit rien » : le thème du template garde alors la
    sienne. Une charte ne remplace QUE ce qu'elle déclare.

    TENANT-SCOPED (RLS id_org, FORCE).
    """

    __tablename__ = "cms_brand_kits"

    id_brand_kit: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    id_advertiser: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_advertisers.id_advertiser", ondelete="CASCADE"), nullable=True)
    kit_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Couleurs — reprises telles quelles par le thème du template (CHECK hexadécimal en base).
    accent: Mapped[str | None] = mapped_column(String(9), nullable=True)
    ink: Mapped[str | None] = mapped_column(String(9), nullable=True)
    paper: Mapped[str | None] = mapped_column(String(9), nullable=True)
    badge_bg: Mapped[str | None] = mapped_column(String(9), nullable=True)
    badge_ink: Mapped[str | None] = mapped_column(String(9), nullable=True)

    # Nom de FAMILLE (built-in ou custom org) — vérifié au catalogue à l'écriture.
    font_family: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Identité de marque : posée par le COMPOSITING, jamais dessinée par le modèle génératif.
    brand_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    id_logo_media: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media", ondelete="SET NULL"), nullable=True)
    legal_mentions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ton de marque : entre dans le prompt comme ATMOSPHÈRE à viser.
    tone: Mapped[str | None] = mapped_column(String(400), nullable=True)

    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(UTC), nullable=False)
