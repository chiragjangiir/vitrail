"""Schémas VOD à la demande (Feature B, Phase 1)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

# Modes de ciblage d'une config VOD (migr 0096). En Literal — et pas en str libre — pour que
# `{"target_mode": "sites"}` réponde 422 au lieu d'être avalé et de ne cibler personne
# (leçon de l'audit du 2026-07-18 sur les cibles silencieusement ignorées).
VodTargetMode = Literal["players", "site"]


class VodConfigCreate(BaseModel):
    vod_name: str
    description: Optional[str] = None
    # Médias visuels (vidéo/image/document) à pré-cacher. Ordre préservé.
    id_medias: list[int] = []
    # Ciblage : 'players' = liste figée ci-dessous (défaut, historique) ;
    #           'site'    = TOUS les players de `id_site`, résolus dynamiquement.
    target_mode: VodTargetMode = "players"
    # Players cibles — DOIVENT partager le même id_site (validé à la création).
    # Ignoré (et vidé) en mode 'site'.
    id_players: list[int] = []
    # Site cible — OBLIGATOIRE en mode 'site', ignoré en mode 'players' (déduit des players).
    id_site: Optional[int] = None
    # Gouvernance §XVIII (migr 0112) : nœud propriétaire. None = config d'organisation.
    id_governance_node: Optional[int] = None


class VodConfigUpdate(BaseModel):
    vod_name: Optional[str] = None
    description: Optional[str] = None
    id_medias: Optional[list[int]] = None
    target_mode: Optional[VodTargetMode] = None
    id_players: Optional[list[int]] = None
    id_site: Optional[int] = None
    # `model_fields_set` distingue « non fourni » de « détaché (null) » : le second est
    # réservé à un admin d'un nœud PARENT (N2).
    id_governance_node: Optional[int] = None


class VodMediaItem(BaseModel):
    id_media: int
    media_name: Optional[str] = None
    media_type: Optional[str] = None
    sort_order: int = 0


class VodPlayerItem(BaseModel):
    id_player: int
    player_name: Optional[str] = None
    player_status: Optional[str] = None
    id_site: Optional[int] = None


class PlayNowRequest(BaseModel):
    """Déclenchement cloud d'une lecture ad-hoc (takeover) — trigger CLOUD §Phase 2."""
    id_media: int
    mode: str = "once"  # once | loop
    # Sous-ensemble de players de la config ; None/[] = tous les players de la config.
    id_players: Optional[list[int]] = None
    # Son du takeover, choisi à CHAQUE déclenchement (décision Ed 2026-07-19). Avant, le
    # player forçait le son, ignorant `display_config.content_sound` — l'opérateur sait au
    # moment du clic s'il veut être entendu. True = comportement historique préservé.
    with_sound: bool = True


class PlayNowResult(BaseModel):
    id_media: int
    mode: str
    dispatched: list[int]  # players ayant reçu la commande


class VodConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_vod: int
    id_org: int
    id_site: Optional[int] = None
    site_name: Optional[str] = None
    target_mode: VodTargetMode = "players"
    vod_name: str
    description: Optional[str] = None
    id_governance_node: Optional[int] = None
    medias: list[VodMediaItem] = []
    # Players RÉSOLUS de la cible : liste explicite en mode 'players', tous les players du
    # site en mode 'site' (donc toujours l'ensemble réellement pré-caché/déclenchable).
    players: list[VodPlayerItem] = []
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
