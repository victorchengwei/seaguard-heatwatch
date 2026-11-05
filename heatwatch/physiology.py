"""HeatWatch physiology layer: sensor guardrail, core-temperature estimate
and body-based risk rules (approaches A, B and C of the benchmark).

Fixed, auditable code. No AI is used here.

Safety principles
  * A missing value stays None. It never becomes zero.
    (A band off the wrist reports heart rate 0; that is treated as missing.)
  * Missing data never lowers a level.
  * A personal baseline may only make alerts stricter, never looser.
  * The core temperature is an ESTIMATE from heart rate, not a measurement.

Core-temperature estimate: extended Kalman filter of Buller et al. (2013),
"Estimation of human core temperature from sequential heart rate
observations", Physiol. Meas. 34:781-798. Published parameters, one step per
minute. Validated mainly in military volunteers; it must be validated for
port and offshore workers before any field use.

DRAFT thresholds (from the benchmark Guide sheet): verify with the clinical
mentors before submission.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Iterable, Optional

from heatwatch.rules import CLOTHING  # ACGIH clothing adjustment values

# ----------------------------------------------------------------- thresholds
CORE_AMBER = 38.0           # deg C, estimated core
CORE_RED = 38.5             # deg C, sustained >= RED_SUSTAIN_S
RED_SUSTAIN_S = 120         # 2 minutes
HR_WINDOW_S = 120           # "sustained" heart rate = median of last 2 min
DEFAULT_AGE = 40            # conservative default when age is missing
UNACCL_DAYS = 7             # fewer days = not acclimatised
CAUTION_HR = 10             # bpm off the HR limit on an "extra caution" day
CAUTION_CORE = 0.2          # deg C off the AMBER core threshold on an "extra caution" day
SLOW_RECOVERY_HR = 120      # bpm still above this after 1 min rest -> AMBER

# Rule A: ACGIH 2026 screening criteria (WBGT deg C), 75-100 % work.
# Heavy has no 75-100 % value, so the 50-75 % row is used. DRAFT.
WBGT_LIMIT = {  # workload: (acclimatised, unacclimatised or unknown)
    "Light": (31.0, 28.0),
    "Moderate": (28.0, 25.0),
    "Heavy": (27.5, 24.0),
}
WBGT_RED_MARGIN = 3.0       # team assumption, confirm with mentors

# Guardrail limits
HR_MIN_VALID, HR_MAX_VALID = 30.0, 220.0
SPIKE_MAX_S = 60            # a jump lasting <= 60 s above the median is an artefact
SPIKE_JUMP = 30.0           # bpm above the rolling median
WBGT_MIN_VALID, WBGT_MAX_VALID = 0.0, 45.0
LOW_BATTERY = 10.0          # percent

LEVELS = ("GREEN", "AMBER", "RED")
RANK = {"GREEN": 0, "AMBER": 1, "RED": 2, "DATA GAP": 1}


# ------------------------------------------------------------ data structures
@dataclass
class Reading:
    t_s: int
    seq: int
    hr: Optional[float]
    skin: Optional[float]
    skin_unit: str
    motion: Optional[float]
    battery: Optional[float]
    site_wbgt: Optional[float]
    weather_wbgt: Optional[float]
    network_up: bool


@dataclass
class Profile:
    age: Optional[int]
    acclimatised_days: Optional[int]
    workload: str
    consent: bool = True            # wearable data may be read only with consent
    clothing: str = "work_clothes"  # PPE adds a clothing adjustment to WBGT
    extra_caution: bool = False     # worker's own daily check-in (tired, stressed, poor sleep):
                                    # limits only ever get STRICTER, never looser


@dataclass
class Result:
    level: str
    reasons: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    core_est: Optional[float] = None
    hr_sustained: Optional[float] = None
    wbgt: Optional[float] = None
    stages: dict = field(default_factory=dict)


# ------------------------------------------------------------------- guardrail
def _f(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    x = str(x).strip()
    return None if x in ("", "None", "nan") else float(x)


def readings_from_rows(rows: Iterable[dict]) -> list:
    out = []
    for r in rows:
        out.append(Reading(
            t_s=int(float(r["t_s"])), seq=int(float(r["seq"])),
            hr=_f(r.get("hr_bpm")), skin=_f(r.get("skin_c")),
            skin_unit=(r.get("skin_unit") or "C").strip() or "C",
            motion=_f(r.get("motion_g")), battery=_f(r.get("battery_pct")),
            site_wbgt=_f(r.get("site_wbgt_c")), weather_wbgt=_f(r.get("weather_wbgt_c")),
            network_up=str(r.get("network_up", "1")).strip() in ("1", "True", "true"),
        ))
    return out


def guardrail(readings: list) -> tuple:
    """Clean the stream. Returns (clean_readings, flags)."""
    flags = []
    # 1. Duplicates (same seq) and clock drift (out of order).
    seen, uniq = set(), []
    for r in readings:
        if r.seq in seen:
            continue
        seen.add(r.seq)
        uniq.append(r)
    if len(uniq) < len(readings):
        flags.append(f"{len(readings) - len(uniq)} duplicate packets removed")
    if [r.seq for r in uniq] != sorted(r.seq for r in uniq):
        flags.append("readings out of order: re-sorted")
    uniq.sort(key=lambda r: r.seq)

    off_wrist = 0
    unit_fixed = False
    wbgt_rejected = False
    for r in uniq:
        # 2. Units: skin temperature sent in deg F.
        if r.skin is not None and (r.skin_unit.upper() == "F" or r.skin > 50):
            r.skin = round((r.skin - 32) * 5 / 9, 2)
            r.skin_unit = "C"
            unit_fixed = True
        # 3. Band off wrist: HR 0 or impossible -> missing, never zero.
        if r.hr is not None and not (HR_MIN_VALID <= r.hr <= HR_MAX_VALID):
            r.hr = None
            off_wrist += 1
        # 4. Impossible site WBGT -> use weather feed.
        if r.site_wbgt is not None and not (WBGT_MIN_VALID <= r.site_wbgt <= WBGT_MAX_VALID):
            r.site_wbgt = None
            wbgt_rejected = True
    if unit_fixed:
        flags.append("skin temperature converted from deg F")
    if off_wrist:
        flags.append(f"band off wrist or invalid HR in {off_wrist} readings: treated as missing, refit band")
    if wbgt_rejected:
        flags.append("site WBGT sensor value impossible: weather feed used, check sensor")

    # 5. Short spikes (motion artefact): drop HR > median + SPIKE_JUMP for <= SPIKE_MAX_S.
    hrs = [r.hr for r in uniq]
    dropped = 0
    i = 0
    while i < len(uniq):
        window = [h for h in hrs[max(0, i - 12):i] if h is not None]
        if uniq[i].hr is not None and len(window) >= 6 and uniq[i].hr > median(window) + SPIKE_JUMP:
            j = i
            while j < len(uniq) and uniq[j].hr is not None and uniq[j].hr > median(window) + SPIKE_JUMP:
                j += 1
            if (uniq[min(j, len(uniq) - 1)].t_s - uniq[i].t_s) <= SPIKE_MAX_S and j < len(uniq):
                for k in range(i, j):
                    uniq[k].hr = None
                    dropped += 1
            i = j
        i += 1
    if dropped:
        flags.append(f"{dropped} HR readings dropped as motion artefact")

    if any(r.battery is not None and r.battery <= LOW_BATTERY for r in uniq[-6:]):
        flags.append("band battery low: tell supervisor")
    if uniq and not any(r.network_up for r in uniq):
        flags.append("no network: alert raised on band, sync later")
    return uniq, flags


# ---------------------------------------------------------- core temperature
# Buller et al. (2013) extended Kalman filter, published parameters.
_A, _GAMMA = 1.0, 0.022 ** 2
_B0, _B1, _B2 = -7887.1, 384.4286, -4.5714
_SIGMA = 18.88 ** 2
CT_START, V_START = 37.1, 0.0


def estimate_core(readings: list) -> list:
    """Per-minute core estimate from heart rate. Returns [(t_s, core)].
    Minutes without valid HR keep the last estimate (no update)."""
    if not readings:
        return []
    ct, v = CT_START, V_START
    out = []
    t0, t_end = readings[0].t_s, readings[-1].t_s
    by_min = {}
    for r in readings:
        if r.hr is not None:
            by_min.setdefault((r.t_s - t0) // 60, []).append(r.hr)
    for m in range(0, (t_end - t0) // 60 + 1):
        ct_p, v_p = _A * ct, _A * _A * v + _GAMMA          # predict
        hrs = by_min.get(m)
        if hrs:
            hr = sum(hrs) / len(hrs)
            c = 2 * _B2 * ct_p + _B1                       # observation slope
            k = v_p * c / (c * c * v_p + _SIGMA)            # Kalman gain
            ct = ct_p + k * (hr - (_B2 * ct_p ** 2 + _B1 * ct_p + _B0))
            v = (1 - k * c) * v_p
        else:
            ct, v = ct_p, v_p
        out.append((t0 + m * 60 + 59, ct))
    return out


# ------------------------------------------------------------------ helpers
def _sustained_hr(readings: list) -> Optional[float]:
    if not readings:
        return None
    end = readings[-1].t_s
    vals = [r.hr for r in readings if r.hr is not None and r.t_s > end - HR_WINDOW_S]
    return median(vals) if len(vals) >= 6 else None


def _wbgt(readings: list) -> Optional[float]:
    for r in reversed(readings[-6:]):
        if r.site_wbgt is not None:
            return r.site_wbgt
        if r.weather_wbgt is not None:
            return r.weather_wbgt
    return None


def _hr_limit(p: Profile) -> tuple:
    age = p.age if p.age is not None else DEFAULT_AGE
    return 180 - age, (p.age is None)


def _accl(p: Profile) -> bool:
    return p.acclimatised_days is not None and p.acclimatised_days >= UNACCL_DAYS


def rule_a(wbgt: Optional[float], p: Profile) -> str:
    """Approach A: WBGT only (today's practice)."""
    if wbgt is None:
        return "DATA GAP"
    wbgt = wbgt + CLOTHING.get(p.clothing, 0.0)   # effective WBGT with PPE
    acc, unacc = WBGT_LIMIT[p.workload]
    lim = acc if _accl(p) else unacc
    if wbgt >= lim + WBGT_RED_MARGIN:
        return "RED"
    return "AMBER" if wbgt >= lim else "GREEN"


def _cap_amber(level: str) -> str:
    return "AMBER" if level == "RED" else level


# --------------------------------------------------------------- approaches
def assess_a(readings: list, p: Profile) -> Result:
    clean, flags = guardrail(readings)
    w = _wbgt(clean)
    return Result(rule_a(w, p), [f"WBGT {w} C vs workload limit"] if w is not None else ["no WBGT"],
                  flags, wbgt=w)


def assess_b(readings: list, p: Profile) -> Result:
    """Approach B: WBGT rule + sustained heart rate (no core estimate).
    HR above 180-age -> AMBER. RED needs WBGT RED (with PPE adjustment) and HR above the limit.
    Without HR: rule A capped at AMBER."""
    if not p.consent:
        readings = [Reading(r.t_s, r.seq, None, None, "C", None, r.battery, r.site_wbgt,
                            r.weather_wbgt, r.network_up) for r in readings]
    clean, flags = guardrail(readings)
    w = _wbgt(clean)
    hr = _sustained_hr(clean)
    lim, _ = _hr_limit(p)
    if hr is None:
        if w is None:
            return Result("DATA GAP", ["no HR and no WBGT"], flags)
        return Result(_cap_amber(rule_a(w, p)), ["HR missing: WBGT fallback, max AMBER"], flags + ["data gap"], wbgt=w)
    a = rule_a(w, p)
    if a == "RED" and hr > lim:
        lvl = "RED"
    elif hr > lim or a in ("AMBER", "RED"):
        lvl = "AMBER"
    else:
        lvl = "GREEN"
    return Result(lvl, [f"HR {hr:.0f} vs limit {lim}", f"WBGT rule {a}"], flags, hr_sustained=hr, wbgt=w)


def assess_c(readings: list, p: Profile) -> Result:
    """Approach C (HeatWatch): guardrail + core estimate + body rules."""
    stages = {}
    if not p.consent:
        # Consent gate: wearable data is never read without consent.
        readings = [Reading(r.t_s, r.seq, None, None, "C", None, r.battery, r.site_wbgt,
                            r.weather_wbgt, r.network_up) for r in readings]
        stages["consent"] = "no consent: wearable not read (gate event logged)"
    else:
        stages["consent"] = "passed"
    clean, flags = guardrail(readings)
    if not p.consent:
        flags = [f for f in flags if "off wrist" not in f] + ["no wearable consent: environment-only level"]
    stages["sensor_guardrail"] = "passed" if not flags else "flagged"
    w = _wbgt(clean)
    hr = _sustained_hr(clean)
    lim, age_missing = _hr_limit(p)
    if age_missing:
        flags.append(f"age missing: conservative default {DEFAULT_AGE} (limit {lim})")
    reasons = []
    # Extra caution (worker's own check-in) lowers the AMBER thresholds only:
    # a hard day means an earlier break. RED thresholds never change.
    amber_c = CORE_AMBER - (CAUTION_CORE if p.extra_caution else 0.0)
    lim_a = lim - (CAUTION_HR if p.extra_caution else 0)
    if p.extra_caution:
        flags.append("daily check-in: extra caution today (stricter limits)")

    if hr is None:
        stages["physiology_analyzer"] = "skipped (no HR)"
        if w is None:
            stages["risk_rules"] = "held"
            return Result("DATA GAP", ["No body or environment signal: supervisor must check the worker in person."],
                          flags, stages=stages)
        lvl = _cap_amber(rule_a(w, p))
        stages["risk_rules"] = "fallback"
        return Result(lvl, [f"HR missing: WBGT {w} C fallback, max AMBER."], flags + ["data gap"],
                      wbgt=w, stages=stages)

    series = estimate_core(clean)
    core = series[-1][1] if series else None
    stages["physiology_analyzer"] = "passed"
    end = clean[-1].t_s
    above_red = [c for t, c in series if t > end - RED_SUSTAIN_S]
    red_sustained = len(above_red) >= 2 and all(c >= CORE_RED for c in above_red)

    env = rule_a(w, p)
    if red_sustained:
        lvl = "RED"
        reasons.append(f"Estimated core {core:.1f} C >= {CORE_RED} for 2 min.")
    elif env == "RED" and hr > lim:
        # Never less safe than approach B: the core estimate lags, so a hot
        # environment plus high heart rate raises RED without waiting for it.
        lvl = "RED"
        reasons.append(f"WBGT in danger zone and HR {hr:.0f} > {lim}: RED without waiting for the core estimate.")
    elif core is not None and core >= CORE_AMBER and hr > lim:
        lvl = "RED"
        reasons.append(f"Estimated core {core:.1f} C >= {CORE_AMBER} and HR {hr:.0f} > {lim}.")
    else:
        lvl = "GREEN"
        if core is not None and core >= amber_c:
            lvl = "AMBER"
            reasons.append(f"Estimated core {core:.1f} C >= {amber_c:.1f}.")
        if hr > lim_a:
            lvl = "AMBER"
            reasons.append(f"Sustained HR {hr:.0f} > limit {lim_a} (180 - age"
                           + (", minus 10 on an extra-caution day)." if p.extra_caution else ")."))
        if w is not None and w >= 32 and p.workload == "Heavy" and not _accl(p):
            lvl = "AMBER"
            reasons.append(f"WBGT {w} C, heavy work, not acclimatised.")
        resting = [r for r in clean if r.motion is not None and r.motion < 0.1 and r.t_s > end - 60]
        if resting and min(r.hr for r in resting if r.hr is not None) > SLOW_RECOVERY_HR:
            lvl = "AMBER"
            reasons.append("Slow heart-rate recovery after 1 min rest.")
    stages["risk_rules"] = "passed"
    stages["red_short_circuit"] = "fired" if lvl == "RED" else "not needed"
    stages["explainer"] = "skipped (RED alert does not wait)" if lvl == "RED" else "pending"
    if not reasons:
        reasons.append("All body and environment signals within limits. GREEN is not medical clearance.")
    return Result(lvl, reasons, flags, core_est=round(core, 2) if core else None,
                  hr_sustained=hr, wbgt=w, stages=stages)
