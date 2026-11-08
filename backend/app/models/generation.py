from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsGenerationJob(Base):
    """Job de génération de contenu IA asynchrone (§ génération — vidéo/audio).

    L'image est générée en synchrone dans l'endpoint (rapide) ; la vidéo et l'audio
    (lents) passent par un job + le worker `generate_content`. TENANT-SCOPED (RLS id_org).
    """

    __tablename__ = "cms_generation_jobs"

    id_job: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # video | music | voice
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # fal | elevenlabs
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    aspect_ratio: Mapped[str | None] = mapped_column(String(12), nullable=True)
    params: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False, default=dict
    )
    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(
        String(12), server_default="pending", default="pending", nullable=False
    )
    id_media: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Réservation de dépense BYOK (P3.2) : le worker s'en sert pour SOLDER au montant réel.
    id_spend: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Regroupe les assets d'une campagne one-shot (Phase 4). NULL = génération isolée.
    id_campaign: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsGenerationCampaign(Base):
    """Campagne de génération one-shot (§ génération — Phase 4) : un brief NL → un bundle
    de visuels (plusieurs concepts × plusieurs ratios). Chaque asset = un CmsGenerationJob
    portant `id_campaign`. TENANT-SCOPED (RLS id_org)."""

    __tablename__ = "cms_generation_campaigns"

    id_campaign: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    ratios: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'"), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(
        String(12), server_default="pending", default="pending", nullable=False
    )
    total_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsAiSpend(Base):
    """Registre des dépenses IA en BYOK (P3.2, migr 0126). TENANT-SCOPED (RLS id_org).

    ⚠️ Volontairement SÉPARÉ de `CmsGenerationJob`, qui est une FILE DE TRAVAIL et pas un
    livre de comptes. Mesuré le 2026-08-07 : sur les cinq chemins qui appellent réellement un
    fournisseur payant, quatre sont invisibles ou faux dans la table des jobs — l'image
    synchrone n'y écrit rien, le promo y écrit `cost_usd = 0` sur de vrais appels fal, et la
    réponse vocale de Jeanine n'y passe pas du tout. Un plafond bâti sur cette somme aurait
    eu l'air de fonctionner.

    🔑 La ligne est écrite AVANT l'appel (réservation sur l'estimation), puis corrigée au
    montant réel — ou relâchée si l'appel n'a pas eu lieu. Sans réservation, deux générations
    simultanées lisent la même somme et passent toutes les deux sous un plafond qui n'en
    tient qu'une.
    """

    __tablename__ = "cms_ai_spend"

    id_spend: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SET NULL : supprimer un compte n'efface pas la dépense qu'il a engagée — elle reste
    # sur la facture du client (même règle que le journal d'audit).
    id_user: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)   # fal | elevenlabs
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    estimated_usd: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    actual_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # reserved | settled | released
    status: Mapped[str] = mapped_column(
        String(10), server_default="reserved", default="reserved", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
