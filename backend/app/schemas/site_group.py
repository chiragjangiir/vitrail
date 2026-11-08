from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SiteGroupCreate(BaseModel):
    group_name: str
    description: Optional[str] = None


class SiteGroupUpdate(BaseModel):
    group_name: Optional[str] = None
    description: Optional[str] = None


class SiteGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_site_group: int
    id_org: int
    group_name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Agrégats peuplés par l'endpoint (pas des colonnes)
    site_count: int = 0
    player_count: int = 0
    site_ids: list[int] = []


class SiteGroupMemberAdd(BaseModel):
    id_site: int
