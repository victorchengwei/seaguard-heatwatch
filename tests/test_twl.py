import pytest

import heatwatch.twl as T
from heatwatch.twl import assess_twl, twl, zone_for


def test_reference_point_light_clothing():
    """Published example: dry 33 C, wet 28 C, 0.5 m/s -> about 174 W/m2 (heatrules.com,
    beta TWL implementation). Light clothing (0.35-0.5 clo) must bracket it within 15%."""
    T.TWL_CLOTHING["_light"] = (0.35, 0.45)
    T.TWL_CLOTHING["_medium"] = (0.5, 0.45)
    try:
        hi = twl(33, 28, 33, 0.5, clothing="_light")
        lo = twl(33, 28, 33, 0.5, clothing="_medium")
    finally:
        T.TWL_CLOTHING.pop("_light")
        T.TWL_CLOTHING.pop("_medium")
    assert lo * 0.85 <= 174 <= hi * 1.15


def test_valid_range_and_direction():
    cool = twl(28, 22, 28, 2.0)
    hot = twl(40, 28, 52, 0.5)
    assert 0 <= hot < cool <= T.TWL_MAX
    # hotter wet bulb -> lower TWL
    assert twl(35, 30, 35, 1) < twl(35, 26, 35, 1)
    # sun (higher globe) -> lower TWL
    assert twl(35, 26, 50, 1) < twl(35, 26, 35, 1)
    # more wind helps in these conditions
    assert twl(35, 26, 35, 3) > twl(35, 26, 35, 0.5)
    # heavier clothing -> lower TWL
    assert twl(35, 26, 35, 1, clothing="double_layer_coveralls") < twl(35, 26, 35, 1)


def test_impermeable_suit_not_valid():
    assert twl(35, 26, 35, 1, clothing="vapour_barrier_suit") is None
    r = assess_twl(35, 26, 35, 1, clothing="vapour_barrier_suit")
    assert r.zone == "not_valid" and r.twl is None


@pytest.mark.parametrize("value,zone", [
    (300, "unrestricted"), (220.1, "unrestricted"), (220, "acclimatisation"),
    (140, "acclimatisation"), (139.9, "buffer"), (115, "buffer"), (114.9, "withdrawal"),
])
def test_zone_limits(value, zone):
    assert zone_for(value, 30, 20) == zone


def test_extreme_dry_or_wet_bulb_forces_withdrawal():
    assert zone_for(250, 44.5, 20) == "withdrawal"
    assert zone_for(250, 35, 32.5) == "withdrawal"


def test_missing_wind_is_failsafe():
    calm = assess_twl(36, 27, 45)
    windy = assess_twl(36, 27, 45, v=3)
    assert calm.twl < windy.twl
    assert any("Wind unknown" in r for r in calm.reasons)


def test_withdrawal_rules_mention_permit_and_water():
    r = assess_twl(42, 30, 54, 0.5)
    assert r.zone == "withdrawal"
    text = " ".join(r.rules)
    assert "permit" in text and "1.2 L" in text and "20 min work" in text
