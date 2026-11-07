import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd
from heatwatch.backtest import run, in_midday_ban

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "open_meteo_abu_dhabi_2025_may_sep.csv"


def test_midday_ban_window():
    assert in_midday_ban(pd.Timestamp("2025-07-01 13:00"))
    assert not in_midday_ban(pd.Timestamp("2025-07-01 10:00"))
    assert not in_midday_ban(pd.Timestamp("2025-06-01 13:00"))  # before 15 June


def test_safety_margin_reduces_misses():
    no = run(str(DATA), "moderate", margin_c=0.0)
    yes = run(str(DATA), "moderate", margin_c=2.0)
    assert yes["sim_miss_rate_pct"] < no["sim_miss_rate_pct"]


def test_backtest_uses_full_season():
    r = run(str(DATA), "moderate")
    assert r["days_total"] == 153 and r["daytime_hours"] == 153 * 13


def test_gap_and_movable_reported():
    from heatwatch.backtest import run
    r = run(DATA, workload="moderate")
    g = r["high_hours_vs_midday_ban"]
    assert abs(sum(g.values()) - 100) < 0.5
    assert 0 <= r["movable_high_hours_pct"] <= 100


def test_cooling_what_if_reduces_high_hours():
    from heatwatch.backtest import cooling_what_if
    r = cooling_what_if(str(DATA), "moderate", offsets=(0.0, 1.0, 2.0))["results"]
    assert r["0"]["reduction_pct"] == 0.0
    assert 0 < r["1"]["reduction_pct"] < r["2"]["reduction_pct"] < 100
