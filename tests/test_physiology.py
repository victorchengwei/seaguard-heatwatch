"""Safety tests for the physiology layer (guardrail, estimator, rules)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from heatwatch.physiology import (  # noqa: E402
    Profile, Reading, assess_b, assess_c, estimate_core, guardrail, rule_a,
)


def _stream(hr, n=180, skin=35.0, unit="C", wbgt=30.0, net=True, battery=80.0):
    return [Reading(t_s=i * 10, seq=i, hr=hr(i) if callable(hr) else hr, skin=skin,
                    skin_unit=unit, motion=0.4, battery=battery, site_wbgt=wbgt,
                    weather_wbgt=wbgt, network_up=net) for i in range(n)]


P = Profile(age=40, acclimatised_days=30, workload="Moderate")


def test_hr_zero_becomes_missing_never_zero():
    clean, flags = guardrail(_stream(0.0))
    assert all(r.hr is None for r in clean)
    assert any("off wrist" in f for f in flags)


def test_off_wrist_is_never_green():
    r = assess_c(_stream(0.0, wbgt=31.0), Profile(35, 20, "Heavy"))
    assert r.level == "AMBER" and "data gap" in r.flags


def test_no_signals_is_data_gap():
    r = assess_c(_stream(None, wbgt=None), P)
    assert r.level == "DATA GAP"


def test_fahrenheit_converted():
    clean, flags = guardrail(_stream(90.0, skin=96.8, unit="F"))
    assert abs(clean[0].skin - 36.0) < 0.05 and any("deg F" in f for f in flags)


def test_impossible_wbgt_uses_weather():
    s = _stream(90.0, wbgt=55.0)
    for r in s:
        r.weather_wbgt = 28.0
    clean, flags = guardrail(s)
    assert clean[-1].site_wbgt is None and any("impossible" in f for f in flags)


def test_duplicates_and_order():
    s = _stream(90.0)
    s = s[:10] + [s[5]] + s[10:]
    s[20], s[21] = s[21], s[20]
    clean, flags = guardrail(s)
    assert [r.seq for r in clean] == sorted({r.seq for r in s})
    assert any("duplicate" in f for f in flags) and any("order" in f for f in flags)


def test_short_spike_dropped():
    clean, flags = guardrail(_stream(lambda i: 195.0 if 90 <= i < 92 else 110.0))
    assert max(r.hr for r in clean if r.hr is not None) < 150
    assert any("artefact" in f for f in flags)


def test_missing_age_uses_conservative_default():
    r = assess_c(_stream(145.0), Profile(None, None, "Heavy"))
    assert any("default 40" in f for f in r.flags) and r.level in ("AMBER", "RED")


def test_high_hr_raises_level():
    assert assess_c(_stream(150.0), P).level in ("AMBER", "RED")
    assert assess_b(_stream(150.0), P).level in ("AMBER", "RED")


def test_estimator_rises_with_hr():
    low = estimate_core(_stream(80.0))[-1][1]
    high = estimate_core(_stream(150.0))[-1][1]
    assert high > low


def test_rule_a_unacclimatised_is_stricter():
    assert rule_a(26.0, Profile(30, 2, "Moderate")) != "GREEN"
    assert rule_a(26.0, Profile(30, 30, "Moderate")) == "GREEN"


def test_red_does_not_wait_for_explainer():
    r = assess_c(_stream(175.0, n=360), Profile(30, 30, "Heavy"))
    if r.level == "RED":
        assert "skipped" in r.stages["explainer"]


def test_no_consent_wearable_never_read():
    s = _stream(175.0, wbgt=31.0)
    r = assess_c(s, Profile(30, 30, "Heavy", consent=False))
    assert r.hr_sustained is None and r.core_est is None
    assert r.level == "AMBER" and "no consent" in r.stages["consent"]


def test_ppe_raises_environment_risk():
    plain = rule_a(27.0, Profile(38, 30, "Heavy"))
    suit = rule_a(27.0, Profile(38, 30, "Heavy", clothing="vapour_barrier_suit"))
    assert plain == "GREEN" and suit == "RED"


def test_never_less_safe_than_b_on_red():
    s = _stream(155.0, wbgt=34.0)
    p = Profile(40, 30, "Heavy")
    if assess_b(s, p).level == "RED":
        assert assess_c(s, p).level == "RED"
