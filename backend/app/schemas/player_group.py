from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PlayerGroupCreate(BaseModel):
    group_name: str
    # content | audio | mixed
    group_type: str = "content"
    description: Optional[str] = None


class PlayerGroupUpdate(BaseModel):
    group_name: Optional[str] = None
    group_type: Optional[str] = None
    description: Optional[str] = None


class PlayerGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_group: int
    id_org: int
    group_name: str
    group_type: str = "content"
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Agrégat peuplé par l'endpoint liste (pas une colonne) — sert aux sélecteurs de
    # cible à filtrer les groupes par capacité des membres (ex. campagnes audio).
    player_ids: list[int] = []


class PlayerGroupMemberAdd(BaseModel):
    id_player: int


class PlayerStatsRead(BaseModel):
    total: int
    online: int
    offline: int
    warning: int
