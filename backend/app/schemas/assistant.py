"""Schémas de l'AI Assistant (§XXVII)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    page_context: dict | None = None
    # Locale de réponse forcée ; à défaut on prend celle de l'utilisateur (JWT/DB).
    locale: str | None = None
    # Reprise d'une session existante (sinon une nouvelle est créée).
    session_id: int | None = None


class ActionExecuteRequest(BaseModel):
    # Token signé d'une action préparée par l'agent (frame SSE `action`).
    token: str
