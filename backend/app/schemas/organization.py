from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr


class OrgCreate(BaseModel):
    org_name: str
    org_slug: str


class OrgProvisionAdmin(BaseModel):
    """Crée le 1er administrateur (CMS_ORG_ADMIN) d'un tenant (super-admin)."""
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class OrgProvisionAdminResult(BaseModel):
    id_user: int
    email: str
    totp_secret: str
    totp_uri: str


class OrgRead(BaseModel):
    model_config = {"from_attributes": True}

    id_org: int
    org_name: str
    org_slug: str
    db_schema: Optional[str]
    version_lock_enabled: bool
    player_version_lock: Optional[str]
    # Politique de génération des renditions adaptatives : off | auto_fhd
    rendition_policy: str = "off"
    is_active: bool = True
    # Crédit AI Assistant : NULL/0 = illimité ; unité tokens|eur ; période weekly|monthly.
    ai_quota_unit: str = "tokens"
    ai_quota_tokens: Optional[int] = None
    ai_quota_eur: Optional[float] = None
    # Plafonds de dépense BYOK (P3.2) — NULL/0 = aucun plafond.
    ai_spend_cap_usd: Optional[float] = None
    ai_user_spend_cap_usd: Optional[float] = None
    ai_spend_cap_period: str = "month"
    ai_quota_period: str = "monthly"
    ai_alert_threshold_pct: int = 80
    # Politique d'accès aux clés IA (BYOK §XXVII) : strict (défaut) | platform.
    ai_byok_mode: str = "strict"
    created_at: datetime


class OrgUpdate(BaseModel):
    org_name: Optional[str] = None
    version_lock_enabled: Optional[bool] = None
    player_version_lock: Optional[str] = None
    rendition_policy: Optional[str] = None  # off | auto_fhd
    is_active: Optional[bool] = None  # suspension org (super-admin)
    # Crédit AI Assistant (super-admin) : 0 = illimité ; unité tokens|eur ; période weekly|monthly.
    ai_quota_unit: Optional[str] = None
    ai_quota_tokens: Optional[int] = None
    ai_quota_eur: Optional[float] = None
    ai_quota_period: Optional[str] = None
    ai_alert_threshold_pct: Optional[int] = None
    # Autorisation explicite de la clé Anthropic plateforme (super-admin) : strict | platform.
    ai_byok_mode: Optional[str] = None
    # Plafonds de DÉPENSE BYOK en USD (P3.2). ⚠️ `update_org` filtre les `None`
    # (`exclude_none=True`) : **0 = aucun plafond** est la seule façon d'en retirer un — et
    # c'est déjà la convention de `ai_quota_tokens`, pas une invention locale.
    ai_spend_cap_usd: Optional[float] = None
    ai_user_spend_cap_usd: Optional[float] = None
    ai_spend_cap_period: Optional[str] = None   # day | week | month


class OrgAiCredentialRead(BaseModel):
    """Vue masquée d'une clé provider — ne renvoie JAMAIS le secret en clair."""

    model_config = {"from_attributes": True}

    provider: str
    key_last4: Optional[str] = None
    status: str
    validated_at: Optional[datetime] = None
    updated_at: datetime


class OrgAiCredentialUpsert(BaseModel):
    """Saisie d'une clé provider (le clair n'existe qu'en entrée, chiffré avant stockage)."""

    provider: Literal["anthropic", "fal", "elevenlabs"]
    api_key: str


class OrgAuthSettingsRead(BaseModel):
    model_config = {"from_attributes": True}

    id_org: int
    auth_2fa_policy: str
    session_lifetime: int
    max_sessions: int
    password_min_len: int
    password_policy: dict
    ip_allowlist: Optional[list]
    updated_at: datetime


class OrgPlayerAlertSettings(BaseModel):
    """Seuils d'alerte player configurables par org (GET/PUT /orgs/{id}/player-alert-settings)."""
    offline_critical_min: int = 10       # minutes avant de passer de offline → critical
    cpu_warn_pct: float = 90.0           # % CPU au-dessus duquel le player passe en warning
    ram_warn_pct: float = 90.0           # % RAM
    disk_warn_pct: float = 85.0          # % disque
    token_warn_days: int = 7             # jours avant expiration du token JWT player
    min_player_version: Optional[str] = None  # ex. "1.5.0" — null = pas de vérification


class OrgAuthSettingsUpdate(BaseModel):
    # disabled | optional | required
    auth_2fa_policy: Optional[str] = None
    session_lifetime: Optional[int] = None
    max_sessions: Optional[int] = None
    password_min_len: Optional[int] = None
    password_policy: Optional[dict] = None
    ip_allowlist: Optional[list] = None
