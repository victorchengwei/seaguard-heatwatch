import json
import shutil
import subprocess
from pathlib import Path

import pytest

from heatwatch.reminders import acclim_pct, run_day

ROOT = Path(__file__).resolve().parents[1]


def shift(level, regime, minutes=120, fasting=False, meal_at=None):
    return [{"minute": m, "level": level, "regime": regime, "fasting": fasting, "mealAt": meal_at}
            for m in range(minutes)]


def buzzes(out):
    return [o["buzz"] for o in out if o["buzz"]]


def codes(out):
    return [c for b in buzzes(out) for c in b["codes"]]


def test_water_never_more_than_14_l_per_hour():
    out = run_day(shift(3, "25-50", 180))
    cups = [b["minute"] for b in buzzes(out) if "drink" in b["codes"]]
    for m in range(180):
        assert sum(1 for c in cups if m - 60 < c <= m) * 0.25 <= 1.4


def test_water_more_often_when_hotter():
    assert codes(run_day(shift(2, "50-75"))).count("drink") > codes(run_day(shift(1, "75-100"))).count("drink")


def test_rest_countdown_follows_schedule():
    out = run_day(shift(2, "50-75", 61))
    seq = [(b["minute"], c) for b in buzzes(out) for c in b["codes"] if c in ("rest_soon", "rest_now", "back_to_work")]
    assert seq == [(40, "rest_soon"), (45, "rest_now"), (60, "back_to_work")]


def test_fasting_no_water_and_stricter_rest():
    out = run_day(shift(2, "50-75", 120, fasting=True))
    c = codes(out)
    assert "drink" not in c and "fast_cool" in c
    assert out[0]["regime"] == "25-50"


def test_stop_level_only_cool_down():
    c = codes(run_day(shift(4, "25-50", 30)))
    assert set(c) == {"cool_down"} and c.count("cool_down") == 3


def test_meal_reminders():
    c = codes(run_day(shift(1, "75-100", 60, meal_at=50)))
    assert "meal_soon" in c and "meal_now" in c


def test_alarm_limit_merges_non_urgent():
    out = run_day(shift(2, "50-75", 120, meal_at=45))
    times = [b["minute"] for b in buzzes(out)]
    for a, b in zip(times, times[1:]):
        urgent = any(c in ("rest_now", "back_to_work", "cool_down") for c in out[b]["buzz"]["codes"])
        assert urgent or b - a >= 5


def test_acclimatisation_table():
    assert [acclim_pct(d, True) for d in range(1, 7)] == [20, 40, 60, 80, 100, 100]
    assert [acclim_pct(d, False) for d in range(1, 5)] == [50, 60, 80, 100]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_reminders_match_python():
    cases = [shift(1, "75-100", 90, meal_at=50), shift(3, "25-50", 130),
             shift(2, "50-75", 120, fasting=True), shift(4, "0-25", 40)]
    js = ("const r=require(process.argv[1]);const cases=JSON.parse(process.argv[2]);"
          "console.log(JSON.stringify(cases.map(c=>r.runDay(c))));")
    out = subprocess.run(["node", "-e", js, str(ROOT / "static" / "reminders.js"), json.dumps(cases)],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [run_day(c) for c in cases]
