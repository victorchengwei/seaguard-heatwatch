import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from heatwatch.rules import Conditions, Worker, assess, wbgt_estimate


def test_cool_day_is_normal():
    a = assess(Conditions(temp_c=24, rh_pct=50, sun=False), Worker(workload="light"))
    assert a.level == 1


def test_hot_humid_heavy_work_stops():
    a = assess(Conditions(temp_c=42, rh_pct=60, sun=True), Worker(workload="heavy"))
    assert a.level == 4 and a.escalate


def test_unwell_always_escalates_even_when_cool():
    a = assess(Conditions(temp_c=20, rh_pct=40), Worker(feels_unwell=True))
    assert a.level == 4 and a.escalate


def test_no_data_is_failsafe_not_silent():
    a = assess(Conditions(), Worker())
    assert a.level == 3


def test_stale_data_never_lowers_risk():
    w = Worker(workload="moderate")
    fresh = assess(Conditions(temp_c=32, rh_pct=50), w)
    stale = assess(Conditions(temp_c=32, rh_pct=50, stale=True), w)
    assert stale.level >= fresh.level


def test_unacclimatized_is_stricter():
    c = Conditions(temp_c=31, rh_pct=55, sun=True)
    a = assess(c, Worker(workload="moderate", acclimatized=True))
    b = assess(c, Worker(workload="moderate", acclimatized=False))
    assert b.level >= a.level


def test_chemical_suit_raises_risk():
    c = Conditions(temp_c=30, rh_pct=50, sun=False)
    a = assess(c, Worker(clothing="work_clothes"))
    b = assess(c, Worker(clothing="vapour_barrier_suit"))
    assert b.level > a.level


def test_heat_budget_raises_level():
    c = Conditions(temp_c=33, rh_pct=50, sun=True)
    a = assess(c, Worker(minutes_worked=10))
    b = assess(c, Worker(minutes_worked=90))
    assert b.level >= a.level


def test_wbgt_shade_reasonable():
    assert 22 < wbgt_estimate(30, 50, sun=False) < 27
    assert wbgt_estimate(30, 50, sun=True) > wbgt_estimate(30, 50, sun=False)


def test_schedule_matches_level():
    from heatwatch.rules import SCHEDULE
    for temp in range(24, 46):
        for mins in (0, 90):
            for wl in ("light", "moderate", "heavy"):
                a = assess(Conditions(temp_c=temp, rh_pct=50, sun=True), Worker(wl, minutes_worked=mins))
                assert a.schedule
                if a.level == 4:  # no work, or ADOSH withdrawal: emergency work only
                    assert a.schedule == SCHEDULE["stop"] or a.schedule.startswith("No ordinary work")
                if a.level == 3:
                    assert a.schedule not in (SCHEDULE["75-100"], SCHEDULE["stop"])


def test_hydration_prompt_matches_level():
    for temp in (20, 33, 38, 45):
        a = assess(Conditions(temp_c=temp, rh_pct=50, sun=True), Worker("heavy"))
        assert a.hydration
        if a.level >= 2:
            assert "1.4 L" in a.hydration
        if 2 <= a.level <= 3:
            assert "250 ml" in a.hydration


def test_twl_stricter_wins_and_is_reported():
    from heatwatch.rules import twl_level
    # Hot, humid, calm, in sun: ADOSH zone is reported with the assessment.
    a = assess(Conditions(temp_c=38, rh_pct=55, sun=True, wind_ms=0.5), Worker("light"))
    assert a.twl is not None and a.oshad_zone and a.oshad_rules
    off = assess(Conditions(temp_c=38, rh_pct=55, sun=True, wind_ms=0.5, use_twl=False), Worker("light"))
    assert a.level >= off.level and off.twl is None
    # Unacclimatised workers may not work in the Buffer zone.
    assert twl_level("buffer", Worker(acclimatized=False)) == 4
    assert twl_level("buffer", Worker()) == 3
    assert twl_level("withdrawal", Worker()) == 4


def test_twl_withdrawal_gives_oshad_schedule_and_water():
    a = assess(Conditions(temp_c=45, rh_pct=40, sun=True, wind_ms=0.5), Worker("light"))
    assert a.twl_zone == "withdrawal" and a.level == 4
    assert "permit" in a.schedule and "1.2 L" in a.hydration


def test_twl_skipped_for_impermeable_suit():
    a = assess(Conditions(temp_c=35, rh_pct=40, sun=False), Worker("light", clothing="vapour_barrier_suit"))
    assert a.twl is None
