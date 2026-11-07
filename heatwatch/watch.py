"""Simulated watch logic - Python mirror of static/watch.js (used for tests and docs).

In the product this runs ON the watch. Body data (heart rate, estimated core
temperature, age) never leaves the device; only the level, reason codes and an
escalate flag are sent on.

Core temperature from heart rate: Kalman filter of Buller et al. (2013),
Physiol. Meas. 34:781 (published parameters; also US patent 10,702,165).
Strain limits: ACGIH excessive-heat-strain criteria as given in the OSHA
Technical Manual (Sec. III, Ch. 4): sustained HR > 180 - age; core temperature
> 38.5 C (acclimatized, medically selected) or > 38.0 C (unacclimatized).
Prototype only: to be reviewed with clinical mentors before any use.
"""
from __future__ import annotations

import math

KF = dict(a=1.0, gamma=0.022, b0=-7887.1, b1=384.4286, b2=-4.5714, sigma=18.88, ct0=37.1, v0=0.0)
SUSTAINED_MIN = 5
NO_MOTION_ALONE_MIN = 5
FALL_NO_MOTION_MIN = 1
NEAR_C, RISING_C = 0.3, 0.7  # prototype warning bands below the ACGIH limit (to review)


def _js_round(x: float) -> int:
    """Math.round from JavaScript (halves go up), so both versions agree."""
    return math.floor(x + 0.5)


def ectemp_step(state: dict, hr: float) -> dict:
    xp = KF["a"] * state["ct"]
    vp = KF["a"] ** 2 * state["v"] + KF["gamma"] ** 2
    c = 2 * KF["b2"] * xp + KF["b1"]
    k = (vp * c) / (c * c * vp + KF["sigma"] ** 2)
    expected = KF["b2"] * xp * xp + KF["b1"] * xp + KF["b0"]
    return {"ct": xp + k * (hr - expected), "v": (1 - k * c) * vp}


def ectemp(hr_series, ct0: float = KF["ct0"]) -> list:
    s = {"ct": ct0, "v": KF["v0"]}
    out = []
    for hr in hr_series:
        s = ectemp_step(s, hr)
        out.append(_js_round(s["ct"] * 100) / 100)
    return out


def watch_minute(mem: dict, sample: dict, age: int, acclimatized: bool = True) -> dict:
    hr_limit = 180 - age
    ct_limit = 38.5 if acclimatized else 38.0
    mem["kf"] = ectemp_step(mem.get("kf") or {"ct": KF["ct0"], "v": KF["v0"]}, sample["hr"])
    mem["over_hr"] = mem.get("over_hr", 0) + 1 if sample["hr"] > hr_limit else 0
    mem["still"] = 0 if sample["moving"] else mem.get("still", 0) + 1
    if sample.get("fall"):
        mem["fell"] = True
    if sample["moving"]:
        mem["fell"] = False

    ct = mem["kf"]["ct"]
    level, reasons = 1, []
    if (mem.get("fell") and mem["still"] >= FALL_NO_MOTION_MIN) or mem["still"] >= NO_MOTION_ALONE_MIN:
        level = 4
        reasons.append("possible_man_down")
    if ct >= ct_limit:
        level = 4
        reasons.append("core_temp_over_limit")
    elif ct >= ct_limit - NEAR_C:
        level = max(level, 3)
        reasons.append("core_temp_near_limit")
    elif ct >= ct_limit - RISING_C:
        level = max(level, 2)
        reasons.append("core_temp_rising")
    if mem["over_hr"] >= SUSTAINED_MIN:
        level = 4
        reasons.append("sustained_heart_rate_over_limit")
    elif mem["over_hr"] >= 2:
        level = max(level, 2)
        reasons.append("heart_rate_over_limit")

    outbound = {"level": level, "reasons": reasons, "escalate": level == 4}
    local = {"hr": sample["hr"], "ct_est": _js_round(ct * 100) / 100, "hr_limit": hr_limit, "ct_limit": ct_limit}
    return {"outbound": outbound, "local": local}


def scenario(name: str) -> list:
    out = []
    for m in range(60):
        wobble = 3 * math.sin(m / 3)
        if name == "rising":
            out.append({"minute": m, "hr": _js_round(100 + m * 1.0 + wobble), "moving": True, "fall": False})
        elif name == "man_down":
            down = m >= 25
            out.append({"minute": m, "hr": _js_round((125 - (m - 25) * 0.8 if down else 108) + wobble),
                        "moving": not down, "fall": m == 25})
        else:
            out.append({"minute": m, "hr": _js_round(105 + wobble), "moving": True, "fall": False})
    return out


def run(name: str, age: int = 45, acclimatized: bool = True) -> list:
    mem: dict = {}
    return [{"minute": s["minute"], **watch_minute(mem, s, age, acclimatized)} for s in scenario(name)]
