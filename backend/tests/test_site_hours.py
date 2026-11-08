"""Tests du noyau auto-power (services/site_hours) — logique pure, sans DB."""

from datetime import date, datetime, time

from app.services.site_hours import (
    DayHours,
    Exception_,
    holidays_for,
    player_desired_power,
    resolve_day,
    site_screen_on_at,
)

# Magasin type : Lun-Sam 08:00-19:30, Dim fermé.
STORE = {wd: DayHours(open_time=time(8, 0), close_time=time(19, 30)) for wd in range(6)}
STORE[6] = DayHours(is_closed=True)

# Bar nocturne : tous les jours 18:00-02:00 (overnight).
BAR = {wd: DayHours(open_time=time(18, 0), close_time=time(2, 0)) for wd in range(7)}


def test_french_holidays():
    h = holidays_for("FR", 2026)
    assert date(2026, 1, 1) in h and date(2026, 12, 25) in h and date(2026, 5, 1) in h
    assert len(h) == 11
    assert holidays_for("US", 2026) == frozenset()  # région inconnue


def test_resolve_day_weekly_and_closed():
    # 2026-06-08 = lundi (ouvert), 2026-06-14 = dimanche (fermé)
    assert resolve_day(date(2026, 6, 8), STORE, [], False, "FR").open_time == time(8, 0)
    assert resolve_day(date(2026, 6, 14), STORE, [], False, "FR").is_closed


def test_resolve_day_exception_overrides():
    # Soirée exceptionnelle le 2 sept 2026 : 08:00-22:30 (override l'horaire normal)
    exc = [Exception_(date(2026, 9, 2), date(2026, 9, 2), "hours", time(8, 0), time(22, 30))]
    dh = resolve_day(date(2026, 9, 2), STORE, exc, False, "FR")
    assert dh.close_time == time(22, 30)
    # Fermeture exceptionnelle
    exc2 = [Exception_(date(2026, 9, 2), date(2026, 9, 2), "closed")]
    assert resolve_day(date(2026, 9, 2), STORE, exc2, False, "FR").is_closed
    # 24h
    exc3 = [Exception_(date(2026, 9, 2), date(2026, 9, 2), "open_24h")]
    assert resolve_day(date(2026, 9, 2), STORE, exc3, False, "FR").is_24h


def test_holiday_default_off_vs_respected():
    noel = date(2026, 12, 25)  # vendredi
    # Par défaut (respect_holidays=False) : férié = jour normal → ouvert
    assert not resolve_day(noel, STORE, [], False, "FR").is_closed
    # respect_holidays=True : férié = fermé
    assert resolve_day(noel, STORE, [], True, "FR").is_closed
    # Sauf si une exception « ouvert » prime sur le férié
    exc = [Exception_(noel, noel, "hours", time(8, 0), time(19, 30))]
    assert not resolve_day(noel, STORE, exc, True, "FR").is_closed


def test_screen_on_with_margins():
    day = date(2026, 6, 8)  # lundi
    def on(h, m):
        return site_screen_on_at(datetime.combine(day, time(h, m)), STORE, [], lead_min=15, lag_min=15)
    assert not on(7, 40)   # avant marge (ouverture 08:00 - 15min = 07:45)
    assert on(7, 50)       # dans la marge avant
    assert on(12, 0)       # plein jour
    assert on(19, 40)      # dans la marge après (fermeture 19:30 + 15 = 19:45)
    assert not on(19, 50)  # après marge


def test_screen_on_overnight_bar():
    def on(d, h, m):
        return site_screen_on_at(datetime.combine(d, time(h, m)), BAR, [], lead_min=0, lag_min=0)
    mon, tue = date(2026, 6, 8), date(2026, 6, 9)
    assert on(mon, 23, 0)       # lundi soir
    assert on(tue, 1, 0)        # mardi 01:00 = fin de la nuit de lundi (overnight)
    assert not on(tue, 12, 0)   # mardi midi = fermé


def test_screen_on_exception_evening():
    # Le 2 sept : exception 08:00-22:30 → allumé à 21:00 (sinon fermé à 19:30)
    exc = [Exception_(date(2026, 9, 2), date(2026, 9, 2), "hours", time(8, 0), time(22, 30))]
    at21 = datetime(2026, 9, 2, 21, 0)
    assert site_screen_on_at(at21, STORE, exc, lead_min=0, lag_min=0)
    assert not site_screen_on_at(at21, STORE, [], lead_min=0, lag_min=0)  # sans exception : fermé


def test_player_power_modes():
    now = datetime(2026, 6, 8, 12, 0)
    assert player_desired_power({"mode": "always_on"}, now, False) is True
    assert player_desired_power({"mode": "manual"}, now, True) is None
    assert player_desired_power(None, now, True) is True            # follow_site défaut
    assert player_desired_power({"mode": "follow_site"}, now, False) is False
    # Vitrine custom 07:00-23:00
    cfg = {"mode": "custom", "on_time": "07:00", "off_time": "23:00"}
    assert player_desired_power(cfg, datetime(2026, 6, 8, 22, 0), False) is True
    assert player_desired_power(cfg, datetime(2026, 6, 8, 23, 30), True) is False
    # Vitrine custom toute la nuit 20:00-06:00 (overnight)
    night = {"mode": "custom", "on_time": "20:00", "off_time": "06:00"}
    assert player_desired_power(night, datetime(2026, 6, 9, 2, 0), False) is True


# ── Fenêtres pré-calculées offline (autonomie player sans serveur) ─────────────

def test_site_power_intervals_basic_margins():
    from app.services.site_hours import site_power_intervals
    start = date(2026, 6, 8)  # lundi
    iv = site_power_intervals(STORE, [], lead_min=15, lag_min=15, start=start, days=7)
    # Lun-Sam ouverts (+ éventuel samedi de la veille 06-06 couvert par delta=-1)
    days_covered = {i[0].date() for i in iv}
    assert date(2026, 6, 8) in days_covered
    assert date(2026, 6, 14) not in days_covered  # dimanche fermé
    mon = next(i for i in iv if i[0].date() == date(2026, 6, 8))
    assert mon[0] == datetime(2026, 6, 8, 7, 45)   # 08:00 - 15 min
    assert mon[1] == datetime(2026, 6, 8, 19, 45)  # 19:30 + 15 min


def test_site_power_intervals_overnight_and_merge():
    from app.services.site_hours import site_power_intervals
    start = date(2026, 6, 8)
    # Bar overnight : chaque fenêtre finit le lendemain 02:00
    iv = site_power_intervals(BAR, [], start=start, days=3)
    first = next(i for i in iv if i[0].date() == start)
    assert first[1] == datetime(2026, 6, 9, 2, 0)
    # Marges énormes → les fenêtres se touchent → fusion en un seul intervalle
    iv2 = site_power_intervals(BAR, [], lead_min=16 * 60, lag_min=0, start=start, days=3)
    assert len(iv2) == 1


def test_site_power_intervals_exception_included():
    from app.services.site_hours import site_power_intervals
    start = date(2026, 9, 1)
    exc = [Exception_(date(2026, 9, 2), date(2026, 9, 2), "closed")]
    iv = site_power_intervals(STORE, exc, start=start, days=7)
    assert date(2026, 9, 2) not in {i[0].date() for i in iv}


def test_custom_power_intervals_overnight_days_filter():
    from app.services.site_hours import custom_power_intervals
    start = date(2026, 6, 8)  # lundi
    cfg = {"on_time": "20:00", "off_time": "06:00", "days": [0, 4]}  # lun + ven (jour de début)
    iv = custom_power_intervals(cfg, start=start, days=7)
    starts = {i[0] for i in iv}
    assert datetime(2026, 6, 8, 20, 0) in starts    # lundi soir
    assert datetime(2026, 6, 12, 20, 0) in starts   # vendredi soir
    assert all(i[0].weekday() in (0, 4) for i in iv)
    mon = next(i for i in iv if i[0] == datetime(2026, 6, 8, 20, 0))
    assert mon[1] == datetime(2026, 6, 9, 6, 0)     # overnight → mardi 06:00


def test_custom_power_intervals_incomplete_cfg():
    from app.services.site_hours import custom_power_intervals
    assert custom_power_intervals({"on_time": "07:00"}, start=date(2026, 6, 8)) == []


# ── Offline attendu pendant une coupure programmée (alerting §XXII) ────────────

def test_scheduled_off_at_follow_site():
    from app.services.site_hours import scheduled_off_at
    day = date(2026, 6, 8)  # lundi, magasin 08:00-19:30, marges 15 min
    def off(h, m):
        return scheduled_off_at(
            datetime.combine(day, time(h, m)), STORE, [], None,
            lead_min=15, lag_min=15,
        )
    assert off(6, 0)        # nuit → éteint programmé
    assert off(7, 40)       # juste avant la marge d'ouverture (07:45)
    assert not off(7, 50)   # écran rallumé (marge avant)
    assert not off(12, 0)   # plein jour
    assert off(20, 0)       # après 19:45 → éteint programmé
    # Dimanche fermé toute la journée
    assert scheduled_off_at(datetime(2026, 6, 14, 12, 0), STORE, [], None,
                            lead_min=15, lag_min=15)


def test_scheduled_off_at_modes_not_suppressed():
    from app.services.site_hours import scheduled_off_at
    night = datetime(2026, 6, 8, 3, 0)
    # always_on / manual → jamais « éteint programmé » (offline = anormal)
    assert not scheduled_off_at(night, STORE, [], {"mode": "always_on"})
    assert not scheduled_off_at(night, STORE, [], {"mode": "manual"})
    # custom vitrine 20:00-06:00 : allumé à 03:00, éteint à 12:00
    cfg = {"mode": "custom", "on_time": "20:00", "off_time": "06:00"}
    assert not scheduled_off_at(night, STORE, [], cfg)
    assert scheduled_off_at(datetime(2026, 6, 8, 12, 0), STORE, [], cfg)
