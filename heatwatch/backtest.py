"""Back-test HeatWatch rules on real historical weather (Open-Meteo, CC BY 4.0).

Honest scope: this tests the RULES on real weather, not a field trial.
- Sun strength comes from measured shortwave radiation (not time of day).
- "Forecast" errors are SIMULATED by adding random noise to the real values,
  so false-alarm and miss rates describe forecast uncertainty, not real outcomes.
Weather data by Open-Meteo.com.
"""
from __future__ import annotations

import random
from collections import Counter

import pandas as pd

from .rules import Conditions, Worker, assess

FULL_SUN_WM2 = 900.0  # radiation treated as full midday sun


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=3)
    df.columns = ["time", "temp_c", "rh_pct", "wind_kmh", "sw_wm2"]
    df["time"] = pd.to_datetime(df["time"])
    return df


def level_for(temp_c, rh_pct, sw, workload, sun=True):
    solar = max(0.0, min(1.0, sw / FULL_SUN_WM2))
    a = assess(Conditions(temp_c=temp_c, rh_pct=rh_pct, sun=sun, solar=solar, use_twl=False), Worker(workload))
    return a.level


def in_midday_ban(ts: pd.Timestamp) -> bool:
    """UAE midday break: 12:30-15:00, 15 June - 15 September (MoHRE)."""
    md = (ts.month, ts.day)
    in_season = (6, 15) <= md <= (9, 15)
    minutes = ts.hour * 60 + ts.minute
    # hourly data: an hour counts if it starts inside 12:30-15:00 window -> 13:00, 14:00
    return in_season and 12 * 60 + 30 <= minutes < 15 * 60


FORECAST_SAFETY_MARGIN_C = 2.0  # forecasts are read 2 C hotter: fewer missed dangerous hours


def run(path: str, workload: str = "heavy", t_sigma: float = 1.5, rh_sigma: float = 8.0,
        seed: int = 42, margin_c: float = FORECAST_SAFETY_MARGIN_C) -> dict:
    df = load(path)
    rng = random.Random(seed)
    df["level"] = [level_for(r.temp_c, r.rh_pct, r.sw_wm2, workload) for r in df.itertuples()]
    df["fc_level"] = [level_for(r.temp_c + rng.gauss(0, t_sigma) + margin_c,
                                max(1.0, min(100.0, r.rh_pct + rng.gauss(0, rh_sigma))),
                                r.sw_wm2, workload) for r in df.itertuples()]
    df["ban"] = df["time"].map(in_midday_ban)

    work = df[(df.time.dt.hour >= 6) & (df.time.dt.hour < 19)]  # daytime shift hours
    levels = Counter(work["level"])
    high = work[work.level >= 3]

    # Lead time: per day, hours between first Caution (>=2) and first High (>=3)
    leads = []
    for _, d in work.groupby(work.time.dt.date):
        c = d[d.level >= 2]
        h = d[d.level >= 3]
        if len(h) and len(c):
            leads.append((h.time.iloc[0] - c.time.iloc[0]).total_seconds() / 3600)
    leads_s = pd.Series(leads) if leads else pd.Series([0.0])

    # Forecast-vs-actual for High-or-worse (simulated forecast error)
    fa = ((work.fc_level >= 3) & (work.level < 3)).sum()
    alerts = (work.fc_level >= 3).sum()
    miss = ((work.fc_level < 3) & (work.level >= 3)).sum()
    actual_high = (work.level >= 3).sum()

    # Where the dangerous hours are, compared with the midday ban
    md = list(zip(high.time.dt.month, high.time.dt.day))
    in_season = pd.Series([(6, 15) <= x <= (9, 15) for x in md], index=high.index)
    gap = {"inside_ban_pct": round(float(100 * high.ban.mean()), 1) if len(high) else 0.0,
           "same_season_outside_window_pct": round(float(100 * (in_season & ~high.ban).mean()), 1) if len(high) else 0.0,
           "outside_ban_season_pct": round(float(100 * (~in_season).mean()), 1) if len(high) else 0.0}

    # PREVENT: dangerous shift hours that could move to safer hours the same day
    # (extra early/late hours 04:00-06:00 and 19:00-22:00 with level <= 2)
    movable = 0
    safe_by_month = {}
    for d, g in df.groupby(df.time.dt.date):
        shift = g[(g.time.dt.hour >= 6) & (g.time.dt.hour < 19)]
        extra = g[((g.time.dt.hour >= 4) & (g.time.dt.hour < 6)) | ((g.time.dt.hour >= 19) & (g.time.dt.hour < 22))]
        movable += min(int((shift.level >= 3).sum()), int((extra.level <= 2).sum()))
        ext = g[(g.time.dt.hour >= 4) & (g.time.dt.hour < 22)]
        safe_by_month.setdefault(d.month, []).append(int((ext.level <= 2).sum()))

    by_month = (work.assign(high=work.level >= 3)
                .groupby(work.time.dt.month)["high"].mean().mul(100).round(0).to_dict())

    return {
        "workload": workload,
        "daytime_hours": int(len(work)),
        "levels": {k: int(v) for k, v in sorted(levels.items())},
        "high_or_stop_share_pct": round(100 * len(high) / len(work), 1),
        "high_hours_outside_midday_ban_pct": round(100 * (~high.ban).mean(), 1) if len(high) else 0.0,
        "days_with_high": int(sum(1 for _, d in work.groupby(work.time.dt.date) if (d.level >= 3).any())),
        "days_total": int(work.time.dt.date.nunique()),
        "lead_time_h_median": float(leads_s.median()),
        "lead_time_h_p25": float(leads_s.quantile(0.25)),
        "days_with_lead_measured": len(leads),
        "sim_false_alarm_rate_pct": round(100 * fa / alerts, 1) if alerts else 0.0,
        "sim_miss_rate_pct": round(100 * miss / actual_high, 1) if actual_high else 0.0,
        "high_share_by_month_pct": {int(k): v for k, v in by_month.items()},
        "high_hours_vs_midday_ban": gap,
        "movable_high_hours_pct": round(100 * movable / len(high), 1) if len(high) else 0.0,
        "mean_safe_hours_04_22_by_month": {int(k): round(sum(v) / len(v), 1) for k, v in safe_by_month.items()},
        "assumptions": {"forecast_safety_margin_c": margin_c, "forecast_error_temp_sd_c": t_sigma, "forecast_error_rh_sd_pct": rh_sigma,
                        "shift_hours": "06:00-19:00", "exposure": "outdoors, direct sun"},
    }


def cooling_what_if(path: str, workload: str = "moderate", offsets=(0.0, 1.0, 1.5, 2.0)) -> dict:
    """WHAT-IF, not a measured result: if cooling PPE lowered the heat a worker feels
    by an amount equal to `offset` C of WBGT, how many daytime High/Stop hours remain?
    The real effect of a garment must be measured in the pilot."""
    df = load(path)
    work = df[(df.time.dt.hour >= 6) & (df.time.dt.hour < 19)]
    from .rules import wbgt_estimate
    base_wbgt = [wbgt_estimate(r.temp_c, r.rh_pct, True, max(0.0, min(1.0, r.sw_wm2 / FULL_SUN_WM2)))
                 for r in work.itertuples()]
    out, base = {}, None
    for off in offsets:
        n = sum(assess(Conditions(measured_wbgt=w - off), Worker(workload)).level >= 3 for w in base_wbgt)
        base = n if base is None else base
        out[f"{off:g}"] = {"high_or_stop_hours": int(n),
                           "reduction_pct": round(100 * (base - n) / base, 1) if base else 0.0}
    return {"workload": workload, "assumption": "cooling effect expressed as C of WBGT; scenario only",
            "results": out}


WIND_10M_TO_2M = 0.65  # log wind profile, open terrain (z0 = 0.1 m): ln(2/0.1)/ln(10/0.1)


def twl_zone_hours(path: str, clothing: str = "work_clothes") -> dict:
    """Share of hours in each ADOSH TWL zone, all hours and daytime (06-18), in sun.
    Globe and wet bulb are estimated from the forecast, so this is indicative only."""
    from .rules import GLOBE_EXCESS_SUN, wet_bulb_stull
    from .twl import assess_twl

    df = load(path)
    zones = []
    for r in df.itertuples():
        solar = max(0.0, min(1.0, r.sw_wm2 / FULL_SUN_WM2))
        tw = wet_bulb_stull(r.temp_c, r.rh_pct)
        v = max(0.5, r.wind_kmh / 3.6 * WIND_10M_TO_2M)
        res = assess_twl(r.temp_c, tw, r.temp_c + GLOBE_EXCESS_SUN * solar, v, None, clothing, True)
        zones.append(res.zone)
    df["zone"] = zones
    day = df[(df.time.dt.hour >= 6) & (df.time.dt.hour < 18)]
    order = ["unrestricted", "acclimatisation", "buffer", "withdrawal"]
    pct = lambda d: {z: round(float(100 * (d.zone == z).mean()), 1) for z in order}
    by_month = {int(m): pct(g) for m, g in day.groupby(day.time.dt.month)}
    return {"hours": len(df), "all_hours_pct": pct(df), "daytime_06_18_pct": pct(day),
            "daytime_by_month_pct": by_month, "clothing": clothing,
            "note": "Estimated globe (+12 C x sun share) and 2 m wind (10 m x 0.65, min 0.5 m/s)."}
