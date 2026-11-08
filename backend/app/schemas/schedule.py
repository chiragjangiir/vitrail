from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel


class ScheduleRuleCreate(BaseModel):
    # always | weekly | date_range
    rule_type: str = "weekly"
    days_of_week: Optional[list[int]] = None  # 0=Lun … 6=Dim
    time_start: Optional[time] = None
    time_end: Optional[time] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ScheduleRuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id_rule: int
    id_schedule: int
    rule_type: str
    days_of_week: Optional[list[int]]
    time_start: Optional[time]
    time_end: Optional[time]
    date_from: Optional[date]
    date_to: Optional[date]


# Cibles de schedule réellement honorées par les chemins player-centriques (ws.py sync,
# prefetch, inventaire, simulation). Volontairement un Literal et non un `str` libre :
# jusqu'au 2026-07-18, `target_type` acceptait n'importe quelle valeur — une cible `site`
# était enregistrée et comptée dans l'aperçu, mais JAMAIS diffusée (aucune erreur).
# Tout nouveau type doit être ajouté ICI **et** dans les résolveurs player-centriques.
ScheduleTargetType = Literal["player", "player_group", "site", "site_group"]


class ScheduleTargetCreate(BaseModel):
    target_type: ScheduleTargetType
    target_id: int


class ScheduleTargetRead(BaseModel):
    model_config = {"from_attributes": True}

    id_target: int
    id_schedule: int
    target_type: str  # lecture = str brut (tolère d'anciennes lignes hors vocabulaire)
    target_id: int


class HdmiCompatCheckRequest(BaseModel):
    """Check d'affectation HDMI-in : la playlist contient-elle un item « entrée HDMI », et
    quelles cibles ne pourront jamais le diffuser (pas d'entrée HDMI physique) ?"""
    id_playlist: int
    targets: list[ScheduleTargetCreate] = []


class HdmiIncompatiblePlayer(BaseModel):
    id_player: int
    player_name: Optional[str] = None


class HdmiCompatCheckResult(BaseModel):
    has_hdmi_item: bool
    incompatible_players: list[HdmiIncompatiblePlayer] = []


class GovernanceScopeRequest(BaseModel):
    """D-b : périmètre effectif d'un programme gouverné (nœud ∩ cibles), avant enregistrement."""
    id_governance_node: int
    targets: list[ScheduleTargetCreate] = []


class GovernanceScopePlayer(BaseModel):
    id_player: int
    player_name: Optional[str] = None


class GovernanceScopeTarget(BaseModel):
    target_type: str
    target_id: int
    target_name: Optional[str] = None


class GovernanceScopeLanSplit(BaseModel):
    """Groupe de synchro LAN coupé en deux par ce ciblage (D4 : on avertit, on ne bloque pas)."""
    group: str
    kept: list[str] = []
    excluded: list[str] = []


class GovernanceScopeResult(BaseModel):
    node_name: str
    perimeter_count: int       # écrans du nœud et de son sous-arbre
    resolved_count: int        # écrans réellement retenus (= périmètre si aucune cible, D0)
    target_count: int
    players: list[GovernanceScopePlayer] = []
    out_of_scope: list[GovernanceScopeTarget] = []  # cibles ne retenant AUCUN écran (D3 → 422)
    lan_sync_split: list[GovernanceScopeLanSplit] = []


class ScheduleBasketItem(BaseModel):
    """Panier d'un schedule audio (programme multi-paniers)."""
    id_basket: int
    mix_ratio: int = 50


class ScheduleBasketRead(ScheduleBasketItem):
    model_config = {"from_attributes": True}
    basket_name: Optional[str] = None
    basket_type: Optional[str] = None


class ScheduleCreate(BaseModel):
    schedule_name: str
    # content (playlist visuelle) | audio (paniers audio §XIX)
    schedule_kind: str = "content"
    id_playlist: Optional[int] = None       # requis si content
    baskets: list[ScheduleBasketItem] = []  # requis si audio (≥1)
    # Nœud de gouvernance propriétaire (§XVIII). NULL = pas de contrainte (défaut).
    id_governance_node: Optional[int] = None
    priority: int = 0
    # Plage de validité (dates début/fin, heure locale) — NULL = borne ouverte.
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    rules: list[ScheduleRuleCreate] = []
    targets: list[ScheduleTargetCreate] = []


class ScheduleUpdate(BaseModel):
    schedule_name: Optional[str] = None
    id_playlist: Optional[int] = None
    baskets: Optional[list[ScheduleBasketItem]] = None
    # Nœud de gouvernance (model_fields_set distingue « non fourni » de « détaché à null »).
    id_governance_node: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    # Plage de validité (model_fields_set distingue « non fourni » de « effacé à null »).
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    rules: Optional[list[ScheduleRuleCreate]] = None


class ScheduleRead(BaseModel):
    model_config = {"from_attributes": True}

    id_schedule: int
    id_org: int
    schedule_name: str
    schedule_kind: str
    id_playlist: Optional[int] = None
    # Nom résolu par le SERVEUR : le client le déduisait de sa liste de playlists,
    # plafonnée à 50 — au-delà, la vignette affichait « #id » (audit menu ⑧).
    playlist_name: Optional[str] = None
    id_governance_node: Optional[int] = None
    priority: int
    is_active: bool
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    # Règles de récurrence (always / weekly) — peuplées par la liste pour la vue calendrier.
    rules: list[ScheduleRuleRead] = []


class ScheduleDetail(ScheduleRead):
    targets: list[ScheduleTargetRead] = []
    baskets: list[ScheduleBasketRead] = []


# ── Simulation journée d'un player (programmation complète) ──────────────────
class PlayerDaySimRequest(BaseModel):
    date: str  # YYYY-MM-DD (jour LOCAL de l'écran, cf. PlayerDaySimResult.timezone)


class DaySimVideoSegment(BaseModel):
    start: str            # "HH:MM"
    end: str
    source: str           # schedule | event
    name: str             # nom du programme / de l'event
    id_playlist: Optional[int] = None
    playlist_name: Optional[str] = None
    priority: int = 0


class DaySimBasket(BaseModel):
    id_basket: int
    name: str
    basket_type: str       # music | ambiance | jingle (message/emergency exclus de la sim)
    ratio: int             # % de mix pour music/ambiance (non pertinent pour jingle)
    source: str            # schedule | event
    # Cadence des jingles (trigger_mode = tracks | minutes ; trigger_value = N)
    trigger_mode: Optional[str] = None
    trigger_value: Optional[int] = None


class DaySimAudioSegment(BaseModel):
    start: str
    end: str
    baskets: list[DaySimBasket] = []


class PlayerDaySimResult(BaseModel):
    id_player: int
    date: str
    # Fuseau dans lequel les horaires ci-dessous se lisent = celui du SITE de l'écran
    # (P2.2). Sans lui, « 12:00 » est ambigu dès qu'un parc traverse deux fuseaux.
    timezone: str
    video: list[DaySimVideoSegment] = []
    audio: list[DaySimAudioSegment] = []


class CurrentScheduleResponse(BaseModel):
    id_player: int
    id_schedule: Optional[int]
    id_playlist: Optional[int]
    playlist_name: Optional[str]
    schedule_name: Optional[str]
    priority: Optional[int]
    resolved_at: datetime
    # Fuseau dans lequel `resolved_at` se lit — celui du site de l'écran (P2.2).
    timezone: str
