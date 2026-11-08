from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChannelCreate(BaseModel):
    name: str
    channel_type: str = "webhook"     # webhook | email (2026-07-12)
    config: dict = {}                 # webhook: {url} ; email: {recipients: [...]}
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class ChannelRead(BaseModel):
    id_channel: int
    name: str
    channel_type: str
    config: dict
    enabled: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RuleCreate(BaseModel):
    event_type: str
    id_channel: int
    params: dict = {}
    enabled: bool = True


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    id_channel: int | None = None


class RuleRead(BaseModel):
    id_rule: int
    event_type: str
    id_channel: int
    params: dict
    enabled: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NotificationLogRead(BaseModel):
    id_log: int
    id_rule: int | None = None
    event_type: str
    subject: str | None = None
    status: str
    detail: str | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
