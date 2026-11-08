"""Schémas des retours utilisateurs (feedback)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackType = Literal["bug", "suggestion", "amelioration", "ux", "question"]
FeedbackStatus = Literal["new", "triaged", "planned", "in_progress", "done", "rejected"]


class FeedbackCreate(BaseModel):
    feedback_type: FeedbackType
    description: str = Field(..., min_length=1, max_length=4000)
    page_url: str | None = None
    route: str | None = None
    user_agent: str | None = None
    app_version: str | None = None
    console_errors: list[str] = []
    screenshot_keys: list[str] = Field(default=[], max_length=8)
    severity: int | None = Field(default=None, ge=1, le=3)


class FeedbackRead(BaseModel):
    model_config = {"from_attributes": True}

    id_feedback: int
    id_org: int
    id_user: int
    feedback_type: str
    description: str
    page_url: str | None = None
    route: str | None = None
    user_agent: str | None = None
    app_version: str | None = None
    console_errors: list = []
    screenshot_keys: list[str] = []
    severity: int | None = None
    status: str
    admin_note: str | None = None
    ai_category: str | None = None
    ai_severity: int | None = None
    ai_summary: str | None = None
    ai_processed_at: datetime | None = None
    created_at: datetime
    # Enrichis par l'endpoint admin (cross-org).
    org_name: str | None = None
    author_email: str | None = None
    screenshot_urls: list[str] = []  # URLs pré-signées MinIO des captures (admin)


class FeedbackUpdate(BaseModel):
    status: FeedbackStatus | None = None
    admin_note: str | None = None
