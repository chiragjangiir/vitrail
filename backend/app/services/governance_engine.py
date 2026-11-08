"""
Gouvernance §XVIII Phase 2 — Moteur de compilation de programme (logique PURE).

Compile un **programme fusionné** par player en empilant les couches (schedules rattachés
aux nœuds de gouvernance qui visent le player), triées par bande de priorité (national→local),
sous contraintes des règles de délégation (`cms_delegation_rules`).

Modèle **déterministe** (décision actée) : le budget est appliqué *structurellement* en
compilant le cycle ; aucun compteur runtime. Les players restent sans état (cohérent wall-clock).
`budget-status` = consommation **planifiée** du cycle compilé.

Le noyau (`services/scheduling.py` + `services/targeting.py`) fournit les prédicats *qui + quand* ;
ce module fournit l'**arbitrage** (combien + qui gagne). Sans I/O DB → testable unitairement.
L'orchestration async (collecte des couches en base) vit dans `endpoints/governance.py`.

Convention `time_budget` (décision D1, 2026-07-24 — **volume absolu par cycle**) : un nœud reçoit
`sec_per_cycle` secondes d'antenne **par cycle compilé**, indépendamment de ce que produisent les
autres couches. Au-delà, on rogne les items de queue du nœud. `soft_cut=true` (défaut) : l'item qui
déborde reste (overflow loggué) ; `false` : il est retiré.
    Ancien modèle (jusqu'au 2026-07-24) : `sec_per_hour × cycle_total_sec / 3600`, où
`cycle_total_sec` sommait **toutes** les couches → ajouter du contenu ailleurs modifiait le quota
absolu de chacun (dé-rognage du parent, R13). Corrigé : la référence est désormais fixe (le budget
lui-même), plus le cycle total. Migration 0104 = renommage du paramètre `sec_per_hour → sec_per_cycle`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as time_cls
import logging
from math import lcm
from typing import Optional

from app.services.playlist_rotation import (
    MAX_UNROLL_TURNS,
    build_turn_selections,
    rotation_seed,
    rotation_turns,
)
from app.services.scheduling import TimeRule, rule_active_at

logger = logging.getLogger(__name__)

# Plafond d'items du cycle compilé (pendant du `cap_items` de la rotation de playlist) :
# au-delà, on réduit le nombre de tours plutôt que d'envoyer un payload démesuré.
_MAX_CYCLE_ITEMS = 600


# ── Données ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompiledItem:
    """Item placé dans le programme compilé, avec sa provenance (couche)."""

    id_media: int
    media_name: str
    media_type: str
    duration_ms: int
    id_node: int
    id_schedule: int
    # « Pas de publicité entre les contenus » (`cms_playlists.no_ads_inside`) : posé par
    # le déroulé de rotation sur tout le bloc SAUF son 1er item, pour que l'injection
    # Retail Media ne coupe jamais un bloc protégé. Propagé au payload player.
    no_ad_before: bool = False


@dataclass
class DelegationConstraints:
    """Règles de délégation d'un nœud agrégées en un objet typé (cf. §18.3)."""

    preemptive: bool = False
    time_window: Optional[TimeRule] = None
    # `item_count` = nombre d'items du nœud diffusés PAR TOUR de boucle, **en rotation**
    # (décision Ed 2026-07-26). Avant, c'était une troncature — `items[:N]` — donc toujours
    # les N MÊMES items : « il faut passer TOUS ses contenus, pas seulement les 2 premiers ».
    item_count: Optional[int] = None                 # max_per_cycle = N par tour
    rotation_mode: str = "one_sequential"            # one_sequential | one_random
    # Plafond imposé aux DESCENDANTS (« le département peut monter jusqu'à 4 ») : un nœud ne
    # peut pas se donner un `item_count` supérieur au plus petit plafond de ses ancêtres.
    # Porté par la règle du PARENT, jamais par celle du nœud contraint (sinon il le lèverait).
    max_for_children: Optional[int] = None
    # Durée maximale d'UN contenu (secondes). Le « N par tour » compte des items, pas du
    # temps : sans ce plafond, une compilation de 3 h livrée en UN fichier accapare la boucle
    # (attaque décrite par Ed le 2026-07-26). ⚠️ `time_budget` seul ne suffit pas — son mode
    # par défaut `soft_cut` termine l'item qui déborde. Un contenu au-dessus est ÉCARTÉ et
    # SIGNALÉ (jamais retiré en silence : c'est la classe de bug qu'on passe la journée à tuer).
    max_item_sec: Optional[int] = None
    time_budget_sec_per_cycle: Optional[int] = None  # sec_per_cycle (volume absolu / cycle, D1)
    soft_cut: bool = True                            # du time_budget (défaut terminer l'item)


@dataclass
class LayerInput:
    """Une couche candidate = un schedule actif rattaché à un nœud, avec ses items bruts."""

    id_node: int
    node_name: str
    node_level: int
    id_schedule: int
    priority: int
    constraints: DelegationConstraints
    items: list[CompiledItem] = field(default_factory=list)  # ordonnés (sort_order)


@dataclass
class LayerReport:
    """Diagnostic d'une couche après compilation (pour l'UI / debug)."""

    id_node: int
    node_name: str
    node_level: int
    id_schedule: int
    priority: int
    status: str            # active | preempted | outside_time_window
    item_count: int = 0    # items réellement contribués
    sec: float = 0.0       # secondes contribuées
    budget_trimmed: bool = False
    budget_overflow: bool = False
    # Contenus écartés parce qu'ils dépassent la durée maximale par contenu (avec leurs noms,
    # pour que l'écran de configuration puisse DIRE lesquels et pourquoi).
    dropped_too_long: list[str] = field(default_factory=list)


@dataclass
class CompiledProgram:
    items: list[CompiledItem]
    layers: list[LayerReport]
    cycle_duration_ms: int
    # Nombre de TOURS du cycle (PPCM des rotations de chaque couche). Un tour = une boucle
    # vue à l'écran ; le cycle en enchaîne `turns` avant de se répéter à l'identique.
    turns: int = 1
    # Cycle RÉDUIT par le garde-fou (cardinalités premières entre elles) : certains contenus
    # passent alors moins souvent que la configuration ne le laisse croire → à signaler à
    # l'écran, pas seulement dans un log.
    truncated: bool = False


# ── Parsing des règles ───────────────────────────────────────────────────────

def _parse_time(s) -> Optional[time_cls]:
    if not s:
        return None
    try:
        h, m = (int(x) for x in str(s).split(":")[:2])
        return time_cls(h, m)
    except (ValueError, TypeError):
        return None


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def parse_constraints(rules) -> DelegationConstraints:
    """Agrège des lignes `cms_delegation_rules` (actives) en `DelegationConstraints`.

    `rules` : objets avec `.rule_type`, `.params` (dict), `.soft_cut`, `.is_active`.
    Les types inconnus et params invalides sont ignorés silencieusement (robustesse).
    """
    c = DelegationConstraints()
    for r in rules:
        if not getattr(r, "is_active", True):
            continue
        p = r.params or {}
        t = r.rule_type
        if t == "preemptive":
            c.preemptive = True
        elif t == "time_window":
            days = p.get("days")
            c.time_window = TimeRule(
                rule_type="weekly" if days else "date_range",
                days_of_week=list(days) if days else None,
                time_start=_parse_time(p.get("start")),
                time_end=_parse_time(p.get("end")),
            )
        elif t == "item_count":
            c.item_count = _as_int(p.get("max_per_cycle"))
            mode = p.get("mode")
            if mode in ("one_sequential", "one_random"):
                c.rotation_mode = mode
            # ⚠️ `max_for_children` / `max_item_sec` ne sont PLUS lus ici : depuis la migr
            # 0110 ce sont des colonnes du NŒUD (ils décrivent le droit des descendants, pas
            # la diffusion du nœud). C'est `_node_constraints` qui les pose.
        elif t == "time_budget":
            c.time_budget_sec_per_cycle = _as_int(p.get("sec_per_cycle"))
            c.soft_cut = bool(r.soft_cut)
        # frequency_cap / position_lock / priority_band retirés (D3, 2026-07-24) :
        # leviers sans valeur ou inertes → une ligne résiduelle est ignorée sans effet.
    return c


# ── Compilation ──────────────────────────────────────────────────────────────

def _order_key(layer: LayerInput):
    """Tri des couches : national→local, puis priorité décroissante."""
    return (layer.node_level, -layer.priority, layer.id_schedule)


def compile_program(layers: list[LayerInput], now: datetime) -> CompiledProgram:
    """Compile les couches candidates en un programme fusionné déterministe.

    Pipeline : fenêtre time_window → préemption → ordre → item_count → time_budget →
    concaténation. Produit les items compilés (dans l'ordre de diffusion du cycle) + un
    report par couche d'entrée (y compris celles écartées).
    """
    reports: dict[int, LayerReport] = {}
    for l in layers:
        reports[l.id_schedule] = LayerReport(
            id_node=l.id_node, node_name=l.node_name, node_level=l.node_level,
            id_schedule=l.id_schedule, priority=l.priority, status="active",
        )

    # 1. Fenêtre time_window du nœud (AND avec l'activité du schedule, déjà filtrée en amont)
    active: list[LayerInput] = []
    for l in layers:
        tw = l.constraints.time_window
        if tw is not None and not rule_active_at(tw, now):
            reports[l.id_schedule].status = "outside_time_window"
            continue
        active.append(l)

    # 2. Préemption : un nœud préemptif de niveau L supprime tout nœud plus local (> L)
    preempt_levels = [l.node_level for l in active if l.constraints.preemptive]
    if preempt_levels:
        cutoff = min(preempt_levels)
        kept = []
        for l in active:
            if l.node_level <= cutoff:
                kept.append(l)
            else:
                reports[l.id_schedule].status = "preempted"
        active = kept

    # 3. Ordre des couches
    active.sort(key=_order_key)

    # 4. item_count = N items PAR TOUR, en ROTATION (décision Ed 2026-07-26).
    #
    # Avant : `l.items[:N]` — une troncature, donc toujours les N MÊMES items. Le reste du
    # contenu d'un nœud ne passait JAMAIS (« il faut passer TOUS ses contenus, pas seulement
    # les 2 premiers »). On garde la liste ENTIÈRE ici et on tranche au tour par tour lors du
    # déroulé (étape 6) : c'est le seul endroit qui connaît le nombre de tours du cycle.
    provisional: list[tuple[LayerInput, list[CompiledItem]]] = []
    for l in active:
        items = list(l.items)
        # Durée maximale PAR CONTENU : un item au-dessus est ÉCARTÉ (et nommé dans le
        # rapport). Sans ça, « N par tour » comptant des items et pas du temps, une
        # compilation d'une heure en un seul fichier raflerait la boucle entière.
        cap_sec = l.constraints.max_item_sec
        if cap_sec:
            allowed, dropped = [], []
            for it in items:
                (dropped if it.duration_ms > cap_sec * 1000 else allowed).append(it)
            if dropped:
                reports[l.id_schedule].dropped_too_long = [it.media_name for it in dropped]
                items = allowed
        provisional.append((l, items))

    # 5. Nombre de TOURS du cycle = PPCM des rotations de chaque couche.
    #    Un « tour » = une boucle vue à l'écran. Le cycle complet enchaîne T tours, après quoi
    #    chaque contenu a été diffusé un nombre entier de fois : c'est ce qui rend le taux de
    #    passage calculable et identique sur tous les écrans d'un groupe LAN.
    turns = 1
    for l, items in provisional:
        k = l.constraints.item_count
        if k and len(items) > k:
            turns = lcm(turns, rotation_turns(len(items), k))
    per_turn = sum(
        min(l.constraints.item_count, len(items)) if l.constraints.item_count else len(items)
        for l, items in provisional
    )
    # Garde-fous : cardinalités premières entre elles → PPCM explosif. La troncature est
    # REMONTÉE (`truncated`) et non plus seulement loggée : c'est le seul cas où un contenu
    # passe moins souvent que ce que la configuration annonce.
    truncated = False
    cap_turns = min(MAX_UNROLL_TURNS, max(1, _MAX_CYCLE_ITEMS // max(1, per_turn)))
    if turns > cap_turns:
        logger.warning("gouvernance : cycle tronqué %s -> %s tours", turns, cap_turns)
        turns = cap_turns
        truncated = True

    selections: dict[int, Optional[list[list[int]]]] = {}
    for l, items in provisional:
        k = l.constraints.item_count
        if k and len(items) > k:
            selections[l.id_schedule] = build_turn_selections(
                l.constraints.rotation_mode, len(items), k, turns,
                # Seed = contenu de la couche ⇒ déroulé identique sur tous les players.
                rotation_seed(l.id_schedule, [it.id_media for it in items]),
            )
        else:
            selections[l.id_schedule] = None

    # 6. Déroulé : T tours, chaque tour concaténant les couches (national → local).
    #    `time_budget` s'applique PAR TOUR (D1 : volume absolu par boucle) — l'appliquer au
    #    cycle entier diluerait le budget par le nombre de tours, qui dépend des AUTRES nœuds.
    compiled: list[CompiledItem] = []
    clock = 0.0
    for t in range(turns):
        for l, items in provisional:
            sel = selections[l.id_schedule]
            turn_items = [items[i] for i in sel[t]] if sel is not None else items
            budget = l.constraints.time_budget_sec_per_cycle
            if budget is not None:
                allowed_ms = budget * 1000.0
                kept: list[CompiledItem] = []
                acc = 0.0
                for it in turn_items:
                    if acc + it.duration_ms <= allowed_ms:
                        kept.append(it)
                        acc += it.duration_ms
                        continue
                    if l.constraints.soft_cut:   # terminer l'item qui déborde
                        kept.append(it)
                        reports[l.id_schedule].budget_overflow = True
                    reports[l.id_schedule].budget_trimmed = True
                    break
                turn_items = kept
            for it in turn_items:
                compiled.append(it)
                clock += it.duration_ms
                reports[l.id_schedule].item_count += 1
                reports[l.id_schedule].sec += it.duration_ms / 1000.0

    for rep in reports.values():
        rep.sec = round(rep.sec, 1)

    return CompiledProgram(
        items=compiled,
        layers=list(reports.values()),
        cycle_duration_ms=int(clock),
        turns=turns,
        truncated=truncated,
    )


def node_budget_status(constraints: DelegationConstraints, items: list[CompiledItem]) -> dict:
    """Consommation **planifiée** d'un nœud (indépendante du player : mêmes schedules).

    `items` = items des schedules actifs du nœud (déjà concaténés). `used_sec` = secondes de
    contenu propre du nœud par cycle (après cap item_count) ; `budget_sec` = sec_per_cycle
    configuré (volume absolu par cycle, D1 — **même dimension** que `used_sec`, donc
    `remaining_sec` = ce qui reste réellement dans le cycle). Forme alignée sur §18.5.
    """
    used_items = items[: constraints.item_count] if constraints.item_count else items
    used_sec = round(sum(it.duration_ms for it in used_items) / 1000.0, 1)
    budget_sec = constraints.time_budget_sec_per_cycle
    return {
        "used_sec": used_sec,
        "budget_sec": budget_sec,
        "remaining_sec": (round(budget_sec - used_sec, 1) if budget_sec is not None else None),
        "items_used": len(used_items),
        "items_budget": constraints.item_count,
    }
