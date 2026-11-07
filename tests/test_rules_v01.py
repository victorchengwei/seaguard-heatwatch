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
