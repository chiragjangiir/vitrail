from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text

from app.db.base import Base


class CmsEvent(Base):
    """Event Override avec machine à états inactive→active→reverting→completed (§XX)."""

    __tablename__ = "cms_events"

    id_event: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # manual | scheduled | conditional | ai_predicted
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # content (playlist/media visuel) | audio (panier audio §XIX)
    event_kind: Mapped[str] = mapped_column(
        String(20), server_default="content", default="content", nullable=False
    )
    id_playlist: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_playlists.id_playlist"), nullable=True
    )
    # Panier audio activé (event_kind=audio) + ratio de mix
    id_basket: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_audio_baskets.id_basket"), nullable=True
    )
    mix_ratio: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    # Contenu unique (image/vidéo/audio) — alternatif à id_playlist (Sprint 2.4)
    id_media: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media"), nullable=True
    )
    # 0–100 : priorité de résolution des conflits (§XX.5)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="70", default=70, nullable=False)
    # NULL = durée indéfinie (revert manuel uniquement)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    revert_on_end: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    # inactive | active | reverting | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), server_default="'inactive'", default="inactive", nullable=False)
    # Expression logique AND/OR des conditions (§XX.4) — NULL pour event_type=manual
    trigger_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Ciblage players/groupes/org (§XX.7) — obligatoire
    target_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Gouvernance §XVIII (phase 4 de l'audit 2026-07-27, migr 0112). NULL = événement
    # d'organisation (comportement historique). Non NULL = édition gardée par le nœud ET
    # cibles contraintes à son périmètre : un événement coupe le contenu en cours sur les
    # écrans qu'il vise, c'est la diffusion la plus immédiatement visible du produit.
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Plage de validité — l'event ne peut s'activer qu'entre valid_from et valid_until
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Si True : repasse en inactive après expiration (répétition automatique)
    is_recurring: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    # Si True : l'event coupe le contenu en cours à l'heure exacte (start + end)
    # Si False (défaut) : l'event attend la fin de l'item en cours avant de s'appliquer
    is_preemptive: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    # Si True : tant que l'event est actif, ses players ciblés gardent l'écran ALLUMÉ
    # (auto-power lot 2) — extension de l'alimentation, ne l'éteint jamais.
    keep_screens_on: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    # Embargo UTC : l'event ne peut s'activer avant cette date/heure, quelle que soit SIGNFLOW_TZ
    not_before_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fuseau de RÉFÉRENCE des fenêtres horaires du trigger_config (P3.13, migr 0123).
    # Un événement porte UNE ligne et UN `activated_at` : il ne peut pas s'activer à l'heure
    # locale de chaque écran (ce serait l'option ①, écartée). Il déclare donc ce que « 18 h »
    # veut dire. NULL = SIGNFLOW_TZ, soit le comportement historique.
    # ⚠️ Sans rapport avec `not_before_utc` juste au-dessus : l'embargo est un instant ABSOLU,
    # volontairement hors de tout fuseau — ne pas « harmoniser » les deux.
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Calculé à l'activation : activated_at + duration_ms
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` : `updated_at` était entretenu À LA MAIN en 4 points de l'API et par du
    # SQL brut dans le worker. Ça marche tant qu'on y pense — et toute mutation ajoutée
    # ensuite est muette. Au modèle, tout UPDATE de la ligne l'entretient (même correctif
    # que playlists / templates / VOD).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsEventAiSuggestion(Base):
    """Suggestion d'événement générée par l'agent IA, en attente de validation (§XX.8)."""

    __tablename__ = "cms_event_ai_suggestions"

    id_suggestion: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    trigger_summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    id_playlist: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_playlists.id_playlist"), nullable=True
    )
    # Score de confiance 0.000–1.000
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    based_on: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(20), server_default="'pending'", nullable=False)
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Rempli après approbation → création de l'event
    # `ondelete="SET NULL"` (migr 0118) : sans action, supprimer un événement né d'une
    # suggestion approuvée violait la contrainte et sortait en 500 non traité. SET NULL et
    # non CASCADE — la suggestion est une trace de DÉCISION (« l'IA a proposé, un humain a
    # approuvé »), elle doit survivre à l'événement qu'elle a produit.
    id_event_created: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_events.id_event", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
