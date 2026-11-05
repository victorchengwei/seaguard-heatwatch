"""SIMULATED sensor streams for the HeatWatch benchmark and demo.

Every value produced here is synthetic. No real worker data is used.

For each benchmark case (data/benchmark/cases.csv) this module builds:
  * streams.csv  - what the system is allowed to see: wearable heart rate,
                   skin temperature, motion, battery, site and weather WBGT,
                   network state, one reading every 10 s.
  * truth.csv    - the reference core temperature of each simulated trace.
                   Approach C must NOT read this file; it estimates core
                   temperature from the heart-rate series itself and is
                   scored against this file.
  * profiles.json - worker profile per case (age, acclimatisation, workload).
  * manifest.csv - one line per case: rows, duration, injected data issue.

Shape of a normal trace: heart rate rises from rest towards the case's
sustained value (time constant 4 min) and holds it for the final part of
the trace, so "sustained >= 2 min" rules can fire. The reference core
temperature rises smoothly (S-curve) from 37.0 C, reaches the case's
reference value at two-thirds of the trace and holds it to the end.
The reference core is a designed ramp, not output of a physiological
model, so estimator error measures agreement with the case design only.

Data issues from the case set are injected exactly where the case says:
motion spikes, band off-wrist, cooled skin, wrong units, impossible WBGT,
low battery, no network, missing profile, missing signals, slow trend,
single-reading spike, slow recovery, clock drift and duplicate packets.

Usage:
    python -m heatwatch.simulate            # writes data/simulated/
    python -m heatwatch.simulate --out DIR --cases FILE
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

STEP_S = 10                 # one reading every 10 s (as in the project brief)
DEFAULT_MIN = 30            # normal trace length, minutes
SLOW_TREND_MIN = 120        # T14: two-hour rise
REST_HR = {"Light": 72, "Moderate": 78, "Heavy": 82}
START_CORE = 37.0
HR_TAU_S = 240.0            # heart-rate time constant
START_TIME = "2026-07-15T13:00:00+04:00"  # a UAE summer afternoon

STREAM_COLS = ["case_id", "t_s", "timestamp", "seq", "hr_bpm", "skin_c", "skin_unit",
               "motion_g", "battery_pct", "site_wbgt_c", "weather_wbgt_c",
               "network_up", "label"]
TRUTH_COLS = ["case_id", "t_s", "ref_core_c", "label"]
LABEL = "SIMULATED"


def _num(x):
    if x is None:
        return None
    x = str(x).strip()
    if x in ("", "None", "nan", "NaN"):
        return None
    return float(x)


def _issue(row) -> str:
    v = (row.get("data_issue") or "").strip()
    return "" if v in ("None", "nan") else v


def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _timestamp(t_s: int) -> str:
    # Fixed date, so files are reproducible; seconds offset from START_TIME.
    base_h, base_m = 13, 0
    total = base_h * 3600 + base_m * 60 + t_s
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"2026-07-15T{h % 24:02d}:{m:02d}:{s:02d}+04:00"


def _approach(start: float, end: float, t: float, tau: float) -> float:
    return end + (start - end) * math.exp(-t / tau)


def _ramp(start: float, end: float, t: float, reach_s: float) -> float:
    """Smooth S-curve from start to end, reached at reach_s, then held."""
    x = min(max(t / reach_s, 0.0), 1.0)
    return start + (end - start) * (3 * x * x - 2 * x * x * x)


def build_case(row: dict) -> tuple[list[dict], list[dict], dict]:
    cid = row["case_id"]
    rng = random.Random(f"heatwatch-{cid}")
    issue = _issue(row)
    workload = row["workload"]
    hr_target = _num(row["sustained_hr_bpm"])
    skin_target = _num(row["skin_c"])
    if issue == "Wrong units" and skin_target is not None and skin_target > 50:
        skin_target = (skin_target - 32) * 5 / 9   # case value is in deg F; simulate in C first
    core_target = _num(row["ref_core_c"])
    wbgt = _num(row["wbgt_c"])

    minutes = SLOW_TREND_MIN if issue == "Slow trend" else DEFAULT_MIN
    n = minutes * 60 // STEP_S
    hr_tau = HR_TAU_S * (4 if issue == "Slow trend" else 1)
    # reference core reaches the case value at 2/3 of the trace (90% for the slow trend)
    reach_s = minutes * 60 * (0.9 if issue == "Slow trend" else 2 / 3)
    rest_hr = REST_HR.get(workload, 78)

    streams, truth = [], []
    for i in range(n):
        t = i * STEP_S
        # --- heart rate
        if hr_target is None:
            hr = None
        else:
            hr = _approach(rest_hr, hr_target, t, hr_tau) + rng.gauss(0, 2.0)
        # --- skin temperature (rises towards target, small noise)
        skin = None if skin_target is None else _approach(33.0, skin_target, t, 300.0) + rng.gauss(0, 0.05)
        # --- reference core
        core = None if core_target is None else _ramp(START_CORE, core_target, t, reach_s)
        motion = {"Light": 0.15, "Moderate": 0.35, "Heavy": 0.6}.get(workload, 0.3) + abs(rng.gauss(0, 0.05))
        site_wbgt = wbgt
        weather_wbgt = None if wbgt is None else wbgt
        battery = 80.0 - 0.01 * i
        net = True
        skin_unit = "C"

        # --- injected data issues (exactly as described in the case set)
        if issue == "Motion artefact" and 900 <= t < 920:
            hr = 195.0                                   # 20 s spike while lifting
        if issue == "Band off-wrist" and t >= minutes * 60 - 600:
            hr, skin = 0.0, 30.0                         # last 10 min off wrist
        if issue in ("Skin cooled by water", "Skin cooled by wind") and t >= minutes * 60 - 600:
            skin = skin_target + rng.gauss(0, 0.05)      # skin already cooled; core stays high
        if issue == "Wrong units" and skin is not None:
            skin, skin_unit = skin * 9 / 5 + 32, "F"     # device sends deg F by mistake
        if issue == "Impossible value":
            site_wbgt = 55.0                             # broken site sensor
            weather_wbgt = 28.0                          # plausible weather-feed value
        if issue == "Low battery":
            battery = max(5.0, 12.0 - 0.04 * i)
        if issue == "No network":
            net = False
        if issue == "All signals missing":
            hr = skin = site_wbgt = weather_wbgt = None
        if issue == "HR missing":
            hr = None
        if issue == "One-reading spike" and i == n - 30:
            core = 38.6                                  # one noisy reference reading
            hr = (hr or 0) + 25.0                        # matching single HR blip
        if cid == "T16" and t >= minutes * 60 - 60:
            motion = 0.05                                # 1 min rest; HR stays near 125
        streams.append({
            "case_id": cid, "t_s": t, "timestamp": _timestamp(t), "seq": i,
            "hr_bpm": "" if hr is None else round(hr, 1),
            "skin_c": "" if skin is None else round(skin, 2),
            "skin_unit": skin_unit,
            "motion_g": round(motion, 3), "battery_pct": round(battery, 1),
            "site_wbgt_c": "" if site_wbgt is None else round(site_wbgt, 1),
            "weather_wbgt_c": "" if weather_wbgt is None else round(weather_wbgt, 1),
            "network_up": int(net), "label": LABEL,
        })
        truth.append({"case_id": cid, "t_s": t,
                      "ref_core_c": "" if core is None else round(core, 2), "label": LABEL})

    # Packet-level issues on the finished stream.
    if issue == "Clock drift":
        # swap 12 neighbouring pairs so timestamps arrive out of order
        for k in range(12):
            j = rng.randrange(1, len(streams) - 1)
            streams[j], streams[j + 1] = streams[j + 1], streams[j]
    if issue == "Duplicates":
        dup_idx = sorted(rng.sample(range(len(streams)), 15))
        for j in reversed(dup_idx):
            streams.insert(j + 1, dict(streams[j]))

    age = _num(row["age"])
    acc = _num(row["acclimatised_days"])
    profile = {
        "case_id": cid,
        "age": None if (issue == "Profile missing" or age is None) else int(age),
        "acclimatised_days": None if (issue == "Profile missing" or acc is None) else int(acc),
        "workload": workload,
        "consent": issue != "No consent",
        "clothing": "vapour_barrier_suit" if issue == "PPE vapour-barrier suit" else "work_clothes",
        "label": LABEL,
    }
    return streams, truth, profile


def generate(cases_path: Path, out_dir: Path) -> dict:
    cases = load_cases(cases_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_s, all_t, profiles, manifest = [], [], [], []
    for row in cases:
        s, t, p = build_case(row)
        all_s += s
        all_t += t
        profiles.append(p)
        manifest.append({"case_id": row["case_id"], "rows": len(s),
                         "minutes": round(t[-1]["t_s"] / 60 + STEP_S / 60, 1),
                         "data_issue": _issue(row) or "none",
                         "expected_level": row["expected_level"], "label": LABEL})
    _write(out_dir / "streams.csv", STREAM_COLS, all_s)
    _write(out_dir / "truth.csv", TRUTH_COLS, all_t)
    _write(out_dir / "manifest.csv", list(manifest[0]), manifest)
    (out_dir / "profiles.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "ALL DATA IN THIS FOLDER IS SIMULATED. No real worker data.\n"
        "Generated by heatwatch/simulate.py from data/benchmark/cases.csv.\n"
        "streams.csv: what the system may read. truth.csv: reference core\n"
        "temperature for scoring only. Approach C must not read truth.csv.\n",
        encoding="utf-8")
    return {"cases": len(cases), "stream_rows": len(all_s), "out": str(out_dir)}


def _write(path: Path, cols: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Generate SIMULATED HeatWatch sensor streams.")
    ap.add_argument("--cases", type=Path, default=root / "data" / "benchmark" / "cases.csv")
    ap.add_argument("--out", type=Path, default=root / "data" / "simulated")
    a = ap.parse_args()
    print(generate(a.cases, a.out))


if __name__ == "__main__":
    main()
