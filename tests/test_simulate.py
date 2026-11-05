"""Checks that the SIMULATED streams match the benchmark case set."""
import csv
import json
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heatwatch.simulate import generate, load_cases  # noqa: E402

CASES = ROOT / "data" / "benchmark" / "cases.csv"


def _load(tmp_path):
    generate(CASES, tmp_path)
    streams = defaultdict(list)
    with open(tmp_path / "streams.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            streams[r["case_id"]].append(r)
    truth = defaultdict(list)
    with open(tmp_path / "truth.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[r["case_id"]].append(r)
    profiles = {p["case_id"]: p for p in json.loads((tmp_path / "profiles.json").read_text())}
    return streams, truth, profiles


def _f(x):
    return None if x == "" else float(x)


def test_every_case_present_and_labelled(tmp_path):
    s, t, p = _load(tmp_path)
    ids = [c["case_id"] for c in load_cases(CASES)]
    assert len(ids) == 52 and set(ids) == set(s) == set(t) == set(p)
    assert all(r["label"] == "SIMULATED" for rows in s.values() for r in rows)


def test_truth_not_in_streams(tmp_path):
    generate(CASES, tmp_path)
    header = (tmp_path / "streams.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "core" not in header


def test_sustained_hr_matches_case(tmp_path):
    s, _, _ = _load(tmp_path)
    for c in load_cases(CASES):
        hr = _f(c["sustained_hr_bpm"]) if c["sustained_hr_bpm"] not in ("", "None") else None
        if hr is None or c["data_issue"] not in ("", "None"):
            continue
        last = [_f(r["hr_bpm"]) for r in s[c["case_id"]][-12:]]   # last 2 minutes
        assert all(abs(v - hr) < 8 for v in last), c["case_id"]


def test_reference_core_reaches_case_value(tmp_path):
    _, t, _ = _load(tmp_path)
    for c in load_cases(CASES):
        if c["ref_core_c"] in ("", "None") or c["data_issue"] == "One-reading spike":
            continue
        last = [_f(r["ref_core_c"]) for r in t[c["case_id"]][-12:]]
        assert all(abs(v - float(c["ref_core_c"])) < 0.01 for v in last), c["case_id"]


def test_injected_issues(tmp_path):
    s, t, p = _load(tmp_path)
    assert max(_f(r["hr_bpm"]) for r in s["T01"]) >= 195                    # motion spike
    assert _f(s["T02"][-1]["hr_bpm"]) == 0 and _f(s["T02"][-1]["skin_c"]) == 30  # off wrist
    assert all(r["hr_bpm"] == "" for r in s["S06"])                          # HR missing
    assert all(r["hr_bpm"] == "" and r["site_wbgt_c"] == "" for r in s["T12"])   # all missing
    assert s["T07"][-1]["skin_unit"] == "F" and _f(s["T07"][-1]["skin_c"]) > 90  # deg F
    assert _f(s["T08"][0]["site_wbgt_c"]) == 55 and _f(s["T08"][0]["weather_wbgt_c"]) < 40
    assert _f(s["T09"][-1]["battery_pct"]) <= 5.5                            # low battery
    assert all(r["network_up"] == "0" for r in s["T10"])                     # no network
    assert p["T11"]["age"] is None                                           # profile missing
    assert len(s["T14"]) == 720                                              # 2-hour trend
    seqs = [int(r["seq"]) for r in s["T20"]]
    assert seqs != sorted(seqs)                                              # clock drift
    seq21 = [int(r["seq"]) for r in s["T21"]]
    assert len(seq21) > len(set(seq21))                                      # duplicates


def test_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(CASES, a)
    generate(CASES, b)
    assert (a / "streams.csv").read_bytes() == (b / "streams.csv").read_bytes()
