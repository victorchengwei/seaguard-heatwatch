"""Guided demo: a simulated crew replayed minute by minute.

Every value here is SIMULATED (from data/simulated/). The demo replays the
same streams the benchmark uses, through the same assess_c() logic, so what
judges see on screen is exactly what was measured.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from heatwatch.physiology import Profile, assess_c, readings_from_rows
from heatwatch.privacy import aggregate
from heatwatch.wellbeing import checkin_rate

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "data" / "simulated"
STEP_ROWS = 6  # one evaluation per minute (readings every 10 s)

# Fictional crew. Worker ids only; no names (privacy by design).
CREW = [
    {"worker": "W01", "case": "B02", "role": "Port deckhand", "role_ar": "عامل سطح في الميناء",
     "story": "Normal shift in mild heat: stays GREEN.", "sector": "Port"},
    {"worker": "W02", "case": "T01", "role": "Cargo lifting", "role_ar": "رفع البضائع",
     "story": "A 20-second 195 bpm spike while lifting is ignored: no false alarm.", "sector": "Logistics"},
    {"worker": "W03", "case": "T02", "role": "Mooring team", "role_ar": "فريق الإرساء",
     "story": "Band slips off the wrist (HR 0): treated as missing, never as zero, never GREEN.",
     "sector": "Port"},
    {"worker": "W04", "case": "T23", "role": "Yard logistics", "role_ar": "لوجستيات الساحة",
     "story": "Worker declined the band: consent gate, environment-only level.", "sector": "Logistics"},
    {"worker": "W05", "case": "T24", "role": "Tank cleaning, vapour-barrier suit",
     "role_ar": "تنظيف الخزانات ببدلة عازلة",
     "story": "Protective suit adds 11 C to effective heat: RED before the body estimate catches up.",
     "sector": "Construction"},
    {"worker": "W06", "case": "T10", "role": "Offshore platform, no network", "role_ar": "منصة بحرية بدون شبكة",
     "story": "No network: the band still raises RED on its own.", "sector": "Offshore"},
    {"worker": "W07", "case": "B11", "role": "Welder on deck", "role_ar": "لحام على السطح",
     "story": "Reads GREEN on body signals alone (one of the late AMBER cases). Try the daily check-in: "
              "'tired' or 'slept badly' makes HIS limits stricter, so he gets an AMBER break sooner. "
              "Nobody sees his answer.", "sector": "Construction"},
]


@lru_cache(maxsize=1)
def _load():
    streams, truth = defaultdict(list), defaultdict(list)
    with open(SIM / "streams.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            streams[r["case_id"]].append(r)
    with open(SIM / "truth.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[r["case_id"]].append(r)
    profiles = {p["case_id"]: p for p in json.loads((SIM / "profiles.json").read_text(encoding="utf-8"))}
    return streams, truth, profiles


def _profile(p, extra=False):
    return Profile(p["age"], p["acclimatised_days"], p["workload"],
                   p.get("consent", True), p.get("clothing", "work_clothes"), extra)


@lru_cache(maxsize=None)
def timeline(case_id: str, extra: bool = False) -> list:
    """Result at every minute of the trace (streaming replay).

    extra=True: the worker's own daily check-in asked for extra caution.
    """
    streams, truth, profiles = _load()
    rows, prof = streams[case_id], _profile(profiles[case_id], extra)
    ref = {int(float(t["t_s"])): t["ref_core_c"] for t in truth[case_id]}
    out = []
    for k in range(STEP_ROWS, len(rows) + 1, STEP_ROWS):
        r = assess_c(readings_from_rows([dict(x) for x in rows[:k]]), prof)
        t = int(float(rows[k - 1]["t_s"]))
        rc = ref.get(t, "")
        out.append({"minute": k // STEP_ROWS, "t_s": t, "level": r.level, "reasons": r.reasons,
                    "flags": r.flags, "stages": r.stages,
                    # technical view only (judges), clearly SIMULATED:
                    "core_est": r.core_est, "ref_core": float(rc) if rc not in ("", None) else None,
                    "hr": None if r.hr_sustained is None else round(r.hr_sustained),
                    "wbgt": r.wbgt})
    return out


def crew() -> list:
    out = []
    for c in CREW:
        tl = timeline(c["case"])
        first = {lvl: next((p["minute"] for p in tl if p["level"] == lvl), None)
                 for lvl in ("AMBER", "RED", "DATA GAP")}
        out.append({**c, "minutes": len(tl), "first_alert": first})
    return out


def state_at(minute: int, caution: frozenset = frozenset()) -> dict:
    """Crew board at one minute: colours only, plus the site aggregate.

    caution: workers whose own check-in asked for extra caution. The board
    shows only the resulting colour, never the check-in answer.
    """
    board = []
    for c in CREW:
        tl = timeline(c["case"], c["worker"] in caution)
        p = tl[min(max(minute, 1), len(tl)) - 1]
        board.append({"worker": c["worker"], "level": p["level"]})
    return {"minute": minute, "board": board,
            "site_report": aggregate([b["level"] for b in board]),
            "checkin_rate": checkin_rate(5, len(CREW)),  # SIMULATED fixed rate; never depends on any answer
            "label": "SIMULATED"}


def worker_at(worker: str, minute: int, extra: bool = False) -> dict:
    c = next(x for x in CREW if x["worker"] == worker)
    tl = timeline(c["case"], extra)
    p = tl[min(max(minute, 1), len(tl)) - 1]
    return {**c, **p, "label": "SIMULATED"}
