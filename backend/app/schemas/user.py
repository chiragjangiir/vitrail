from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    locale: str = "en"
    is_demo: bool = False  # compte démo (lecture seule, message localisé sur toute action)

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, v: str) -> str:
        allowed = {"en", "fr", "es", "pt", "de"}
        if v not in allowed:
            raise ValueError(f"locale must be one of {allowed}")
        return v


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id_user: int
    id_org: int
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    totp_enabled: bool
    locale: str
    theme: str = "light"
    is_active: bool
    is_demo: bool = False
    # Portail annonceur (S7 B2) : non-NULL = compte externe lié à UN annonceur →
    # le front redirige vers /portal et masque le CMS.
    id_advertiser: Optional[int] = None
    last_login_at: Optional[datetime]
    created_at: datetime
    org_name: Optional[str] = None  # peuplé par /users/me (indicateur d'org dans l'UI)
    # Peuplés par /users/me UNIQUEMENT (vides sur les listes d'utilisateurs) :
    # droits effectifs servant à masquer menus et boutons inutilisables côté UI.
    roles: list[str] = []
    permissions: list[str] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    locale: Optional[str] = None
    theme: Optional[str] = None
    is_demo: Optional[bool] = None  # réservé à l'admin (update_user) ; strippé dans update_me

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"en", "fr", "es", "pt", "de"}
        if v not in allowed:
            raise ValueError(f"locale must be one of {allowed}")
        return v

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"light", "dark"}:
            raise ValueError("theme must be 'light' or 'dark'")
        return v


class UserRoleAssign(BaseModel):
    id_role: int
    is_deny: bool = False


class AssignedRoleRead(BaseModel):
    """Rôle assigné à un utilisateur (pour la section rôles du drawer IAM)."""
    id_role: int
    role_key: str
    label: str
    is_deny: bool


class TotpResetResponse(BaseModel):
    """Secret + URI otpauth pour (ré)enrôler la 2FA d'un utilisateur (QR côté UI)."""
    email: str
    secret: str
    otpauth_uri: str


class GroupCreate(BaseModel):
    group_name: str
    description: Optional[str] = None
    scope_type: str = "org"
    scope_id: Optional[int] = None


class GroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id_group: int
    id_org: int
    group_name: str
    description: Optional[str]
    scope_type: str
    scope_id: Optional[int]
    is_active: bool
    created_at: datetime


class RoleCreate(BaseModel):
    role_key: str
    label: str
    description: Optional[str] = None


class RoleRead(BaseModel):
    model_config = {"from_attributes": True}

    id_role: int
    id_org: Optional[int]
    role_key: str
    label: str
    description: Optional[str]
    is_system: bool
    is_active: bool


class PermissionRead(BaseModel):
    """Entrée du catalogue de permissions atomiques (§II.1)."""
    model_config = {"from_attributes": True}

    id_permission: int
    module: str
    operation: str
    description: Optional[str] = None
    #: False = permission d'une fonctionnalité SPÉCIFIÉE mais pas encore développée
    #: (aujourd'hui `spf:*`, moteur §XIV). L'éditeur l'affiche grisée et non
    #: cochable : sans cela, un client coche un droit qui ne protège rien et croit
    #: avoir activé la fonctionnalité. Décision Ed 2026-07-20.
    available: bool = True


class RolePermissionsUpdate(BaseModel):
    """Jeu COMPLET des permissions d'un rôle custom (remplacement, pas fusion)."""
    permissions: list[str]  # ["media:read", "media:create", …]
