"""Retail Media §2.8 — annonceurs, campagnes, créatifs, cibles (migr 0074).

Cadrage docs/PLAN_RETAIL_MEDIA.md : vente v1 = SOV % + forfait (CPM indicatif),
surbooking = blocage + override org-admin, approval créatifs optionnel par org.
Les cibles reprennent le modèle canonique des schedules (services/targeting.py).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsIndustryCategory(Base):
    """Catégorie d'industrie (migr 0087, retour Ed #10) — liste gérée par l'org.

    Sert à l'exclusion concurrentielle : un annonceur porte une catégorie
    (« Automobile »), un SITE peut exclure des catégories (concession Peugeot →
    exclut Automobile) → les players du site sortent de l'inventaire de tout
    annonceur de cette catégorie (même tuyau que l'opt-out player)."""

    __tablename__ = "cms_industry_categories"

    id_category: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsSiteExcludedCategory(Base):
    """Catégorie exclue par un SITE (héritée par ses players) — migr 0087."""

    __tablename__ = "cms_site_excluded_categories"

    id_site: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site", ondelete="CASCADE"), primary_key=True
    )
    id_category: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_industry_categories.id_category", ondelete="CASCADE"),
        primary_key=True,
    )
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsAdvertiserIndustryCategory(Base):
    """Catégories d'industrie d'un ANNONCEUR (migr 0088 — 1-N : une agence de pub
    porte plusieurs industries ; remplace la colonne 1-1 de la 0087)."""

    __tablename__ = "cms_advertiser_industry_categories"

    id_advertiser: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_advertisers.id_advertiser", ondelete="CASCADE"),
        primary_key=True,
    )
    id_category: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_industry_categories.id_category", ondelete="CASCADE"),
        primary_key=True,
    )
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsAdvertiser(Base):
    """Annonceur (marque fournisseur) — propriétaire de campagnes."""

    __tablename__ = "cms_advertisers"

    id_advertiser: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    advertiser_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_info: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dossier médiathèque « Annonceurs/<nom> » (auto-créé) — les créatifs de cet
    # annonceur s'y classent ; le picker de campagne filtre sur son sous-arbre.
    id_folder: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_media_folders.id_folder", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True, nullable=False
    )
    # Types de campagne autorisés au PORTAIL self-service (migr 0095) — gate portail seul,
    # le retailer CMS reste libre. Audio = OFF par défaut (feature opt-in).
    allow_visual_campaigns: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True, nullable=False
    )
    allow_audio_campaigns: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` au MODÈLE (audit menu ⑨) : `updated_at` d'un annonceur ne bougeait
    # jamais (6/6 en prod figés à created_at). Colonne déjà timestamptz, aucune migration.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsAdvertiserSiteList(Base):
    """Liste de sites enregistrée par un annonceur du portail (retour Ed #11, migr 0085).

    Purement UI : `site_ids` (JSONB) n'est jamais résolu par le targeting — l'annonceur
    rappelle sa sélection dans le formulaire de campagne self-service. Scope par
    annonceur = applicatif (endpoints /portal), RLS id_org standard.
    """

    __tablename__ = "cms_advertiser_site_lists"

    id_list: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False
    )
    id_advertiser: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_advertisers.id_advertiser", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    list_name: Mapped[str] = mapped_column(String(255), nullable=False)
    site_ids: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsCampaign(Base):
    """Campagne annonceur : SOV vendue sur une période, sur des cibles canoniques."""

    __tablename__ = "cms_campaigns"

    id_campaign: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_advertiser: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_advertisers.id_advertiser"), nullable=False
    )
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # draft -> (pending_approval ->) approved -> live <-> paused -> completed | cancelled
    status: Mapped[str] = mapped_column(
        String(20), server_default="draft", default="draft", nullable=False
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    # {"start": "09:00", "end": "20:00"} — fenêtre horaire quotidienne optionnelle
    daily_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sov_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), server_default="10.0", default=10.0, nullable=False
    )
    max_plays_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Retail Media AUDIO S2 (migr 0094) : 'visual' (défaut) | 'audio'. Une campagne audio
    # vend des SPOTS/HEURE (spots_per_hour) insérés dans la rotation musicale §XIX —
    # sov_percent est ignoré. Immuable après création (pas dans CampaignUpdate).
    campaign_kind: Mapped[str] = mapped_column(
        String(10), server_default="visual", default="visual", nullable=False
    )
    spots_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pricing_model: Mapped[str] = mapped_column(
        String(10), server_default="sov", default="sov", nullable=False
    )  # sov | flat (cpm = indicatif v1)
    price_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_currency: Mapped[str] = mapped_column(
        String(3), server_default="EUR", default="EUR", nullable=False
    )
    cpm_rate: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, server_default="50", default=50, nullable=False)
    # Surbooking : la sauvegarde bloque à 100 % d'occupation, sauf override org-admin explicite.
    overbook_override: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    # Notifications §XXII (campaign_worker) — dédup edge-triggered des transitions de
    # cycle de vie (démarrée/terminée : une notification par transition) + date de la
    # dernière évaluation de sous-diffusion (une par jour).
    started_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    underserved_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` au MODÈLE : les 3 chemins qui entretenaient `updated_at` le faisaient
    # À LA MAIN (`camp.updated_at = func.now()`) — donc toute mutation ajoutée ailleurs
    # l'aurait oublié. ⚠️ Les assignations manuelles RESTENT et ne font pas doublon :
    # quand SEULES les cibles changent, aucune colonne de la campagne n'est modifiée,
    # la ligne n'est pas « sale » et `onupdate` ne se déclenche pas — c'est l'assignation
    # explicite qui marque alors la campagne comme touchée.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsCampaignCreative(Base):
    """Créatif d'une campagne : pointeur média + rotation pondérée."""

    __tablename__ = "cms_campaign_creatives"

    id_creative: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_campaign: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_campaigns.id_campaign", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    id_media: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media"), nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = durée native
    weight: Mapped[int] = mapped_column(Integer, server_default="1", default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), server_default="active", default="active", nullable=False
    )  # active | archived
    # Approbation inline S5 (pattern moderation_status feeds §25) — enforced seulement
    # si l'org a campaign_creative_approval : pending | approved | rejected.
    approval_status: Mapped[str] = mapped_column(
        String(20), server_default="approved", default="approved", nullable=False
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsCampaignTarget(Base):
    """Cible de diffusion d'une campagne (modèle canonique player/group/site/tags/org)."""

    __tablename__ = "cms_campaign_targets"

    id_target: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_campaign: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_campaigns.id_campaign", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # org | site | group | player | tags
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tag_expr: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
