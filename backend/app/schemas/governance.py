from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Nœuds ─────────────────────────────────────────────────────────────────────

class NodeCreate(BaseModel):
    node_name: str
    parent_id: Optional[int] = None
    node_type: Optional[str] = None
    # D7 : None = hérite du parent (true si racine). Sinon valeur explicite.
    requires_approval: Optional[bool] = None


class NodeUpdate(BaseModel):
    node_name: Optional[str] = None
    node_type: Optional[str] = None
    # P3 (revue 2026-07-23) : re-parentage. `model_fields_set` distingue « non fourni » de
    # « None explicite » = faire du nœud une RACINE (réservé à l'org-admin). Le `path` et les
    # niveaux de tout le sous-arbre sont recalculés côté serveur.
    parent_id: Optional[int] = None
    # Restrictions d'écriture des règles, par famille ({"preemptive": false, …}). Les familles
    # absentes du dict ne sont pas touchées. LEVER une restriction est réservé à un ancêtre
    # STRICT (403 sinon) ; la reposer est permis à tout éditeur du nœud (durcir est toujours
    # permis, comme pour `requires_approval`).
    rules_locked: Optional[dict[str, bool]] = None
    # Plafonds imposés aux descendants. `None` explicite = retirer le plafond.
    max_for_children: Optional[int] = None
    max_item_sec: Optional[int] = None
    # D7 : décocher (→ false) est réservé à un admin d'ANCÊTRE (ou org-admin).
    requires_approval: Optional[bool] = None


class NodeRead(BaseModel):
    model_config = {"from_attributes": True}

    id_node: int
    id_org: int
    parent_id: Optional[int] = None
    node_name: str
    node_level: int
    node_type: Optional[str] = None
    path: str
    requires_approval: bool = True
    # Restrictions posées SUR CE NŒUD, par famille (clé absente = restreinte).
    rules_locked: dict[str, bool] = {}
    # Plafonds que ce nœud impose à ses descendants (None = aucun).
    max_for_children: Optional[int] = None
    max_item_sec: Optional[int] = None
    created_at: datetime
    child_count: int = 0
    # Contenu gouverné (D6/D9) : l'utilisateur courant peut-il ÉCRIRE sur ce nœud ?
    # Le front s'en sert pour n'offrir que des nœuds réellement assignables dans les
    # sélecteurs playlist/média (un nœud ancêtre est visible mais en lecture seule).
    can_edit: bool = True


# ── Assignations ─────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    target_type: str  # player | group | site
    target_id: int


class AssignmentRead(BaseModel):
    target_type: str
    target_id: int
    target_name: Optional[str] = None


# ── Administrateurs de nœud (immutabilité §XVIII Phase 2) ────────────────────

class NodeAdminCreate(BaseModel):
    id_user: int


class NodeAdminRead(BaseModel):
    id_user: int
    email: str
    full_name: Optional[str] = None


# ── Règles de délégation ─────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    rule_type: str
    params: dict = {}
    soft_cut: bool = True


class RuleUpdate(BaseModel):
    params: Optional[dict] = None
    soft_cut: Optional[bool] = None
    is_active: Optional[bool] = None


class RuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id_rule: int
    id_node: int
    rule_type: str
    params: dict
    soft_cut: bool
    is_active: bool
    created_at: datetime


# ── Détail ───────────────────────────────────────────────────────────────────

class NodeDetail(NodeRead):
    children: list[NodeRead] = []
    rules: list[RuleRead] = []
    assignments: list[AssignmentRead] = []
    admins: list[NodeAdminRead] = []
    # D7 : l'utilisateur peut-il RETIRER la modération de ce nœud (admin d'un ancêtre
    # strict / org-admin) ? Le front grise la case au lieu de laisser tomber en 403.
    can_disable_moderation: bool = False
    # Restrictions EFFECTIVES par famille (OU sur le nœud et tous ses ancêtres) : une case
    # décochée localement ne sert à rien si un ancêtre l'a posée. C'est cette valeur-là que
    # l'écran doit montrer, pas la case brute.
    rules_locked_effective: dict[str, bool] = {}
    # Familles dont la restriction est posée PLUS HAUT (le nœud ne peut donc rien y changer) :
    # sans ça, l'écran ne saurait pas distinguer « verrouillé ici » de « verrouillé au-dessus »,
    # et afficherait une case décochée sur un paramètre pourtant inaccessible.
    rules_locked_above: dict[str, bool] = {}
    # L'utilisateur courant peut-il écrire les règles de ce nœud, PAR FAMILLE, et changer les
    # cases ? (le front grise plutôt que de laisser tomber en 403)
    can_edit_rule_types: dict[str, bool] = {}
    can_set_rules_delegation: bool = False
    # Plafonds hérités des ancêtres, pour borner les champs à la saisie.
    inherited_max_per_turn: Optional[int] = None
    inherited_max_item_sec: Optional[int] = None


# ── Compilation §XVIII Phase 2 ───────────────────────────────────────────────

class CompiledItemRead(BaseModel):
    id_media: int
    media_name: str
    media_type: str
    duration_ms: int
    id_node: int
    id_schedule: int


class LayerReportRead(BaseModel):
    id_node: int
    node_name: str
    node_level: int
    id_schedule: int
    priority: int
    status: str            # active | preempted | outside_time_window
    item_count: int
    sec: float
    budget_trimmed: bool
    budget_overflow: bool
    # Contenus écartés faute de tenir dans la durée maximale par contenu (nommés, jamais
    # retirés en silence).
    dropped_too_long: list[str] = []


class ContentRateRead(BaseModel):
    """Taux de passage d'un contenu — ce que l'admin du nœud doit voir AVANT de valider ses
    règles (« l'admin fait sa configuration et on lui montre le taux de passage », Ed)."""

    id_media: int
    media_name: str
    id_node: int
    node_name: str
    plays_per_cycle: int
    # Intervalle moyen entre deux passages : l'unité avec laquelle on raisonne vraiment
    # (« toutes les 11 minutes »), bien plus parlante qu'un pourcentage d'antenne.
    interval_ms: int
    plays_per_day: float
    airtime_pct: float


class CompiledScheduleRead(BaseModel):
    id_player: int
    resolved_at: str
    cycle_duration_ms: int
    # Nombre de TOURS du cycle : un tour = une boucle vue à l'écran. L'aperçu les affiche
    # un par un — 72 items à plat étaient illisibles (retour Ed).
    turns: int = 1
    # Cycle réduit par le garde-fou : certains contenus passent alors MOINS souvent que la
    # configuration ne l'annonce. À dire à l'écran, pas seulement dans un log.
    truncated: bool = False
    # Heures d'ouverture retenues pour « passages par jour » (24 h si le site n'en déclare pas).
    open_hours_per_day: float = 24.0
    contents: list["ContentRateRead"] = []
    layers: list[LayerReportRead] = []
    items: list[CompiledItemRead] = []
    # R10 : quand `layers` est vide, POURQUOI. no_node | no_schedule | schedule_inactive |
    # no_playlist | no_rule | outside_window. `empty_detail` = nom du programme concerné.
    empty_reason: Optional[str] = None
    empty_detail: Optional[str] = None


class BudgetStatusRead(BaseModel):
    id_node: int
    used_sec: float
    budget_sec: Optional[int] = None
    remaining_sec: Optional[float] = None
    items_used: int
    items_budget: Optional[int] = None
