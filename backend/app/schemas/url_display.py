"""Schémas URL Display (§XXV.2) — « Site Web » comme contenu schedulable.

Un url_display est stocké comme un `cms_media` (`media_type='url_display'`, sans fichier) :
l'URL + la config webview vivent dans `media_metadata`. Cf. docs/SPIKE_url_display.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class UrlDisplayConfig(BaseModel):
    """Config de rendu webview (hors URL elle-même)."""

    # webview = le player rend la page en iframe ; screenshot_server = le serveur capture la page
    # avec Playwright et le player affiche l'image (sites non-framables + écrans faibles).
    render_mode: Literal["webview", "screenshot_server"] = "webview"
    # 0 = pas de rechargement auto ; sinon la page est rechargée toutes les N secondes.
    refresh_interval_s: int = Field(default=0, ge=0, le=86400)
    zoom: float = Field(default=1.0, gt=0.1, le=5.0)
    scroll_mode: Literal["none", "auto", "infinite"] = "none"
    scroll_speed_px_s: int = Field(default=50, ge=1, le=2000)
    interaction_blocked: bool = True
    custom_css: str = ""
    hide_selectors: list[str] = Field(default_factory=list)
    # Sonde d'accès au site (player) : inaccessible → skip de l'item + alerte serveur.
    reachability_enabled: bool = True
    reachability_timeout_s: int = Field(default=8, ge=1, le=60)


class UrlDisplayCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1)
    config: UrlDisplayConfig = Field(default_factory=UrlDisplayConfig)

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith("https://"):
            # HTTP en clair bloqué (§25.2 Sécurité). Whitelist admin = évolution future.
            raise ValueError("URL must use https://")
        return v


class UrlDisplayUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    url: Optional[str] = None
    config: Optional[UrlDisplayConfig] = None

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v.lower().startswith("https://"):
            raise ValueError("URL must use https://")
        return v


class UrlDisplayRead(BaseModel):
    id_media: int
    name: str
    url: str
    config: UrlDisplayConfig
    created_at: datetime
    updated_at: datetime
