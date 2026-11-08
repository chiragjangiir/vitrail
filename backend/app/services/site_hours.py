"""
Heures d'ouverture des sites & alimentation automatique des écrans (auto-power).

Logique PURE, sans I/O DB, testable unitairement. Résout, pour un instant donné
(heure locale du site), si l'écran doit être ALLUMÉ, à partir de :
  - horaires hebdomadaires réguliers (cms_site_hours),
  - exceptions datées (cms_site_exceptions : closed | hours | open_24h) qui priment,
  - jours fériés (calendrier régional) si le site les « respecte »,
  - marges avant ouverture / après fermeture (power_lead_min / power_lag_min).

Gère les fenêtres enjambant minuit (ex. bar 18:00→02:00) et les marges qui
débordent d'un jour à l'autre en évaluant la veille, le jour même et le lendemain.

Réutilise l'esprit de `services/scheduling.py` (overnight) ; ici on raisonne en
datetimes absolus (locaux) pour appliquer proprement les marges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, time as time_cls, timedelta
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class DayHours:
    """Horaires effectifs d'un jour donné (après exceptions/fériés)."""
    is_closed: bool = False
    is_24h: bool = False
    open_time: Optional[time_cls] = None
    close_time: Optional[time_cls] = None


@dataclass(frozen=True)
class Exception_:
    """Exception datée (vue plate, découplée de l'ORM)."""
    date_from: date_cls
    date_to: date_cls
    kind: str  # closed | hours | open_24h
    open_time: Optional[time_cls] = None
    close_time: Optional[time_cls] = None


# ── Jours fériés ─────────────────────────────────────────────────────────────
def _easter_sunday(year: int) -> date_cls:
    """Dimanche de Pâques (algorithme de Gauss / Anonymous Gregorian)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date_cls(year, month, day + 1)


@lru_cache(maxsize=64)
def holidays_for(region: str, year: int) -> frozenset[date_cls]:
    """Jours fériés d'une région pour une année. Région inconnue → vide."""
    if region != "FR":
        return frozenset()
    easter = _easter_sunday(year)
    days = {
        date_cls(year, 1, 1),    # Jour de l'an
        date_cls(year, 5, 1),    # Fête du travail
        date_cls(year, 5, 8),    # Victoire 1945
        date_cls(year, 7, 14),   # Fête nationale
        date_cls(year, 8, 15),   # Assomption
        date_cls(year, 11, 1),   # Toussaint
        date_cls(year, 11, 11),  # Armistice
        date_cls(year, 12, 25),  # Noël
        easter + timedelta(days=1),   # Lundi de Pâques
        easter + timedelta(days=39),  # Ascension
        easter + timedelta(days=50),  # Lundi de Pentecôte
    }
    return frozenset(days)


# ── Résolution des horaires d'un jour ────────────────────────────────────────
def resolve_day(
    d: date_cls,
    weekly: dict[int, DayHours],
    exceptions: list[Exception_],
    respect_holidays: bool,
    region: str,
) -> DayHours:
    """Horaires effectifs du jour `d` : exception > férié > horaires hebdo."""
    matching = [e for e in exceptions if e.date_from <= d <= e.date_to]
    if matching:
        # La plus spécifique gagne (plage la plus courte).
        e = min(matching, key=lambda x: (x.date_to - x.date_from))
        if e.kind == "closed":
            return DayHours(is_closed=True)
        if e.kind == "open_24h":
            return DayHours(is_24h=True)
        if e.kind == "hours":
            return DayHours(open_time=e.open_time, close_time=e.close_time)

    if respect_holidays and d in holidays_for(region, d.year):
        return DayHours(is_closed=True)

    h = weekly.get(d.weekday())
    if h is None or h.is_closed or h.open_time is None or h.close_time is None:
        return DayHours(is_closed=True)
    return DayHours(open_time=h.open_time, close_time=h.close_time)


def window_datetimes(d: date_cls, dh: DayHours) -> Optional[tuple[datetime, datetime]]:
    """Fenêtre d'ouverture absolue (open_dt, close_dt) pour le jour `d`, ou None si fermé.

    close <= open ⇒ enjambe minuit (close le lendemain). close == open ⇒ 24h.
    """
    if dh.is_closed:
        return None
    if dh.is_24h:
        return datetime.combine(d, time_cls(0, 0)), datetime.combine(d + timedelta(days=1), time_cls(0, 0))
    if dh.open_time is None or dh.close_time is None:
        return None
    open_dt = datetime.combine(d, dh.open_time)
    close_dt = datetime.combine(d, dh.close_time)
    if dh.close_time <= dh.open_time:
        close_dt += timedelta(days=1)  # overnight (ou 24h si égal)
    return open_dt, close_dt


def site_screen_on_at(
    now: datetime,
    weekly: dict[int, DayHours],
    exceptions: list[Exception_],
    *,
    lead_min: int = 0,
    lag_min: int = 0,
    respect_holidays: bool = False,
    region: str = "FR",
) -> bool:
    """True si l'écran doit être allumé à `now` (heure locale du site).

    Évalue veille / jour / lendemain pour couvrir les fenêtres nocturnes et les
    marges qui débordent au-delà de minuit.
    """
    for delta in (-1, 0, 1):
        d = now.date() + timedelta(days=delta)
        dh = resolve_day(d, weekly, exceptions, respect_holidays, region)
        w = window_datetimes(d, dh)
        if w is None:
            continue
        on_dt = w[0] - timedelta(minutes=lead_min)
        off_dt = w[1] + timedelta(minutes=lag_min)
        if on_dt <= now < off_dt:
            return True
    return False


# ── Mode d'alimentation par player (vitrine, 24/7, manuel…) ──────────────────
def player_desired_power(
    power_cfg: dict | None,
    now: datetime,
    site_on: Optional[bool],
) -> Optional[bool]:
    """État d'alimentation voulu pour un player, ou None = « ne pas piloter ».

    power_cfg = display_config.power_schedule :
      - absent / mode 'follow_site' : suit le site (site_on) ; None si le site ne pilote pas
      - 'always_on'  : toujours allumé
      - 'manual'     : jamais piloté automatiquement (None)
      - 'custom'     : fenêtre propre {on_time, off_time, days?} (ex. vitrine la nuit)
    """
    mode = (power_cfg or {}).get("mode", "follow_site")
    if mode == "always_on":
        return True
    if mode == "manual":
        return None
    if mode == "custom":
        on = power_cfg.get("on_time")
        off = power_cfg.get("off_time")
        if not on or not off:
            return None
        days = power_cfg.get("days")  # None = tous les jours ; sinon liste 0..6 (jour de début)
        oh = DayHours(open_time=_parse_time(on), close_time=_parse_time(off))
        # On réutilise la logique veille/jour/lendemain (overnight) sans marge.
        for delta in (-1, 0, 1):
            d = now.date() + timedelta(days=delta)
            if days is not None and d.weekday() not in days:
                continue
            w = window_datetimes(d, oh)
            if w and w[0] <= now < w[1]:
                return True
        return False
    # follow_site (défaut)
    return site_on


def _parse_time(s: str) -> time_cls:
    h, m = (int(x) for x in s.split(":")[:2])
    return time_cls(h, m)


def scheduled_off_at(
    now: datetime,
    weekly: dict[int, DayHours],
    exceptions: list[Exception_],
    power_cfg: dict | None,
    *,
    lead_min: int = 0,
    lag_min: int = 0,
    respect_holidays: bool = False,
    region: str = "FR",
) -> bool:
    """True si l'écran du player est programmé ÉTEINT à `now` (heure locale du site).

    Sert à qualifier un player offline d'« attendu » (alerting §XXII) : pendant une
    coupure d'alimentation programmée, certains devices dorment déconnectés (veille
    Android = réseau coupé). Modes manual/always_on (ou site non piloté) → False.
    """
    site_on = site_screen_on_at(
        now, weekly, exceptions,
        lead_min=lead_min, lag_min=lag_min,
        respect_holidays=respect_holidays, region=region,
    )
    return player_desired_power(power_cfg, now, site_on) is False


# ── Fenêtres d'allumage pré-calculées (autonomie offline des players) ─────────
def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Fusionne les intervalles qui se chevauchent ou se touchent (triés)."""
    merged: list[tuple[datetime, datetime]] = []
    for on_dt, off_dt in sorted(intervals):
        if merged and on_dt <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], off_dt))
        else:
            merged.append((on_dt, off_dt))
    return merged


def site_power_intervals(
    weekly: dict[int, DayHours],
    exceptions: list[Exception_],
    *,
    lead_min: int = 0,
    lag_min: int = 0,
    respect_holidays: bool = False,
    region: str = "FR",
    start: date_cls,
    days: int = 14,
) -> list[tuple[datetime, datetime]]:
    """Fenêtres d'allumage absolues (heure locale du site) sur `days` jours.

    Pré-calcul poussé aux players (display_config.offline_power) pour qu'un player
    SANS connexion serveur puisse allumer/éteindre son écran seul. Évalue la veille
    de `start` pour couvrir les fenêtres nocturnes en cours, applique les marges
    lead/lag, puis fusionne (des marges généreuses ou du 24h peuvent faire se
    toucher deux jours consécutifs).
    """
    raw: list[tuple[datetime, datetime]] = []
    for delta in range(-1, days):
        d = start + timedelta(days=delta)
        dh = resolve_day(d, weekly, exceptions, respect_holidays, region)
        w = window_datetimes(d, dh)
        if w is None:
            continue
        raw.append((w[0] - timedelta(minutes=lead_min), w[1] + timedelta(minutes=lag_min)))
    return _merge_intervals(raw)


def custom_power_intervals(
    power_cfg: dict,
    *,
    start: date_cls,
    days: int = 14,
) -> list[tuple[datetime, datetime]]:
    """Fenêtres absolues du mode 'custom' (vitrine) sur `days` jours.

    Même sémantique que player_desired_power : {on_time, off_time, days?} où
    `days` (0..6) filtre le JOUR DE DÉBUT de la fenêtre ; overnight géré.
    """
    on = power_cfg.get("on_time")
    off = power_cfg.get("off_time")
    if not on or not off:
        return []
    allowed = power_cfg.get("days")  # None = tous les jours
    oh = DayHours(open_time=_parse_time(on), close_time=_parse_time(off))
    raw: list[tuple[datetime, datetime]] = []
    for delta in range(-1, days):
        d = start + timedelta(days=delta)
        if allowed is not None and d.weekday() not in allowed:
            continue
        w = window_datetimes(d, oh)
        if w is not None:
            raw.append(w)
    return _merge_intervals(raw)
