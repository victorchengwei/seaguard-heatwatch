"""Supervisor view: crew-level status and a work-window planner.

Privacy by design: the supervisor sees crew colours and actions only,
never a worker's personal data or health information.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .rules import REGIMES, SCHEDULE, Conditions, Worker, assess
import math


def solar_share(hour: int) -> float:
    """Rough share of midday sun by local hour (0 at night, 1 at noon)."""
    return max(0.0, math.sin(math.pi * (hour - 6) / 12))


@dataclass
class Crew:
    name: str
    location: str
    workload: str = "moderate"
    clothing: str = "work_clothes"
    sun: bool = True
    size: int = 4
    unacclimatized: int = 0  # how many members are new (count only, no names)
    minutes_worked: int = 0
    unwell_reports: int = 0  # count only


def crew_status(crew: Crew, temp_c: Optional[float], rh_pct: Optional[float],
                stale: bool = False, solar: float = 1.0) -> dict:
    """Level for the crew = the most protective level of its members."""
    cond = Conditions(temp_c=temp_c, rh_pct=rh_pct, sun=crew.sun, stale=stale, solar=solar)
    a = assess(cond, Worker(crew.workload, crew.clothing, True, False, crew.minutes_worked))
    level, reasons, action = a.level, list(a.reasons), a.action
    order = list(REGIMES) + ["stop"]
    regime = a.work_rest
    if crew.unacclimatized:
        b = assess(cond, Worker(crew.workload, crew.clothing, False, False, crew.minutes_worked))
        if b.level > level:
            level, action = b.level, b.action
        if order.index(b.work_rest) > order.index(regime):
            regime = b.work_rest  # the strictest schedule protects the newest member
        reasons.append(f"{crew.unacclimatized} new member(s): stricter limit applied to the crew.")
    if crew.unwell_reports:
        level, action = 4, "Stop work, cool down, call the medic."
        reasons.append(f"{crew.unwell_reports} member(s) reported feeling unwell.")
    labels = {1: "Normal", 2: "Caution", 3: "High", 4: "Stop work"}
    schedule = SCHEDULE["stop"] if level == 4 else SCHEDULE[regime]
    return {"crew": crew.name, "location": crew.location, "size": crew.size,
            "level": level, "label": labels[level], "action": action, "schedule": schedule,
            "effective_wbgt": a.effective_wbgt, "twl": a.twl, "oshad_zone": a.oshad_zone,
            "reasons": reasons}


def plan_windows(forecast: List[dict], workload: str, clothing: str = "work_clothes",
                 sun: bool = True, min_hours: int = 2) -> dict:
    """Find the coolest block of consecutive hours with level <= 2.

    forecast: [{"hour": "2026-07-15T06:00", "temp_c": 31, "rh_pct": 60}, ...]
    """
    rows = []
    for f in forecast:
        h = int(f["hour"][11:13])
        a = assess(Conditions(f["temp_c"], f["rh_pct"], sun, solar=solar_share(h)), Worker(workload, clothing))
        rows.append({**f, "level": a.level, "wbgt": a.effective_wbgt})

    best, run = None, []
    for r in rows + [None]:
        if r is not None and r["level"] <= 2:
            run.append(r)
            continue
        if len(run) >= min_hours:
            score = sum(x["wbgt"] for x in run) / len(run)
            if best is None or score < best[0]:
                best = (score, list(run))
        run = []

    if best is None:
        rec = (f"No {min_hours}-hour window is safe for {workload} work in the forecast. "
               "Postpone the task, split it into short shifts in shade, or reduce workload.")
        window = None
    else:
        start, end = best[1][0]["hour"], best[1][-1]["hour"]
        window = {"start": start, "end": end, "hours": len(best[1])}
        rec = f"Schedule {workload} work from {start[-5:]} to {end[-5:]} (coolest safe window)."
    return {"workload": workload, "window": window, "recommendation": rec, "hours": rows}
