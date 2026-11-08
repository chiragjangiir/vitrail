"""Recherche globale (barre topbar) — résultats cross-entités groupés."""

from __future__ import annotations

from pydantic import BaseModel


class SearchHit(BaseModel):
    id: int
    label: str
    sublabel: str | None = None
    href: str


class SearchGroup(BaseModel):
    # media | playlist | campaign | player | site | template | event
    kind: str
    items: list[SearchHit] = []


class SearchResponse(BaseModel):
    query: str
    groups: list[SearchGroup] = []
