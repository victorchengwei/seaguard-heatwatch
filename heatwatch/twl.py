"""Thermal Work Limit (TWL) and the Abu Dhabi ADOSH-SF heat zones.

TWL (W/m2) is the highest metabolic rate a well-hydrated, acclimatised,
self-paced worker can keep up without the core temperature passing 38.2 C
(Brake & Bates 2002). The lower the TWL, the harsher the conditions.
Abu Dhabi uses it in ADOSH-SF (formerly OSHAD-SF) CoP 11.0 "Safety in the Heat" (v4.0, July 2024)
and its Technical Guideline.

ESTIMATE, NOT THE OFFICIAL CALCULATOR. Brake & Bates did not publish their full
algorithm in the sources we can access, so this module is a transparent
heat-balance model built on the same principles:
  * core temperature held at 38.2 C, maximal skin blood flow (two-node model);
  * dry heat exchange (convection + radiation) and evaporation through clothing
    (ISO 9920 / ASHRAE coefficients, Lewis relation 16.5 K/kPa);
  * sweat capped at about 1.2 L per hour (0.67 kg/m2/h);
  * TWL = the heat flow at which core-to-skin transfer equals skin-to-air loss.
Results are checked against published reference points in tests/test_twl.py
and must be validated against the official ADOSH online TWL calculator
before any real use. Valid range 60-380 W/m2 (outside it we report the edge).

Zones (ADOSH-SF Technical Guideline Table 1, as reported by HAAD/The National
2011, Miller & Bates 2007 Table 6 and Wikipedia; the official table is an
image, VERIFY the wording against v4.0):
  > 220   Unrestricted
  140-220 Acclimatisation
  115-140 Buffer
  < 115   Withdrawal (also if dry bulb > 44 C or wet bulb > 32 C)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

CORE_LIMIT_C = 38.2
SWEAT_MAX_KG_M2_H = 0.67  # about 1.2 L/h for an average 1.8 m2 worker
LATENT_J_KG = 2.43e6
LEWIS = 16.5  # K/kPa
K_MAX = 5.28 + 1.163 * 90.0  # W/m2/K, tissue conductance at maximal skin blood flow
TWL_MIN, TWL_MAX = 60.0, 380.0

# Clothing: (insulation in clo, Woodcock moisture permeability index im).
# None = TWL not valid (impermeable clothing): use WBGT only.
TWL_CLOTHING = {
    "work_clothes": (0.6, 0.45),
    "woven_coveralls": (0.7, 0.45),
    "double_layer_coveralls": (1.2, 0.40),
    "sms_polypropylene_coveralls": (0.8, 0.38),
    "polyolefin_coveralls": (0.8, 0.30),
    "vapour_barrier_suit": None,
}

# Zone limits (W/m2) and extra withdrawal triggers.
UNRESTRICTED = 220.0
ACCLIMATISATION = 140.0
BUFFER = 115.0
WITHDRAW_DRY_BULB_C = 44.0
WITHDRAW_WET_BULB_C = 32.0

ZONES = {
    "unrestricted": {
        "name": "Unrestricted",
        "zh": "不限制區",
        "rules": [
            "Self-paced work, no limits for trained, hydrated workers.",
            "Drink at least 2 L every 2-3 hours, even when not thirsty.",
        ],
    },
    "acclimatisation": {
        "name": "Acclimatisation",
        "zh": "適應區",
        "rules": [
            "Workers not acclimatised (new, back from leave) must not work alone.",
            "Self-paced work; drink at least 2 L every 2-3 hours.",
        ],
    },
    "buffer": {
        "name": "Buffer",
        "zh": "緩衝區",
        "rules": [
            "Reduce heat now: shade, ventilation, move or reschedule work.",
            "No working alone. Unacclimatised workers must not work.",
            "Scheduled rest breaks in a cooled rest area; drink regularly.",
        ],
    },
    "withdrawal": {
        "name": "Withdrawal",
        "zh": "撤離區",
        "rules": [
            "No ordinary work. Only emergency, rescue or essential maintenance under a permit to work.",
            "If work must go on: 20 min work, 40 min rest; 600 ml water every 30 min (1.2 L per hour).",
            "No working alone; no unacclimatised workers; dehydration test at end of shift.",
        ],
    },
}


# ------------------------------------------------------------------ physics


def psat_kpa(t_c: float) -> float:
    """Saturation vapour pressure (kPa), Magnus form."""
    return 0.6105 * math.exp(17.27 * t_c / (237.7 + t_c))


def vapour_pressure_from_wet_bulb(ta: float, tw: float, p_kpa: float = 101.325) -> float:
    """Actual vapour pressure (kPa) from dry and (psychrometric) wet bulb."""
    return max(0.0, psat_kpa(tw) - 6.6e-4 * p_kpa * (ta - tw))


def mean_radiant_temp(ta: float, tg: float, v: float) -> float:
    """Mean radiant temperature from a 150 mm black globe (ISO 7726, forced convection)."""
    v = max(v, 0.1)
    x = (tg + 273.15) ** 4 + 2.5e8 * v ** 0.6 * (tg - ta)
    return max(x, 0.0) ** 0.25 - 273.15


def _skin_loss(tsk: float, ta: float, tr: float, pa: float, v: float, clo: float, im: float) -> float:
    """Heat lost from skin (W/m2) at skin temperature tsk: dry + evaporative."""
    icl = 0.155 * clo
    fcl = 1.0 + 0.31 * clo
    hc = max(3.1, 8.3 * max(v, 0.1) ** 0.6)
    tmean = (tsk + tr) / 2.0 + 273.15
    hr = 4.0 * 0.95 * 5.67e-8 * 0.72 * tmean ** 3
    to = (hr * tr + hc * ta) / (hr + hc)
    dry = (tsk - to) / (icl + 1.0 / (fcl * (hc + hr)))
    re_cl = icl / (im * LEWIS)
    he = LEWIS * hc
    e_max = (psat_kpa(tsk) - pa) / (re_cl + 1.0 / (fcl * he))
    e_sweat = SWEAT_MAX_KG_M2_H * LATENT_J_KG / 3600.0
    return dry + min(e_max, e_sweat)


def twl(ta: float, tw: float, tg: Optional[float] = None, v: float = 1.0,
        p_kpa: float = 101.325, clothing: str = "work_clothes") -> Optional[float]:
    """Estimated TWL (W/m2). ta dry bulb, tw wet bulb, tg globe (C), v wind (m/s).

    Returns None when TWL is not valid for the clothing (impermeable suits).
    """
    spec = TWL_CLOTHING.get(clothing)
    if spec is None:
        return None
    clo, im = spec
    tg = ta if tg is None else tg
    pa = vapour_pressure_from_wet_bulb(ta, tw, p_kpa)
    tr = mean_radiant_temp(ta, tg, v)

    def gap(tsk: float) -> float:  # core-to-skin supply minus skin-to-air loss
        return K_MAX * (CORE_LIMIT_C - tsk) - _skin_loss(tsk, ta, tr, pa, v, clo, im)

    lo, hi = 20.0, CORE_LIMIT_C
    if gap(lo) < 0:  # environment removes heat faster than the body can supply: very cool
        return TWL_MAX
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if gap(mid) > 0:
            lo = mid
        else:
            hi = mid
    tsk = (lo + hi) / 2.0
    skin = K_MAX * (CORE_LIMIT_C - tsk)
    # Breathing also removes heat, proportional to metabolic rate (ASHRAE).
    resp_share = 0.0014 * (34.0 - ta) + 0.0173 * (5.87 - pa)
    m = skin / max(0.5, 1.0 - resp_share)
    # Below TWL_MIN (resting) the value is outside the validated range, but it is
    # still reported: it always falls in the Withdrawal zone.
    return round(max(0.0, min(TWL_MAX, m)), 1)


# -------------------------------------------------------------------- zones


@dataclass
class TwlResult:
    twl: Optional[float]
    zone: str  # key of ZONES, or "not_valid"
    name: str
    zh: str
    rules: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    estimated_inputs: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def zone_for(value: float, ta: float, tw: float) -> str:
    if value < BUFFER or ta > WITHDRAW_DRY_BULB_C or tw > WITHDRAW_WET_BULB_C:
        return "withdrawal"
    if value < ACCLIMATISATION:
        return "buffer"
    if value <= UNRESTRICTED:
        return "acclimatisation"
    return "unrestricted"


def assess_twl(ta: float, tw: float, tg: Optional[float] = None, v: Optional[float] = None,
               p_kpa: Optional[float] = None, clothing: str = "work_clothes",
               estimated_inputs: bool = False) -> TwlResult:
    """TWL and ADOSH zone, with plain-language reasons. Missing wind is taken as
    calm (0.5 m/s) and missing pressure as sea level: both fail-safe."""
    reasons = []
    if v is None:
        v = 0.5
        reasons.append("Wind unknown: assumed calm (0.5 m/s), the safer choice.")
    if p_kpa is None:
        p_kpa = 101.325
    value = twl(ta, tw, tg, v, p_kpa, clothing)
    if value is None:
        return TwlResult(None, "not_valid", "Not valid", "不適用", [
            "TWL is not valid for impermeable suits: use WBGT and medical supervision.",
        ], ["Impermeable clothing."], estimated_inputs)
    z = zone_for(value, ta, tw)
    reasons.insert(0, f"TWL {value:.0f} W/m2 (dry bulb {ta:.0f} C, wet bulb {tw:.0f} C, "
                      f"globe {(ta if tg is None else tg):.0f} C, wind {v:.1f} m/s).")
    if z == "withdrawal" and value >= BUFFER:
        reasons.append("Dry bulb above 44 C or wet bulb above 32 C: withdrawal regardless of TWL.")
    if estimated_inputs:
        reasons.append("Globe and wet bulb estimated from forecast, not measured.")
    zz = ZONES[z]
    return TwlResult(value, z, zz["name"], zz["zh"], list(zz["rules"]), reasons, estimated_inputs)
