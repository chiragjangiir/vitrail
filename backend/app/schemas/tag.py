from typing import Optional

from pydantic import BaseModel


# ── Namespaces ────────────────────────────────────────────────────────────────

class NamespaceCreate(BaseModel):
    namespace_key: str
    label: Optional[str] = None
    match_mode: str = "any"
    applies_to: list[str] = []


class NamespaceUpdate(BaseModel):
    label: Optional[str] = None
    match_mode: Optional[str] = None
    applies_to: Optional[list[str]] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class TagValueRead(BaseModel):
    model_config = {"from_attributes": True}

    id_tag: int
    id_namespace: int
    tag_value: str
    label: Optional[str] = None
    color: Optional[str] = None
    sort_order: int


class NamespaceRead(BaseModel):
    model_config = {"from_attributes": True}

    id_namespace: int
    id_org: int
    namespace_key: str
    label: Optional[str] = None
    match_mode: str
    applies_to: list[str]
    is_system: bool
    is_active: bool
    sort_order: int


class NamespaceWithValues(NamespaceRead):
    values: list[TagValueRead] = []


# ── Valeurs ───────────────────────────────────────────────────────────────────

class TagValueCreate(BaseModel):
    tag_value: str
    label: Optional[str] = None
    color: Optional[str] = None
    sort_order: int = 0


class TagValueUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


# ── Tagging ───────────────────────────────────────────────────────────────────

class IdTagList(BaseModel):
    """Body pour PUT media/{id}/tags et PUT players/{id}/tag-filters."""
    id_tags: list[int] = []


class BulkTagRequest(BaseModel):
    id_media: list[int]
    id_tags: list[int]
    mode: str = "add"  # add | replace


class PlaylistItemTagsUpdate(BaseModel):
    tags: list[int] = []
    ns_overrides: list[int] = []  # ids de namespaces en mode override


class PlaylistItemTagsRead(BaseModel):
    tags: list[int] = []
    ns_overrides: list[int] = []
    # tags effectifs (union média + item après override), pour l'affichage éditeur
    effective: dict[str, list[str]] = {}


# ── Fallback (§XVII.5) ─────────────────────────────────────────────────────────

class FallbackConfig(BaseModel):
    model_config = {"from_attributes": True}

    fallback_audio_id: Optional[int] = None
    fallback_video_message: Optional[str] = None
    fallback_video_config: dict = {}


class FallbackConfigUpdate(BaseModel):
    fallback_audio_id: Optional[int] = None
    fallback_video_message: Optional[str] = None
    fallback_video_config: Optional[dict] = None


# ── Simulation (§XVII.7) ────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    player_ids: list[int]


class SimulateItem(BaseModel):
    id_item: int
    id_media: int
    media_name: Optional[str] = None
    matched: bool


class SimulatePlayerResult(BaseModel):
    id_player: int
    player_name: Optional[str] = None
    items: list[SimulateItem] = []
