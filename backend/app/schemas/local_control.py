from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LocalControlProfileCreate(BaseModel):
    """Options de génération d'un profil d'accès local (Store Control Panel §19.3)."""

    role: str = "CMS_STORE_OPERATOR"
    # NULL/absent = tous les paniers actifs du player
    allowed_basket_ids: Optional[list[int]] = None
    can_edit_ratio: bool = False
    can_set_volume: bool = True
    can_trigger_event: bool = False
    # Durée de validité du profil/QR en heures. 0 = permanent (étiquette collée
    # sur le player, scannée à la demande). Max 1 an. (§19.3)
    validity_hours: int = Field(default=4, ge=0, le=8760)


class LocalControlProfileRead(BaseModel):
    model_config = {"from_attributes": True}

    id_profile: int
    id_player: int
    role: str
    allowed_basket_ids: Optional[list[int]] = None
    can_edit_ratio: bool
    can_set_volume: bool
    can_trigger_event: bool
    expires_at: Optional[datetime] = None
    revoked: bool
    created_at: datetime
    # Token + URL LAN (pour ré-afficher le QR) — enrichis par l'endpoint
    token: Optional[str] = None
    lan_url: Optional[str] = None
