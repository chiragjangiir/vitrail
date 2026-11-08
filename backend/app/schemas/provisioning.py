from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProvisioningTokenCreate(BaseModel):
    label: str
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None


class ProvisioningTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_key: int
    id_org: int
    key_prefix: str
    label: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    use_count: int
    is_active: bool
    created_at: datetime
    # Présent uniquement dans la réponse de création (non stocké en clair)
    token_value: Optional[str] = None


# ── Clé opérateur de provisioning (§XXIX) — installeur terrain sans JWT à re-copier ──

class ProvisioningKeyCreate(BaseModel):
    label: str = Field(..., max_length=255)
    expires_in_days: int = Field(90, ge=1, le=730)


class ProvisioningKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_key: int
    id_org: int
    key_prefix: str
    label: Optional[str] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    # Présent uniquement à la création (jamais stocké en clair)
    token_value: Optional[str] = None


class ProvisioningWhoami(BaseModel):
    id_org: int
    kind: str  # "user" | "key"


class ProvisioningPlayerStatus(BaseModel):
    id_player: int
    player_name: str
    status: str


class PlayerRegisterRequest(BaseModel):
    player_name: str
    player_os: str
    player_version: Optional[str] = None
    os_info: Optional[dict] = None
    org_token: str
    # N° de série stable du device (BrightSign : capabilities.bs_serial) → ré-attache idempotente
    # à un player existant au lieu de créer un doublon (cf. register_player).
    serial: str | None = None


class PlayerRegisterResponse(BaseModel):
    id_player: int
    player_token: str
    expires_at: datetime


# ── Installeur terrain (§XXIX) — payload de provisioning « 1 payload, plusieurs canaux » ──

class NetworkConfig(BaseModel):
    mode: Literal["dhcp", "static"] = "dhcp"
    ip: Optional[str] = None
    mask: Optional[str] = None
    gw: Optional[str] = None
    dns: Optional[str] = None
    wifi_ssid: Optional[str] = None
    wifi_psk: Optional[str] = None


class ProvisioningPayloadRequest(BaseModel):
    ref: str = Field(..., max_length=120)            # libellé/nom du player
    os: Literal["android", "linux", "rpi", "windows", "brightsign"]
    backend_url: Optional[str] = None                # sinon dérivé de la requête
    network: Optional[NetworkConfig] = None          # OPT-IN
    options: Optional[dict] = None                   # display_config initial (résolution/rotation)
    # id_player : ré-attache à un player existant (sinon création d'un nouveau)
    id_player: Optional[int] = None
    expires_in_days: int = Field(30, ge=1, le=365)


class ProvisioningPayload(BaseModel):
    version: int = 1
    ref: str
    os: str
    backend_url: str
    token: str                                       # sfp_… (à traiter comme un secret)
    network: Optional[NetworkConfig] = None
    options: Optional[dict] = None
    id_key: int                                      # pour révoquer le token depuis le CMS
    # cible si ré-attache (sinon création d'un nouveau player à l'enregistrement)
    id_player: Optional[int] = None


# ── Provisioning en LOT (§XXIX.10) — préparer N players via 1 clé USB ──

class ProvisioningBatchEntry(BaseModel):
    ref: str = Field(..., max_length=120)            # nom du player (une machine = une entrée)
    network: Optional[NetworkConfig] = None          # OPT-IN, par machine (IP statique distincte…)
    options: Optional[dict] = None


class ProvisioningBatchRequest(BaseModel):
    mode: Literal["per_machine", "shared"] = "per_machine"
    os: Literal["android", "linux", "rpi", "windows", "brightsign"]
    backend_url: Optional[str] = None
    expires_in_days: int = Field(30, ge=1, le=365)
    # mode per_machine : une entrée par machine (N players pré-créés + N tokens max_uses=1)
    entries: list[ProvisioningBatchEntry] = Field(default_factory=list)
    # mode shared : 1 token max_uses=count (players créés à la volée, nommés côté terrain)
    ref: Optional[str] = None                        # libellé de base du token partagé
    count: Optional[int] = Field(None, ge=1, le=500)
    # mode shared : config COMMUNE appliquée à toutes les machines du lot (Wi-Fi/DHCP/résolution ;
    # les IP statiques par player exigent le mode per_machine — assignation machine↔entrée inconnue).
    network: Optional[NetworkConfig] = None
    options: Optional[dict] = None


class ProvisioningBatch(BaseModel):
    """Bundle de lot renvoyé au CMS ; le frontend l'aplatit en `signflow-config.json` v2."""
    version: int = 2
    mode: Literal["per_machine", "shared"]
    os: str
    backend_url: str
    # per_machine : un payload complet par machine (ref/token/réseau)
    players: list[ProvisioningPayload] = Field(default_factory=list)
    # shared : un seul token à usage multiple (+ config commune éventuelle)
    token: Optional[str] = None
    count: Optional[int] = None
    ref: Optional[str] = None
    id_key: Optional[int] = None
    network: Optional[NetworkConfig] = None
    options: Optional[dict] = None
