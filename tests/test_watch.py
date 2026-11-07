import json
import pathlib
import shutil
import subprocess

import pytest

from heatwatch.watch import ectemp, run

ROOT = pathlib.Path(__file__).resolve().parents[1]


def first(rows, level):
    return next((r["minute"] for r in rows if r["outbound"]["level"] >= level), None)


def test_ectemp_rises_with_heart_rate_and_falls_back():
    up = ectemp([150] * 60)
    assert up[-1] > up[0] > 37.0
    down = ectemp([150] * 60 + [80] * 60)
    assert down[-1] < up[-1]


def test_normal_shift_stays_normal():
    assert max(r["outbound"]["level"] for r in run("normal")) == 1


def test_rising_strain_warns_before_stop():
    rows = run("rising", age=45)
    caution, stop = first(rows, 2), first(rows, 4)
    assert caution is not None and stop is not None and caution < stop
    assert "sustained_heart_rate_over_limit" in rows[stop]["outbound"]["reasons"]


def test_man_down_escalates_immediately():
    rows = run("man_down")
    stop = first(rows, 4)
    assert stop == 25 and rows[stop]["outbound"]["escalate"]
    assert "possible_man_down" in rows[stop]["outbound"]["reasons"]


def test_no_body_data_leaves_the_watch():
    for sc in ("normal", "rising", "man_down"):
        for r in run(sc):
            assert set(r["outbound"]) == {"level", "reasons", "escalate"}
            text = json.dumps(r["outbound"])
            assert str(r["local"]["hr"]) not in text and "ct" not in r["outbound"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_watch_matches_python():
    js = (
        "const w=require(process.argv[1]);"
        "const s={age:45,acclimatized:true};"
        "console.log(JSON.stringify(['normal','rising','man_down'].map(n=>w.run(n,s))));"
    )
    out = subprocess.run(["node", "-e", js, str(ROOT / "static" / "watch.js")],
                         capture_output=True, text=True, check=True).stdout
    browser = json.loads(out)
    python = [run(n, age=45, acclimatized=True) for n in ("normal", "rising", "man_down")]
    for b_rows, p_rows in zip(browser, python):
        for b, p in zip(b_rows, p_rows):
            assert b["outbound"] == p["outbound"]
            assert b["local"]["hr"] == p["local"]["hr"]
            assert abs(b["local"]["ct_est"] - p["local"]["ct_est"]) < 0.011
