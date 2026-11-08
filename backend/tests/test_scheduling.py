"""
Tests du noyau Scheduling (services/scheduling.py) — logique PURE, sans DB.

Couvre always/weekly/date_range, bornes incluses, et surtout les fenêtres
OVERNIGHT (time_start > time_end) qui étaient un bug latent avant le noyau.
"""

from datetime import date, datetime, time

from app.services.scheduling import (
    TimeRule,
    _in_time_window,
    next_start_at,
    rule_active_at,
    rules_active_at,
    schedule_active_at,
    schedule_within_validity,
)

# 2026-06-01 est un LUNDI (weekday()==0) ; 2026-06-02 un MARDI.
MON = datetime(2026, 6, 1)
TUE = datetime(2026, 6, 2)
assert MON.weekday() == 0 and TUE.weekday() == 1


def test_always_matches_anytime():
    r = TimeRule(rule_type="always")
    assert rule_active_at(r, MON.replace(hour=3))
    assert rule_active_at(r, TUE.replace(hour=23, minute=59))


def test_unknown_rule_type_never_matches():
    assert not rule_active_at(TimeRule(rule_type="nope"), MON)


def test_weekly_day_filter():
    r = TimeRule(rule_type="weekly", days_of_week=[0])  # lundi seulement
    assert rule_active_at(r, MON.replace(hour=10))
    assert not rule_active_at(r, TUE.replace(hour=10))


def test_weekly_no_days_is_every_day():
    r = TimeRule(rule_type="weekly", days_of_week=None,
                 time_start=time(9, 0), time_end=time(18, 0))
    assert rule_active_at(r, MON.replace(hour=12))
    assert rule_active_at(r, TUE.replace(hour=12))


def test_weekly_time_window_normal():
    r = TimeRule(rule_type="weekly", days_of_week=[0],
                 time_start=time(9, 0), time_end=time(18, 0))
    assert not rule_active_at(r, MON.replace(hour=8, minute=59))
    assert rule_active_at(r, MON.replace(hour=9, minute=0))    # borne incluse
    assert rule_active_at(r, MON.replace(hour=18, minute=0))   # borne incluse
    assert not rule_active_at(r, MON.replace(hour=18, minute=1))


def test_weekly_overnight_window():
    # Bar ouvert lundi 22:00 -> mardi 02:00. days_of_week = jour de DÉBUT (lundi).
    r = TimeRule(rule_type="weekly", days_of_week=[0],
                 time_start=time(22, 0), time_end=time(2, 0))
    assert rule_active_at(r, MON.replace(hour=23))           # lundi soir : ouvert
    assert rule_active_at(r, MON.replace(hour=22, minute=0))  # borne début incluse
    assert rule_active_at(r, TUE.replace(hour=1))            # mardi tôt : encore ouvert
    assert rule_active_at(r, TUE.replace(hour=2, minute=0))   # borne fin incluse
    assert not rule_active_at(r, TUE.replace(hour=2, minute=1))  # fermé après 02:00
    assert not rule_active_at(r, MON.replace(hour=12))       # lundi midi : fermé
    assert not rule_active_at(r, MON.replace(hour=1))        # lundi 01:00 ≠ fenêtre lundi-soir


def test_weekly_with_validity_envelope():
    # Sam/Dim 09-18h, mais seulement durant juin 2026 (cas client item-rules).
    r = TimeRule(rule_type="weekly", days_of_week=[5, 6],
                 time_start=time(9), time_end=time(18),
                 date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    sat_in = datetime(2026, 6, 6, 12)   # samedi 6 juin, dans la fenêtre
    sat_out = datetime(2026, 7, 4, 12)  # samedi 4 juillet, hors validité
    mon_in = datetime(2026, 6, 8, 12)   # lundi, hors jours
    assert sat_in.weekday() == 5 and sat_out.weekday() == 5
    assert rule_active_at(r, sat_in)
    assert not rule_active_at(r, sat_out)
    assert not rule_active_at(r, mon_in)


def test_date_range_bounds():
    r = TimeRule(rule_type="date_range",
                 date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    assert not rule_active_at(r, datetime(2026, 5, 31, 12))
    assert rule_active_at(r, datetime(2026, 6, 1, 0, 0))
    assert rule_active_at(r, datetime(2026, 6, 30, 23, 59))
    assert not rule_active_at(r, datetime(2026, 7, 1, 0, 0))


def test_date_range_with_time_window():
    r = TimeRule(rule_type="date_range",
                 date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                 time_start=time(8, 0), time_end=time(20, 0))
    assert rule_active_at(r, datetime(2026, 6, 15, 12))
    assert not rule_active_at(r, datetime(2026, 6, 15, 7))
    assert not rule_active_at(r, datetime(2026, 6, 15, 21))


def test_in_time_window_helpers():
    assert _in_time_window(time(12), None, None)            # pas de bornes
    assert _in_time_window(time(12), time(9), None)         # start seul
    assert not _in_time_window(time(8), time(9), None)
    assert _in_time_window(time(8), None, time(9))          # end seul
    assert not _in_time_window(time(10), None, time(9))
    assert _in_time_window(time(23), time(22), time(2))     # overnight
    assert _in_time_window(time(1), time(22), time(2))
    assert not _in_time_window(time(12), time(22), time(2))


def test_schedule_validity_envelope():
    # Programme de Noël : actif du 1er au 26 décembre 2026.
    vf, vu = date(2026, 12, 1), date(2026, 12, 26)
    assert not schedule_within_validity(vf, vu, date(2026, 11, 30))  # avant
    assert schedule_within_validity(vf, vu, date(2026, 12, 1))       # borne incluse
    assert schedule_within_validity(vf, vu, date(2026, 12, 26))      # borne incluse
    assert not schedule_within_validity(vf, vu, date(2026, 12, 27))  # après
    # Bornes ouvertes (NULL) = toujours valide
    assert schedule_within_validity(None, None, date(2030, 1, 1))
    assert schedule_within_validity(None, vu, date(2020, 1, 1))      # pas de borne basse
    assert not schedule_within_validity(vf, None, date(2026, 11, 1)) # borne basse seule
    assert schedule_within_validity(vf, None, date(2027, 6, 1))      # après borne basse, pas de haute


def test_schedule_active_at_overnight_validity_owns_start_day():
    """Programme nocturne « Nocturne » 21:00→02:00, tous les jours, valide 04→06 juin 2026.

    Une nuit appartient à son JOUR DE DÉBUT : la validité et le jour de semaine sont
    évalués sur ce jour, pas sur le jour courant. Reproduit le bug terrain (faux créneau
    matinal au 1er jour de validité + nuit manquante au dernier jour)."""
    noc = TimeRule(rule_type="weekly", days_of_week=[0, 1, 2, 3, 4, 5, 6],
                   time_start=time(21, 0), time_end=time(2, 0))
    vf, vu = date(2026, 6, 4), date(2026, 6, 6)

    def act(y, mo, d, h, mi=0):
        return schedule_active_at(noc, vf, vu, datetime(y, mo, d, h, mi))

    # 04/06 = 1er jour de validité : PAS de créneau matinal (nuit 03→04 hors validité)
    assert not act(2026, 6, 4, 1)      # 01:00 → queue de la nuit du 03 (hors validité)
    assert act(2026, 6, 4, 22)         # 22:00 → tête de la nuit du 04 (valide)
    # nuits intermédiaires
    assert act(2026, 6, 5, 1)          # queue de la nuit du 04 (valide)
    assert act(2026, 6, 5, 22)
    # 06/06 = dernier jour : sa nuit (tête) doit être couverte
    assert act(2026, 6, 6, 1)          # queue de la nuit du 05
    assert act(2026, 6, 6, 22)         # tête de la nuit du 06 (valide)
    # 07/06 : la queue de la nuit du 06 reste couverte, mais pas de nouvelle nuit
    assert act(2026, 6, 7, 1)          # queue de la nuit du 06 (jour de début valide)
    assert not act(2026, 6, 7, 22)     # tête de la nuit du 07 (hors validité)
    # 03/06 : avant la validité, rien
    assert not act(2026, 6, 3, 22)
    assert not act(2026, 6, 3, 12)


def test_schedule_active_at_passthrough_and_nonovernight():
    # Sans enveloppe (vf=vu=None) → comportement standard de rule_active_at
    always = TimeRule(rule_type="always")
    assert schedule_active_at(always, None, None, MON.replace(hour=4))
    # « Toujours » AVEC validité → borné aux dates (jour courant)
    assert schedule_active_at(always, date(2026, 6, 4), date(2026, 6, 6), datetime(2026, 6, 5, 3))
    assert not schedule_active_at(always, date(2026, 6, 4), date(2026, 6, 6), datetime(2026, 6, 7, 3))
    # Diurne non-nocturne 08-20 valide 04→06 : jour propriétaire = jour courant
    diu = TimeRule(rule_type="weekly", days_of_week=[0, 1, 2, 3, 4, 5, 6],
                   time_start=time(8), time_end=time(20))
    assert schedule_active_at(diu, date(2026, 6, 4), date(2026, 6, 6), datetime(2026, 6, 5, 12))
    assert not schedule_active_at(diu, date(2026, 6, 4), date(2026, 6, 6), datetime(2026, 6, 7, 12))


def test_rules_active_at_or_and_empty():
    morning = TimeRule(rule_type="weekly", days_of_week=[0],
                       time_start=time(6), time_end=time(11))
    evening = TimeRule(rule_type="weekly", days_of_week=[0],
                       time_start=time(18), time_end=time(23))
    assert rules_active_at([morning, evening], MON.replace(hour=7))
    assert rules_active_at([morning, evening], MON.replace(hour=20))
    assert not rules_active_at([morning, evening], MON.replace(hour=14))
    assert not rules_active_at([], MON.replace(hour=7))  # liste vide = jamais


# ── next_start_at (prefetch look-ahead) ──────────────────────────────────────────

def test_next_start_now_when_active():
    """Déjà actif → now (priorité max au prefetch)."""
    always = TimeRule(rule_type="always")
    now = MON.replace(hour=10)
    assert next_start_at([always], None, None, now) == now


def test_next_start_empty_rules_none():
    """Pas de règle = jamais joué (cohérent sync) → None."""
    assert next_start_at([], None, None, MON, horizon_days=28) is None


def test_next_start_weekly_future_day():
    """Mercredi 09-12h, on est lundi 14h → prochaine occurrence = mercredi 09:00."""
    wed = TimeRule(rule_type="weekly", days_of_week=[2],
                   time_start=time(9), time_end=time(12))
    nxt = next_start_at([wed], None, None, MON.replace(hour=14))
    assert nxt == datetime(2026, 6, 3, 9, 0)   # mercredi 3 juin 09:00


def test_next_start_today_later_same_day():
    """Lundi 18-23h, on est lundi 14h → ce soir 18:00 (même jour)."""
    eve = TimeRule(rule_type="weekly", days_of_week=[0],
                   time_start=time(18), time_end=time(23))
    nxt = next_start_at([eve], None, None, MON.replace(hour=14))
    assert nxt == datetime(2026, 6, 1, 18, 0)


def test_next_start_beyond_horizon_none():
    """date_range qui démarre dans 60 jours, horizon 28 → None."""
    future = TimeRule(rule_type="date_range",
                      date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
    assert next_start_at([future], None, None, MON, horizon_days=28) is None


def test_next_start_validity_envelope():
    """Always borné au 10-12 juin, on est le 1er → prochaine = 10 juin 00:00."""
    always = TimeRule(rule_type="always")
    nxt = next_start_at([always], date(2026, 6, 10), date(2026, 6, 12), MON, horizon_days=28)
    assert nxt == datetime(2026, 6, 10, 0, 0)


def test_next_start_earliest_of_multiple_rules():
    """Deux règles → la plus proche gagne."""
    wed = TimeRule(rule_type="weekly", days_of_week=[2], time_start=time(9), time_end=time(12))
    tue = TimeRule(rule_type="weekly", days_of_week=[1], time_start=time(8), time_end=time(10))
    nxt = next_start_at([wed, tue], None, None, MON.replace(hour=14))
    assert nxt == datetime(2026, 6, 2, 8, 0)   # mardi 8:00 avant mercredi
