"""SeaGuard HeatWatch rules engine.

Fixed, auditable rules decide the heat-risk level. No AI is used here:
an AI layer may only explain the result in plain language afterwards.

Thresholds follow the ACGIH TLV / Action Limit work-rest table for heat
stress (WBGT, deg C). VERIFY every number against the current ACGIH TLV
booklet and with the clinical mentors before submission.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from heatwatch import twl as twl_mod

# ---------------------------------------------------------------- constants

WORKLOADS = ("light", "moderate", "heavy", "very_heavy")

# Work share of each hour -> limit per workload (None = not recommended).
# ACGIH TLV (acclimatized workers).
TLV = {
    "75-100": {"light": 31.0, "moderate": 28.0, "heavy": None, "very_heavy": None},
    "50-75": {"light": 31.0, "moderate": 29.0, "heavy": 27.5, "very_heavy": None},
    "25-50": {"light": 32.0, "moderate": 30.0, "heavy": 29.0, "very_heavy": 28.0},
    "0-25": {"light": 32.5, "moderate": 31.5, "heavy": 30.5, "very_heavy": 30.0},
}
# ACGIH Action Limit (unacclimatized workers): stricter.
ACTION_LIMIT = {
    "75-100": {"light": 28.0, "moderate": 25.0, "heavy": None, "very_heavy": None},
    "50-75": {"light": 28.5, "moderate": 26.0, "heavy": 24.0, "very_heavy": None},
    "25-50": {"light": 29.5, "moderate": 27.0, "heavy": 25.5, "very_heavy": 24.5},
    "0-25": {"light": 30.0, "moderate": 29.0, "heavy": 28.0, "very_heavy": 27.0},
}
REGIMES = ("75-100", "50-75", "25-50", "0-25")  # from most work to most rest

# Clothing adjustment factors (deg C-WBGT added to the measured WBGT).
CLOTHING = {
    "work_clothes": 0.0,
    "woven_coveralls": 0.0,
    "double_layer_coveralls": 3.0,
    "sms_polypropylene_coveralls": 0.5,
    "polyolefin_coveralls": 1.0,
    "vapour_barrier_suit": 11.0,
}

FAILSAFE_MARGIN = 2.0  # deg C added when inputs are missing or stale

LEVELS = {
    1: "Normal",
    2: "Caution",
    3: "High",
    4: "Stop work",
}
# Work-rest regime in plain words (share of each hour spent working).
SCHEDULE = {
    "75-100": "Normal work, usual breaks",
    "50-75": "Work 45 min, rest 15 min each hour",
    "25-50": "Work 30 min, rest 30 min each hour",
    "0-25": "Work 15 min, rest 45 min each hour",
    "stop": "No work in these conditions",
}

# Hydration (NIOSH, Heat Stress: Hydration, 2017): small, frequent drinks; too much can be harmful.
HYDRATION = {
    1: "Drink water regularly, before you feel thirsty.",
    2: "Drink 1 cup (about 250 ml) every 15-20 minutes; no more than 1.4 L per hour.",
    3: "Drink 1 cup (about 250 ml) every 15-20 minutes; no more than 1.4 L per hour.",
    4: "Cool down and sip water; no more than 1.4 L per hour. Dark or cola-coloured urine: tell the medic.",
}

ACTIONS = {
    1: "Drink water regularly.",
    2: "Drink water now, take shade breaks, check on your buddy.",
    3: "Rest in shade, rotate the crew, move heavy tasks to a cooler time.",
    4: "Stop work, cool down, call the medic or supervisor.",
}

# ------------------------------------------------------------------ physics


def vapour_pressure_hpa(temp_c: float, rh_pct: float) -> float:
    """Actual water-vapour pressure (hPa) from air temperature and RH."""
    es = 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    return rh_pct / 100.0 * es


GLOBE_EXCESS_SUN = 12.0  # deg C globe temperature above air in strong sun (conservative)


def wet_bulb_stull(temp_c: float, rh_pct: float) -> float:
    """Psychrometric wet-bulb temperature (Stull 2011), valid RH 5-99%."""
    t, rh = temp_c, rh_pct
    return (t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
            + math.atan(t + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
            - 4.686035)


def wbgt_estimate(temp_c: float, rh_pct: float, sun: bool = True, solar: float = 1.0) -> float:
    """Estimated WBGT (deg C) from air temperature and humidity.

    Shade/indoor: WBGT = 0.7*Tw + 0.3*Ta
    Sun:          WBGT = 0.7*Tw + 0.2*Tg + 0.1*Ta, Tg = Ta + 12 C x solar
    solar: 0..1 share of full midday sun (low in early morning / evening).
    Tw uses the psychrometric wet bulb as a stand-in for natural wet bulb.
    A measured WBGT always overrides this estimate.
    """
    tw = wet_bulb_stull(temp_c, rh_pct)
    if not sun:
        return 0.7 * tw + 0.3 * temp_c
    tg = temp_c + GLOBE_EXCESS_SUN * max(0.0, min(1.0, solar))
    return 0.7 * tw + 0.2 * tg + 0.1 * temp_c


# ------------------------------------------------------------------- inputs


@dataclass
class Conditions:
    """Site conditions. Any value may be None (missing sensor / forecast)."""

    temp_c: Optional[float] = None
    rh_pct: Optional[float] = None
    sun: bool = True
    measured_wbgt: Optional[float] = None  # from a WBGT sensor, if present
    stale: bool = False  # data older than the allowed age
    solar: float = 1.0  # 0..1 share of full midday sun
    wind_ms: Optional[float] = None  # wind speed at work height (m/s)
    pressure_hpa: Optional[float] = None
    measured_globe_c: Optional[float] = None  # black-globe temperature, if measured
    use_twl: bool = True  # ADOSH-SF Thermal Work Limit alongside WBGT (stricter wins)


@dataclass
class Worker:
    workload: str = "moderate"
    clothing: str = "work_clothes"
    acclimatized: bool = True
    stricter_limit: bool = False  # set by a clinician; reason never stored
    minutes_worked: int = 0  # in the current hot period
    feels_unwell: bool = False  # one-tap button
    needs_break: bool = False  # one-tap button


@dataclass
class Assessment:
    level: int
    label: str
    action: str
    effective_wbgt: Optional[float]
    limit_continuous: Optional[float]
    work_rest: str
    reasons: list = field(default_factory=list)
    escalate: bool = False
    schedule: str = ""
    hydration: str = ""
    twl: Optional[float] = None  # W/m2, estimate
    twl_zone: Optional[str] = None  # ADOSH zone key
    oshad_zone: Optional[str] = None  # zone name for display
    oshad_rules: list = field(default_factory=list)

    def __post_init__(self):
        self.hydration = self.hydration or HYDRATION[self.level]
        if self.level == 4:  # Stop work always means no work, whatever the table allows
            self.schedule = SCHEDULE["stop"]
        elif not self.schedule:
            self.schedule = SCHEDULE.get(self.work_rest, SCHEDULE["stop"])


# --------------------------------------------------------------------- core


def _limits(worker: Worker) -> dict:
    table = TLV if (worker.acclimatized and not worker.stricter_limit) else ACTION_LIMIT
    return {regime: table[regime][worker.workload] for regime in REGIMES}


def assess(cond: Conditions, worker: Worker) -> Assessment:
    if worker.workload not in WORKLOADS:
        raise ValueError(f"unknown workload: {worker.workload}")
    if worker.clothing not in CLOTHING:
        raise ValueError(f"unknown clothing: {worker.clothing}")

    reasons = []

    # 1. The worker's own report always wins.
    if worker.feels_unwell:
        return Assessment(
            4, LEVELS[4], ACTIONS[4], None, None, "stop",
            ["Worker reported feeling unwell: always escalates."], escalate=True,
        )

    # 2. Effective WBGT, fail-safe when data is missing or stale.
    if cond.measured_wbgt is not None:
        wbgt = cond.measured_wbgt
        reasons.append(f"Measured WBGT {wbgt:.1f} C.")
    elif cond.temp_c is not None and cond.rh_pct is not None:
        wbgt = wbgt_estimate(cond.temp_c, cond.rh_pct, cond.sun, cond.solar)
        reasons.append(
            f"Estimated WBGT {wbgt:.1f} C from {cond.temp_c:.0f} C and {cond.rh_pct:.0f}% humidity"
            + (" in sun." if cond.sun else " in shade.")
        )
    elif cond.temp_c is not None:
        wbgt = wbgt_estimate(cond.temp_c, 80.0, cond.sun, cond.solar) + FAILSAFE_MARGIN
        reasons.append("Humidity missing: assumed 80% plus safety margin.")
    else:
        # No data at all: never fail silent.
        return Assessment(
            3, LEVELS[3], ACTIONS[3] + " Use the printed work-rest card.", None, None,
            "25-50", ["No weather or sensor data: fail-safe level High."],
        )
    if cond.stale:
        wbgt += FAILSAFE_MARGIN
        reasons.append(f"Data is stale: +{FAILSAFE_MARGIN:.0f} C safety margin.")

    caf = CLOTHING[worker.clothing]
    if caf:
        reasons.append(f"Clothing adds {caf:.1f} C.")
    eff = wbgt + caf

    limits = _limits(worker)
    if not worker.acclimatized:
        reasons.append("Not acclimatized: stricter Action Limit applies.")
    if worker.stricter_limit:
        reasons.append("Clinician flag: stricter limit applies.")

    # 3. Most work that stays within the limit.
    work_rest = None
    for regime in REGIMES:
        lim = limits[regime]
        if lim is not None and eff <= lim:
            work_rest = regime
            break
    cont = limits["75-100"]

    if work_rest is None:
        level = 4
        reasons.append(f"Effective WBGT {eff:.1f} C exceeds every work-rest limit.")
    elif work_rest == "75-100":
        level = 2 if eff > cont - 1.0 else 1
    elif work_rest in ("50-75",):
        level = 2
    else:
        level = 3

    # 3b. Abu Dhabi ADOSH-SF Thermal Work Limit: the stricter of WBGT and TWL wins.
    tz = None
    if cond.use_twl and cond.temp_c is not None and cond.rh_pct is not None and caf < 10:
        tz = twl_zone(cond, worker)
        tlevel = twl_level(tz.zone, worker)
        reasons.extend(tz.reasons)
        if tlevel > level:
            reasons.append(f"ADOSH {tz.name} zone raises the level to {LEVELS[tlevel]}.")
            level = tlevel
            if level == 3 and work_rest in ("75-100", "50-75"):
                work_rest = "25-50"

    # 4. Cumulative heat budget: long continuous work raises the level.
    if level >= 2 and worker.minutes_worked >= 60:
        level = min(level + 1, 4)
        if work_rest is not None:  # one step more rest, so the schedule matches the level
            work_rest = REGIMES[min(REGIMES.index(work_rest) + 1, len(REGIMES) - 1)]
        reasons.append(f"Already worked {worker.minutes_worked} min in heat: level raised.")

    escalate = level == 4
    action = ACTIONS[level]
    if worker.needs_break and level < 4:
        action = "Break approved: rest in shade now. " + action
        reasons.append("Worker asked for a break.")

    a = Assessment(level, LEVELS[level], action, round(eff, 1), cont,
                   work_rest or "stop", reasons, escalate)
    if tz is not None:
        a.twl, a.twl_zone, a.oshad_zone, a.oshad_rules = tz.twl, tz.zone, tz.name, tz.rules
        if tz.zone == "withdrawal":
            a.schedule = "No ordinary work. Emergency work only, under permit: 20 min work, 40 min rest."
            a.hydration = "600 ml water every 30 min (1.2 L per hour); no more than 1.4 L per hour."
    return a


# ----------------------------------------------------------- ADOSH TWL link


def twl_zone(cond: Conditions, worker: Worker) -> "twl_mod.TwlResult":
    """TWL zone from site conditions. Globe from sensor, else estimated like the WBGT."""
    tw = wet_bulb_stull(cond.temp_c, cond.rh_pct)
    if cond.measured_globe_c is not None:
        tg, est = cond.measured_globe_c, False
    else:
        tg = cond.temp_c + (GLOBE_EXCESS_SUN * max(0.0, min(1.0, cond.solar)) if cond.sun else 0.0)
        est = True
    p = None if cond.pressure_hpa is None else cond.pressure_hpa / 10.0
    return twl_mod.assess_twl(cond.temp_c, tw, tg, cond.wind_ms, p, worker.clothing, estimated_inputs=est)


def twl_level(zone: str, worker: Worker) -> int:
    """ADOSH zone -> HeatWatch level. Unacclimatised workers may not work in Buffer."""
    unaccl = not worker.acclimatized or worker.stricter_limit
    if zone == "withdrawal":
        return 4
    if zone == "buffer":
        return 4 if unaccl else 3
    if zone == "acclimatisation":
        return 2 if unaccl else 1
    return 1
