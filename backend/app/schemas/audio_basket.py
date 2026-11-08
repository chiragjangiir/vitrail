from datetime import datetime, time
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Baskets ──────────────────────────────────────────────────────────────────

class AudioBasketCreate(BaseModel):
    basket_name: str
    # music | message | jingle | ambiance | emergency
    basket_type: str
    # national | regional | local | style
    basket_scope: str = "local"
    description: Optional[str] = None
    is_mandatory: bool = False
    min_ratio: int = 0
    max_ratio: int = 100
    # {"enabled":bool,"target_pct":int,"fade_in_ms":int,"fade_out_ms":int}
    ducking_config: dict[str, Any] = Field(default_factory=dict)
    # Récurrence jingle : mode 'tracks'|'minutes' + valeur
    trigger_mode: str = "tracks"
    trigger_value: int = 5
    # Lecture en ordre aléatoire (paniers Music)
    shuffle: bool = False
    id_node: Optional[int] = None


class AudioBasketUpdate(BaseModel):
    basket_name: Optional[str] = None
    basket_type: Optional[str] = None
    basket_scope: Optional[str] = None
    description: Optional[str] = None
    is_mandatory: Optional[bool] = None
    min_ratio: Optional[int] = None
    max_ratio: Optional[int] = None
    ducking_config: Optional[dict[str, Any]] = None
    trigger_mode: Optional[str] = None
    trigger_value: Optional[int] = None
    shuffle: Optional[bool] = None
    is_active: Optional[bool] = None
    # Rattachement à un nœud de gouvernance (§XVIII). null = portée globale org.
    id_node: Optional[int] = None


class AudioBasketRead(BaseModel):
    model_config = {"from_attributes": True}

    id_basket: int
    id_org: int
    id_node: Optional[int] = None
    basket_name: str
    basket_type: str
    basket_scope: str
    description: Optional[str] = None
    is_mandatory: bool
    min_ratio: int
    max_ratio: int
    ducking_config: dict[str, Any]
    trigger_mode: str = "tracks"
    trigger_value: int = 5
    shuffle: bool = False
    is_active: bool
    # Enrichis par l'endpoint liste : nombre d'items + durée totale des pistes
    # (somme des durées natives connues ; null si aucune durée extraite).
    item_count: int = 0
    total_duration_ms: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# ── Basket items ─────────────────────────────────────────────────────────────

class BasketItemCreate(BaseModel):
    id_media: int
    weight: int = 1
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    sort_order: int = 0
    # Règle de diffusion récurrente (heure locale) : jours (0=Lun..6=Dim) + créneau.
    rule_days: Optional[list[int]] = None
    rule_time_start: Optional[time] = None
    rule_time_end: Optional[time] = None


class BasketItemsBulkCreate(BaseModel):
    """Ajout multi-sélection depuis le drawer de recherche (parité avec les playlists)."""
    id_medias: list[int] = Field(min_length=1, max_length=200)


class BasketItemUpdate(BaseModel):
    """Mise à jour partielle d'un item (poids, validité absolue, règle récurrente)."""
    weight: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    rule_days: Optional[list[int]] = None
    rule_time_start: Optional[time] = None
    rule_time_end: Optional[time] = None


class BasketItemRead(BaseModel):
    model_config = {"from_attributes": True}

    id_item: int
    id_basket: int
    id_media: int
    # Enrichis par l'endpoint
    media_name: Optional[str] = None
    media_type: Optional[str] = None
    duration_ms: Optional[int] = None
    weight: int
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    rule_days: Optional[list[int]] = None
    rule_time_start: Optional[time] = None
    rule_time_end: Optional[time] = None
    is_active: bool
    sort_order: int


# ── Player basket config ─────────────────────────────────────────────────────

class PlayerBasketConfigItem(BaseModel):
    id_basket: int
    mix_ratio: int = 50
    is_active: bool = True


class PlayerBasketConfigRead(BaseModel):
    model_config = {"from_attributes": True}

    id_player: int
    id_basket: int
    basket_name: Optional[str] = None
    basket_type: Optional[str] = None
    mix_ratio: int
    is_active: bool
    activated_at: datetime
