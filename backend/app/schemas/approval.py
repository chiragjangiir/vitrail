from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ApprovalSubmit(BaseModel):
    resource_type: str = Field(max_length=30)
    resource_id: int
    notes: str | None = None
    due_date: datetime | None = None


class ApprovalActionBody(BaseModel):
    """Corps des actions approve/reject/request-changes/resubmit/comment.

    Le caractère obligatoire du commentaire dépend de l'action (reject et
    request-changes l'exigent — validé dans l'endpoint, règle §21.5)."""

    comment: str | None = None
    # Retour Ed #9 : envoyer le récap de décision par email aux comptes portail de
    # l'annonceur (approve/reject/request-changes seulement, best-effort).
    notify_advertiser: bool = False


class ApprovalCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_comment: int
    id_request: int
    id_user: int
    comment_text: str
    action: str | None = None
    created_at: datetime
    # Peuplé par l'endpoint (jointure users)
    user_name: str | None = None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_request: int
    id_org: int
    resource_type: str
    resource_id: int
    submitted_by: int
    submitted_at: datetime
    status: str
    due_date: datetime | None = None
    notes: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Enrichissements peuplés par l'endpoint (pas des colonnes)
    resource_name: str | None = None
    submitted_by_name: str | None = None
    reviewed_by_name: str | None = None
    # Retour d'envoi email annonceur (#9) — peuplé seulement quand la décision a été
    # prise avec notify_advertiser (None = pas demandé ; 0 = aucun compte portail)
    email_sent_to: int | None = None
    email_error: str | None = None


class ApprovalCreativeInfo(BaseModel):
    """Créatif de la campagne montré au reviewer (avec prévisualisation signée)."""

    id_creative: int
    media_name: str
    media_type: str
    duration_ms: int = 0
    approval_status: str
    preview_url: str | None = None
    thumbnail_url: str | None = None


class ApprovalTargetInfo(BaseModel):
    target_type: str
    name: str | None = None  # None pour `org` (label i18n côté UI)


class ApprovalOccupancyInfo(BaseModel):
    """Occupation SOV projetée des cibles (moteur S2 v2 — seuils relatifs au plafond)."""

    warning: bool = False
    blocked: bool = False
    max_projected_pct: float = 0


class ApprovalOtherCampaign(BaseModel):
    """Campagne déjà en place sur les cibles — le reviewer voit d'où vient l'occupation."""

    id_campaign: int
    campaign_name: str
    sov_percent: float
    starts_on: date
    ends_on: date
    shared_players: int = 0


class ApprovalPriceInfo(BaseModel):
    """Devis (tarifs par écran v2) — le prix contractuel reste le champ de la campagne."""

    estimated_price: float
    priced_players: int
    unpriced_players: int = 0
    days: int


class ApprovalAchievableInfo(BaseModel):
    """SOV max réalisable (anti-martèlement) — le valideur voit l'écart demandé/physique."""

    max_sov_pct: float
    worst_player_name: str | None = None


class ApprovalCampaignInfo(BaseModel):
    """Paramètres commerciaux montrés au reviewer — il ne valide plus à l'aveugle."""

    advertiser_name: str | None = None
    # Catégories d'industrie de l'annonceur (exclusion concurrentielle #10, multi 0088)
    industry_categories: list[str] = []
    starts_on: date
    ends_on: date
    daily_hours: dict | None = None
    sov_percent: float
    priority: int = 50
    pricing_model: str
    price_amount: float | None = None
    price_currency: str = "EUR"
    cpm_rate: float | None = None
    targets: list[ApprovalTargetInfo] = []
    target_player_count: int = 0
    occupancy: ApprovalOccupancyInfo | None = None
    other_campaigns: list[ApprovalOtherCampaign] = []
    price: ApprovalPriceInfo | None = None
    achievable: ApprovalAchievableInfo | None = None


class ApprovalPlaylistItemInfo(BaseModel):
    media_name: str | None = None
    media_type: str | None = None
    duration_ms: int | None = None
    thumbnail_url: str | None = None


class ApprovalPlaylistInfo(BaseModel):
    id_playlist: int
    playlist_name: str
    item_count: int
    items: list[ApprovalPlaylistItemInfo] = []


class ApprovalDetail(ApprovalRead):
    comments: list[ApprovalCommentRead] = []
    # resource_type campaign : ce que le reviewer approuve (visionnage inline)
    creatives: list[ApprovalCreativeInfo] = []
    campaign: ApprovalCampaignInfo | None = None
    # resource_type playlist (gouvernance §XVIII) : aperçu du brouillon soumis.
    playlist: ApprovalPlaylistInfo | None = None


class ApprovalDashboard(BaseModel):
    """Compteurs de la file (§21.5 /approvals/dashboard)."""

    pending_review: int = 0
    changes_requested: int = 0
    approved: int = 0
    rejected: int = 0
    published: int = 0
    urgent: int = 0  # pending_review/changes_requested avec due_date < 48 h
    # Cloche topbar (retour Ed #7) : l'appelant est-il valideur (voit l'org entière) ?
    is_reviewer: bool = False
