"""
Noyau Scheduling — évaluation de règle temporelle TZ-aware (partagé).

Brique (a) du noyau Scheduling & Targeting (cf. docs/SPIKE_scheduling_targeting_core.md).
Logique PURE, sans I/O DB, testable unitairement. Factorise la règle horaire jusqu'ici
dupliquée dans `ws.py::_rule_matches`, `schedules.py::_rule_matches` et la fenêtre de
validité de `_build_basket_items`.

Consommateurs : schedules (§XIII), item-rules (§ retours clients item 4), Gouvernance
§XVIII Phase 2 (fenêtre d'une couche), Retail Media (flight + daypart, Phase 3).

Vocabulaire = celui de `cms_schedule_rules` : rule_type ∈ {always, weekly, date_range},
days_of_week 0=Lun…6=Dim (= datetime.weekday()), time_start/time_end, date_from/date_to.

Fenêtre OVERNITHT : si time_start > time_end, le créneau enjambe minuit
([time_start, 24h[ ∪ [0h, time_end]). Pour `weekly`, days_of_week désigne le jour de
DÉBUT du créneau (convention actée dans le spike).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


@dataclass(frozen=True)
class TimeRule:
    """Règle temporelle normalisée, découplée de l'ORM (schedule OU item-rule)."""

    rule_type: str  # always | weekly | date_range
    days_of_week: list[int] | None = None  # 0=Lun … 6=Dim
    time_start: time | None = None
    time_end: time | None = None
    date_from: date | None = None
    date_to: date | None = None


def local_now(tz_name: str | None = None) -> datetime:
    """Instant courant en heure locale (datetime naïf).

    Défaut = SIGNFLOW_TZ (mono-pays). `tz_name` permet la TZ d'un player/site
    (multi-pays, forward-compat). Repli UTC si la TZ est inconnue.
    """
    try:
        tz = ZoneInfo(tz_name or settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).replace(tzinfo=None)


def _in_time_window(current: time, start: time | None, end: time | None) -> bool:
    """True si `current` ∈ [start, end], en gérant les fenêtres enjambant minuit.

    - start seul   : current >= start
    - end seul     : current <= end
    - start <= end : créneau normal [start, end]
    - start >  end : créneau overnight [start, 24h[ ∪ [0h, end]
    """
    if start is None and end is None:
        return True
    if start is None:
        return current <= end  # type: ignore[operator]
    if end is None:
        return current >= start
    if start <= end:
        return start <= current <= end
    # overnight : minuit est dans le créneau
    return current >= start or current <= end


def rule_active_at(rule: TimeRule, now: datetime) -> bool:
    """True si `now` (déjà en heure locale cible) tombe dans la règle."""
    current_time = now.time().replace(microsecond=0)
    current_date = now.date()

    if rule.rule_type == "always":
        return True

    if rule.rule_type == "date_range":
        if rule.date_from and current_date < rule.date_from:
            return False
        if rule.date_to and current_date > rule.date_to:
            return False
        return _in_time_window(current_time, rule.time_start, rule.time_end)

    if rule.rule_type == "weekly":
        # Enveloppe de validité optionnelle (date_from/date_to) — utile pour les
        # item-rules « récurrence + plage de dates ». Les schedules weekly ne posent
        # pas ces dates → comportement inchangé pour eux.
        if rule.date_from and current_date < rule.date_from:
            return False
        if rule.date_to and current_date > rule.date_to:
            return False
        # days_of_week = jour de DÉBUT du créneau (cf. overnight ci-dessous)
        if rule.days_of_week is not None:
            overnight = (
                rule.time_start is not None
                and rule.time_end is not None
                and rule.time_start > rule.time_end
            )
            if overnight:
                # Le créneau couvre la fin du jour J (>= time_start) et le début
                # du jour J+1 (<= time_end). On accepte si :
                #  - aujourd'hui est un jour de début ET current >= time_start, OU
                #  - hier était un jour de début ET current <= time_end.
                yesterday = (now.weekday() - 1) % 7
                started_today = (
                    now.weekday() in rule.days_of_week and current_time >= rule.time_start  # type: ignore[operator]
                )
                started_yesterday = (
                    yesterday in rule.days_of_week and current_time <= rule.time_end  # type: ignore[operator]
                )
                return started_today or started_yesterday
            if now.weekday() not in rule.days_of_week:
                return False
        return _in_time_window(current_time, rule.time_start, rule.time_end)

    return False


def schedule_within_validity(
    valid_from: date | None, valid_until: date | None, today: date
) -> bool:
    """Enveloppe de validité d'un programme (dates début/fin, heure locale).

    True si `today` ∈ [valid_from, valid_until] (bornes incluses ; NULL = ouverte).
    S'AND avec l'évaluation des règles de récurrence : un programme n'est diffusé que
    s'il est dans sa fenêtre de dates ET qu'une règle horaire matche. Sans bornes
    (les deux NULL) = toujours valide (comportement historique inchangé).
    """
    if valid_from and today < valid_from:
        return False
    if valid_until and today > valid_until:
        return False
    return True


def schedule_active_at(
    rule: TimeRule, valid_from: date | None, valid_until: date | None, now: datetime
) -> bool:
    """`rule_active_at` + enveloppe de validité du PROGRAMME (valid_from/until), attribuée
    au jour de DÉBUT du créneau — IDENTIQUE au calendrier (source de vérité UI).

    Une fenêtre nocturne (ex. 21:00→02:00) appartient à son jour de début : le créneau
    00:00→02:00 du jour J relève de la nuit commencée en J-1. La validité (et le jour de
    semaine) sont donc évaluées sur le jour de début. Conséquence : `valid_until` = dernier
    jour où une nuit peut DÉMARRER (sa queue matinale tombe le lendemain et reste affichée) ;
    `valid_from` = premier jour où une nuit peut démarrer (pas de faux créneau matinal issu
    de la nuit précédente, hors validité). Aligne la résolution serveur (sync players,
    current-schedule, current-state, simulation) sur le calendrier qui rattache déjà la
    queue à son jour de début.
    """
    if valid_from is None and valid_until is None:
        return rule_active_at(rule, now)

    def _within(d: date) -> bool:
        if valid_from and d < valid_from:
            return False
        if valid_until and d > valid_until:
            return False
        return True

    today = now.date()
    overnight = (
        rule.rule_type == "weekly"
        and rule.time_start is not None and rule.time_end is not None
        and rule.time_start > rule.time_end
    )
    if not overnight:
        # always / weekly normal / date_range : la fenêtre appartient au jour courant.
        return _within(today) and rule_active_at(rule, now)

    # weekly nocturne : tête (jour J) vs queue (créneau du matin, appartient à J-1)
    ct = now.time().replace(microsecond=0)
    days = rule.days_of_week
    head = (days is None or now.weekday() in days) and ct >= rule.time_start and _within(today)
    ywd = (now.weekday() - 1) % 7
    tail = (days is None or ywd in days) and ct <= rule.time_end and _within(today - timedelta(days=1))
    return head or tail


def next_start_at(
    rules: list[TimeRule],
    valid_from: date | None,
    valid_until: date | None,
    now: datetime,
    horizon_days: int = 28,
) -> datetime | None:
    """Prochaine datetime locale (>= now) où AU MOINS UNE règle du programme s'active,
    dans la fenêtre [now, now+horizon]. `now` si déjà actif. None si jamais dans l'horizon.

    Sert la priorisation du **prefetch** (look-ahead) : plus la diffusion est proche, plus
    le contenu est prioritaire au téléchargement / à la conservation sous pression disque.

    Forward-scan jour par jour : pour chaque jour, on teste les instants candidats (minuit
    + chaque `time_start` de règle). La granularité (ces instants) suffit pour ordonner les
    médias par proximité de diffusion. Liste de règles vide = jamais actif (cohérent avec la
    résolution de sync qui ignore un schedule sans règle) → None.
    """
    if not rules:
        return None
    if any(schedule_active_at(r, valid_from, valid_until, now) for r in rules):
        return now
    horizon_end = now + timedelta(days=horizon_days)
    # Instants candidats d'un jour : minuit (couvre always/date_range sans heure) + les
    # heures de début de chaque règle (couvre weekly/date_range à créneau).
    start_times = sorted(
        {r.time_start for r in rules if r.time_start is not None} | {time(0, 0)}
    )
    d = now.date()
    while datetime.combine(d, time(0, 0)) <= horizon_end:
        for st in start_times:
            cand = datetime.combine(d, st)
            if cand < now or cand > horizon_end:
                continue
            if any(schedule_active_at(r, valid_from, valid_until, cand) for r in rules):
                return cand
        d += timedelta(days=1)
    return None


def rules_active_at(rules: list[TimeRule], now: datetime) -> bool:
    """OR sur une liste de règles (un schedule/item a N règles, actif si l'une matche).

    Liste vide = jamais actif (cohérent avec l'existant : un schedule sans règle ne
    s'active pas). Pour « perpétuel par défaut », l'appelant teste la liste vide en amont.
    """
    return any(rule_active_at(r, now) for r in rules)


# ── Adaptateurs ORM (hors logique pure, pour éviter le couplage modèle) ──────────

def time_rule_from_schedule(r) -> TimeRule:  # r: CmsScheduleRule
    """Convertit une ligne `cms_schedule_rules` en TimeRule."""
    return TimeRule(
        rule_type=r.rule_type,
        days_of_week=r.days_of_week,
        time_start=r.time_start,
        time_end=r.time_end,
        date_from=r.date_from,
        date_to=r.date_to,
    )


def schedule_rule_matches(r, now: datetime) -> bool:  # r: CmsScheduleRule
    """Raccourci : éval directe d'une ligne `cms_schedule_rules`."""
    return rule_active_at(time_rule_from_schedule(r), now)
