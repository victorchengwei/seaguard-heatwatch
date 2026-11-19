"""Live multi-site command centre (v0.17).

Joins three inputs into one picture per crew, refreshed every few seconds:

1. LIVE weather for each site (Open-Meteo forecast API, no key): current
   conditions plus the next 12 hours. Cached for 10 minutes. If the feed
   fails, the last reading is used and marked stale (+2 C safety margin);
   with no reading at all, a labelled fallback day is used, also stale.
   A failure can only make a warning stricter, never softer.
2. On-site heat-stress stations (SIMULATED by default, real ones can post):
   air, humidity, black globe, natural wet bulb and WBGT every 15 seconds.
   The sensor and the weather model are both assessed; the stricter wins.
   A real station that goes silent for 2 minutes is ignored and the site is
   marked stale (+2 C), so a dead sensor can never lower a level.
3. Watches (SIMULATED): each watch sends only a level and a reason code.
   Heart rate, temperature estimate and age never leave the watch.
4. Worker check-ins (SIMULATED): "OK", "need a break", "feel unwell".

The same fixed rules as everywhere else (WBGT + ADOSH TWL, rules.py) give
the level now and for every forecast hour. The first forecast hour at High
or Stop becomes a proactive intervention, offered 30 minutes before the
limit is crossed. A person decides; nothing acts on its own.

Occupational safety alerts only: this is not a medical device and never
makes a diagnosis.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .planner import Crew, crew_status, plan_windows
from .rules import LEVELS, SCHEDULE, Conditions, Worker, assess, wet_bulb_stull

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
VARS = "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation"
CACHE_TTL_S = 600          # refresh weather at most every 10 minutes per site
STALE_AFTER_S = 3 * 3600   # older than this: treated as stale (+2 C margin)
FULL_SUN_W_M2 = 900.0      # shortwave radiation taken as full midday sun
LEAD_MIN = 30              # proactive intervention: act this long before the limit
HORIZON_H = 12
ROOT = Path(__file__).resolve().parent.parent
REPLAY_CSV = ROOT / "data" / "open_meteo_abu_dhabi_2025_may_sep.csv"

# ------------------------------------------------------------------ sites
# Crew and watch positions are synthetic. Sites are real places.


def _c(name, loc, workload, clothing, sun, size, new=0, worked=0):
    return Crew(name, loc, workload, clothing, sun, size, new, worked)


SITES = [
    {"id": "khalifa", "name": "Khalifa Port", "region": "Abu Dhabi, UAE", "kind": "Port",
     "lat": 24.8085, "lon": 54.6490, "utc_offset_h": 4,
     "crews": [
         {"crew": _c("Crew A", "Main deck · cargo ops", "moderate", "work_clothes", True, 5, 0, 45),
          "watches": ["W-03", "W-04"], "pos": [24.8095, 54.6440]},
         {"crew": _c("Crew C", "Quay · mooring", "heavy", "work_clothes", True, 4, 1, 20),
          "watches": ["W-05"], "pos": [24.8122, 54.6508]},
         {"crew": _c("Crew D", "Tank cleaning · chemical suit", "moderate", "vapour_barrier_suit", False, 3, 0, 15),
          "watches": ["W-11"], "pos": [24.8038, 54.6562]},
     ]},
    {"id": "offshore", "name": "Offshore platform", "region": "Arabian Gulf, off Das Island", "kind": "Offshore",
     "lat": 25.1520, "lon": 52.8730, "utc_offset_h": 4,
     "crews": [
         {"crew": _c("Crew E", "Open deck · lifting ops", "heavy", "woven_coveralls", True, 4, 0, 30),
          "watches": ["W-21", "W-22"], "pos": [25.1525, 52.8722]},
         {"crew": _c("Crew B", "Engine room", "moderate", "woven_coveralls", False, 3, 1, 70),
          "watches": ["W-07"], "pos": [25.1514, 52.8738], "indoor": {"add_c": 6.0, "add_rh": 10.0}},
     ]},
    {"id": "taichung", "name": "Taichung Port", "region": "Taiwan", "kind": "Port",
     "lat": 24.2890, "lon": 120.5050, "utc_offset_h": 8,
     "crews": [
         {"crew": _c("Crew F", "Container yard · lashing", "moderate", "work_clothes", True, 4, 0, 10),
          "watches": ["W-31"], "pos": [24.2905, 120.5010]},
         {"crew": _c("Crew G", "Offshore wind service vessel", "heavy", "woven_coveralls", True, 3, 1, 0),
          "watches": ["W-32"], "pos": [24.2840, 120.4920]},
     ]},
]

MODES = ("live", "heatwave", "replay")

# ------------------------------------------------------------------ weather


def _http_json(url: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SeaGuard-HeatWatch/0.17"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


FETCH: Callable[[str], dict] = _http_json   # tests replace this
_CACHE: dict = {}                            # site id -> (weather dict, fetched epoch)


def _url(site: dict) -> str:
    q = {"latitude": site["lat"], "longitude": site["lon"], "current": VARS, "hourly": VARS,
         "forecast_hours": HORIZON_H + 1, "timezone": "auto", "wind_speed_unit": "ms"}
    return OPEN_METEO + "?" + urllib.parse.urlencode(q)


def _parse(raw: dict) -> dict:
    cur, hr = raw["current"], raw["hourly"]
    hours = [{"time": t, "temp_c": hr["temperature_2m"][i], "rh_pct": hr["relative_humidity_2m"][i],
              "wind_ms": hr["wind_speed_10m"][i], "rad_w_m2": hr["shortwave_radiation"][i]}
             for i, t in enumerate(hr["time"])]
    # keep the current hour onwards, drop rows with gaps (never guess a missing value)
    hours = [h for h in hours if h["time"][:13] >= cur["time"][:13]
             and h["temp_c"] is not None and h["rh_pct"] is not None]
    return {"local_time": cur["time"], "tz": raw.get("timezone_abbreviation", ""),
            "current": {"temp_c": cur["temperature_2m"], "rh_pct": cur["relative_humidity_2m"],
                        "wind_ms": cur["wind_speed_10m"], "rad_w_m2": cur["shortwave_radiation"]},
            "hourly": hours}


def _fallback(site: dict, now_utc: datetime) -> dict:
    """Labelled fallback day when no live reading exists. Always marked stale."""
    local = now_utc + timedelta(hours=site["utc_offset_h"])
    t_min, t_max = (27.0, 37.0) if site["utc_offset_h"] == 4 else (20.0, 27.0)

    def at(dt):
        x = (math.cos((dt.hour - 14) / 24 * 2 * math.pi) + 1) / 2
        rad = max(0.0, math.sin(math.pi * (dt.hour - 6) / 12)) * 800
        return {"time": dt.strftime("%Y-%m-%dT%H:00"), "temp_c": round(t_min + (t_max - t_min) * x, 1),
                "rh_pct": round(75 - 40 * x), "wind_ms": 3.0, "rad_w_m2": round(rad)}

    hours = [at(local.replace(minute=0) + timedelta(hours=i)) for i in range(HORIZON_H + 1)]
    return {"local_time": local.strftime("%Y-%m-%dT%H:%M"), "tz": f"UTC+{site['utc_offset_h']}",
            "current": {k: hours[0][k] for k in ("temp_c", "rh_pct", "wind_ms", "rad_w_m2")},
            "hourly": hours}


def site_weather(site: dict, now: Optional[float] = None) -> dict:
    """Live weather with cache; never raises. Adds source and stale flags."""
    now = time.time() if now is None else now
    hit = _CACHE.get(site["id"])
    if hit and now - hit[1] < CACHE_TTL_S:
        return {**hit[0], "source": "live", "stale": False, "age_s": int(now - hit[1])}
    try:
        w = _parse(FETCH(_url(site)))
        _CACHE[site["id"]] = (w, now)
        return {**w, "source": "live", "stale": False, "age_s": 0}
    except Exception:  # network, timeout, bad JSON: fail safe, never fail silent
        if hit:
            age = int(now - hit[1])
            return {**hit[0], "source": "live (last reading)", "stale": True,
                    "age_s": age, "note": "Weather feed unavailable: last reading used with +2 C margin."}
        fb = _fallback(site, datetime.fromtimestamp(now, timezone.utc))
        return {**fb, "source": "fallback", "stale": True, "age_s": None,
                "note": "No live weather: labelled fallback day used with +2 C margin."}


# ------------------------------------------------------------------ replay (real hottest day, 2025)
_REPLAY: dict = {}


def replay_day() -> dict:
    """A real Abu Dhabi day from May-Sep 2025 (Open-Meteo history): workable at dawn, dangerous by noon."""
    if _REPLAY:
        return _REPLAY
    rows = []
    with open(REPLAY_CSV, encoding="utf-8") as f:
        r = csv.reader(f)
        for _ in range(4):
            next(r)
        for t, temp, rh, wind_kmh, rad in r:
            rows.append({"time": t, "temp_c": float(temp), "rh_pct": float(rh),
                         "wind_ms": round(float(wind_kmh) / 3.6, 1), "rad_w_m2": float(rad)})
    days: dict = {}
    for x in rows:
        days.setdefault(x["time"][:10], []).append(x)
    from .rules import wbgt_estimate

    def peak(day):
        return max(wbgt_estimate(h["temp_c"], h["rh_pct"], True, min(1.0, h["rad_w_m2"] / FULL_SUN_W_M2))
                   for h in day)
    def dawn(day):
        h = day[6]
        return wbgt_estimate(h["temp_c"], h["rh_pct"], True, min(1.0, h["rad_w_m2"] / FULL_SUN_W_M2))
    # The hottest day whose dawn is still workable, so the replay shows risk building through
    # the morning (the hottest day overall is already at Stop before sunrise).
    full = [d for d in days.values() if len(d) == 24]
    best = max([d for d in full if dawn(d) < 25.5] or full, key=peak)
    _REPLAY.update({"date": best[0]["time"][:10], "hours": best})
    return _REPLAY


def replay_weather(hour: float) -> dict:
    """Weather at replay clock `hour` (0-24) of the hottest day, plus the next 12 hours (wraps)."""
    day = replay_day()
    hrs = day["hours"]
    h0 = int(hour) % 24
    hours = [{**hrs[(h0 + i) % 24], "time": f"{day['date']}T{(h0 + i) % 24:02d}:00"} for i in range(HORIZON_H + 1)]
    m = int(round((hour - int(hour)) * 60)) % 60
    return {"local_time": f"{day['date']}T{h0:02d}:{m:02d}", "tz": "GST",
            "current": {k: hours[0][k] for k in ("temp_c", "rh_pct", "wind_ms", "rad_w_m2")},
            "hourly": hours, "source": f"replay · Abu Dhabi {day['date']} (real 2025 weather)",
            "stale": False, "age_s": None}


# ------------------------------------------------------------------ simulated watches + check-ins

WATCH_CODES = {"heart_rate_over_limit": "heart rate high", "core_temp_rising": "body heat rising",
               "core_temp_near_limit": "body heat near limit"}


def _rand(*parts) -> float:
    """Deterministic 0..1 from the inputs, so every viewer sees the same simulation."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def watch_reports(watches: list, weather_level: int, bucket: int) -> list:
    """SIMULATED watches: level and reason code only. Strain is likelier when it is hotter."""
    out = []
    for w in watches:
        p = {1: 0.04, 2: 0.15, 3: 0.35, 4: 0.5}[weather_level]
        r = _rand(w, bucket)
        if r < p:
            code = "core_temp_near_limit" if r < p / 3 else ("core_temp_rising" if r < 2 * p / 3 else "heart_rate_over_limit")
            level = min(4, max(weather_level, 2) + (1 if code == "core_temp_near_limit" else 0))
            out.append({"watch": w, "level": level, "reasons": [code]})
        else:
            out.append({"watch": w, "level": 1, "reasons": []})
    return out


def checkin(crew_name: str, weather_level: int, bucket: int) -> dict:
    """SIMULATED one-tap check-in from a crew member (no names, no health numbers)."""
    r = _rand("checkin", crew_name, bucket)
    if weather_level >= 3 and r < 0.12:
        return {"kind": "unwell", "text": "One member tapped “I feel unwell”"}
    if weather_level >= 2 and r < 0.35:
        return {"kind": "break", "text": "One member tapped “I need a break”"}
    return {"kind": "ok", "text": "Check-ins: all OK"}


# ------------------------------------------------------------------ on-site heat-stress sensors

SENSOR_PERIOD_S = 15     # one reading every 15 s (typical WBGT station logging interval)
SENSOR_TTL_S = 120       # a real station silent for longer is ignored and the site goes stale
SITE_OFFSET_C = {"khalifa": 0.8, "offshore": -0.3, "taichung": 0.5}  # quay concrete vs sea breeze
_EXT: dict = {}          # station id -> (reading dict, received epoch) from real stations
RANGES = {"temp_c": (-10.0, 60.0), "rh_pct": (0.0, 100.0), "globe_c": (-10.0, 90.0), "wbgt_c": (0.0, 45.0)}


def station_for(site: dict, crew_entry: dict) -> Optional[dict]:
    """Which station covers this crew: engine-room station, deck/quay station in the sun, or none."""
    if crew_entry.get("indoor"):
        return {"id": f"{site['id'].upper()}-ER", "name": "Engine-room WBGT station", "indoor": True}
    if crew_entry["crew"].sun:
        return {"id": f"{site['id'].upper()}-01", "name": "Deck/quay WBGT station (sun)", "indoor": False}
    return None  # shaded or enclosed work with no station: weather model only


def wbgt_from(ta: float, rh: float, tg: float, indoor: bool, solar: float) -> tuple:
    """Natural wet bulb (psychrometric + sun load) and WBGT (ISO 7243 / ACGIH formulas)."""
    tnwb = wet_bulb_stull(ta, rh) + (0.0 if indoor else 1.0 * solar)
    wbgt = 0.7 * tnwb + 0.3 * tg if indoor else 0.7 * tnwb + 0.2 * tg + 0.1 * ta
    return round(tnwb, 1), round(wbgt, 1)


def simulate_reading(site_id: str, station: dict, cur: dict, heat_delta: float, tick: int,
                     indoor: Optional[dict] = None) -> Optional[dict]:
    """SIMULATED station reading for 15-second tick `tick`: model weather + local effects + noise."""
    if cur.get("temp_c") is None or cur.get("rh_pct") is None:
        return None
    solar = 0.0 if station["indoor"] else max(0.0, min(1.0, (cur.get("rad_w_m2") or 0) / FULL_SUN_W_M2))
    wiggle = 0.4 * math.sin(2 * math.pi * tick / 40) + (_rand(station["id"], tick, "t") - 0.5) * 0.3
    ta = cur["temp_c"] + heat_delta + SITE_OFFSET_C.get(site_id, 0.0) + wiggle
    rh = cur["rh_pct"] + (_rand(station["id"], tick, "h") - 0.5) * 3
    if indoor:
        ta, rh = ta + indoor["add_c"], rh + indoor["add_rh"]
    rh = max(5.0, min(rh, 95.0))
    tg = ta + (3.0 if station["indoor"] else 12.0 * solar) + (_rand(station["id"], tick, "g") - 0.5) * 0.6
    tnwb, wbgt = wbgt_from(ta, rh, tg, station["indoor"], solar)
    return {"station": station["id"], "name": station["name"], "temp_c": round(ta, 1), "rh_pct": round(rh),
            "globe_c": round(tg, 1), "wet_bulb_c": tnwb, "wbgt_c": wbgt, "source": "simulated",
            "tick": tick, "age_s": 0}


def ingest_reading(station_id: str, body: dict, now: Optional[float] = None) -> dict:
    """Store a reading from a REAL station (POST /api/sensor). Values out of range are refused."""
    now = time.time() if now is None else now
    known = {f"{s['id'].upper()}-{suf}" for s in SITES for suf in ("01", "ER")}
    if station_id not in known:
        raise ValueError(f"unknown station {station_id}; known: {sorted(known)}")
    r = {}
    for k, (lo, hi) in RANGES.items():
        v = body.get(k)
        if v is None:
            continue
        v = float(v)
        if not lo <= v <= hi:
            raise ValueError(f"{k}={v} out of range {lo}..{hi}")
        r[k] = v
    if "temp_c" not in r or "rh_pct" not in r:
        raise ValueError("temp_c and rh_pct are required")
    indoor = station_id.endswith("-ER")
    r.setdefault("globe_c", None)
    r["wet_bulb_c"] = round(wet_bulb_stull(r["temp_c"], r["rh_pct"]), 1)
    if "wbgt_c" not in r:
        tg = r["globe_c"] if r["globe_c"] is not None else r["temp_c"]
        r["wet_bulb_c"], r["wbgt_c"] = wbgt_from(r["temp_c"], r["rh_pct"], tg, indoor, 0.0)
    r.update({"station": station_id, "source": "real station"})
    _EXT[station_id] = (r, now)
    return {"accepted": True, "station": station_id, "wbgt_c": r["wbgt_c"]}


def station_reading(site: dict, station: dict, cur: dict, heat_delta: float, tick: int, now: float,
                    indoor: Optional[dict], use_real: bool) -> tuple:
    """(reading or None, stale flag). A real station wins while fresh; silent = stale, model only."""
    if use_real and station["id"] in _EXT:
        r, t = _EXT[station["id"]]
        age = int(now - t)
        if age <= SENSOR_TTL_S:
            return {**r, "name": station["name"], "age_s": age}, False
        return None, True  # it was reporting and went silent: never trust the gap
    return simulate_reading(site["id"], station, cur, heat_delta, tick, indoor), False


# ------------------------------------------------------------------ assessment


def _conditions(h: dict, crew_entry: dict, stale: bool, heat_delta: float) -> dict:
    t, rh = h.get("temp_c"), h.get("rh_pct")
    if t is None or rh is None:  # missing reading: the rules engine applies its fail-safe level
        return {"temp_c": t, "rh_pct": rh, "stale": True, "solar": 1.0}
    t = t + heat_delta
    ind = crew_entry.get("indoor")
    if ind:
        t, rh = t + ind["add_c"], min(rh + ind["add_rh"], 95.0)
    solar = max(0.0, min(1.0, (h.get("rad_w_m2") or 0) / FULL_SUN_W_M2))
    return {"temp_c": t, "rh_pct": rh, "stale": stale, "solar": solar if crew_entry["crew"].sun else 0.0}


def forecast_levels(crew_entry: dict, hourly: list, stale: bool, heat_delta: float) -> list:
    crew = crew_entry["crew"]
    out = []
    for h in hourly:
        c = _conditions(h, crew_entry, stale, heat_delta)
        st = crew_status(crew, c["temp_c"], c["rh_pct"], stale=c["stale"], solar=c["solar"])
        out.append({"time": h["time"], "level": st["level"], "wbgt": st["effective_wbgt"],
                    "zone": st["oshad_zone"], "temp_c": None if c["temp_c"] is None else round(c["temp_c"], 1)})
    return out


def intervention(crew_entry: dict, now_level: int, fc: list, local_time: str,
                 hourly: list, stale: bool, heat_delta: float) -> Optional[dict]:
    """Proactive step for the first forecast hour at High or Stop (or now, if already there)."""
    crew = crew_entry["crew"]
    if now_level >= 3:
        text = (f"{crew.name} is at Stop work now: stop, move to shade, cool down; resume only when the level drops."
                if now_level == 4 else
                f"{crew.name} is at High now: apply the work-rest schedule and cooling now.")
        return {"when": "now", "level": now_level, "minutes_ahead": 0, "text": text}
    try:
        now_dt = datetime.fromisoformat(local_time)
    except ValueError:
        return None
    for f in fc[1:]:
        if f["level"] >= 3:
            at = datetime.fromisoformat(f["time"])
            act = at - timedelta(minutes=LEAD_MIN)
            mins = int((act - now_dt).total_seconds() // 60)
            sched = SCHEDULE["stop"] if f["level"] == 4 else "Work 30 min, rest 30 min each hour"
            # suggest the coolest safe window for this crew's work in the forecast
            pw = plan_windows([{"hour": h["time"], "temp_c": h["temp_c"] + heat_delta + (crew_entry.get("indoor") or {}).get("add_c", 0.0),
                                "rh_pct": h["rh_pct"]} for h in hourly if h.get("temp_c") is not None and h.get("rh_pct") is not None],
                              crew.workload, crew.clothing, crew.sun, min_hours=1)
            if pw["window"]:
                end = datetime.fromisoformat(pw["window"]["end"]) + timedelta(hours=1)
                pw["window"]["end"] = end.strftime("%Y-%m-%dT%H:%M")
            move = (f" Move {crew.workload} tasks to {pw['window']['start'][-5:]}–{pw['window']['end'][-5:]} (coolest safe window)."
                    if pw["window"] else " No safe window in the next 12 h: plan cooling and shorter shifts.")
            return {"when": act.strftime("%H:%M"), "level": f["level"], "minutes_ahead": max(0, mins),
                    "breach_at": at.strftime("%H:%M"),
                    "text": (f"Forecast: {crew.name} reaches {LEVELS[f['level']]} at {at:%H:%M}. "
                             f"Start “{sched}” from {act:%H:%M}, before the limit is crossed." + move)}
    return None


def snapshot(mode: str = "live", heat_delta: float = 0.0, replay_hour: float = 13.0,
             now: Optional[float] = None) -> dict:
    """The whole command-centre picture. Pure function of time, mode and the weather feed."""
    if mode not in MODES:
        mode = "live"
    heat_delta = max(0.0, min(10.0, float(heat_delta))) if mode == "heatwave" else 0.0
    now = time.time() if now is None else now
    bucket = int(now // 60)  # watch/check-in simulation changes once a minute, the same for every viewer
    tick = int(now // SENSOR_PERIOD_S) if mode != "replay" else int(replay_hour * 240)  # sensor tick: 15 s
    sites, events, counts = [], [], {1: 0, 2: 0, 3: 0, 4: 0}
    for s in SITES:
        w = replay_weather(replay_hour) if mode == "replay" else site_weather(s, now)
        hourly = w["hourly"][: HORIZON_H + 1] or [{"time": w["local_time"][:13] + ":00", **w["current"]}]
        crews_out, readings = [], {}
        for ce in s["crews"]:
            crew = ce["crew"]
            c = _conditions(w["current"], ce, w["stale"], heat_delta)
            model = crew_status(crew, c["temp_c"], c["rh_pct"], stale=c["stale"], solar=c["solar"])
            base, sensor_note, rd = model, None, None
            stn = station_for(s, ce)
            if stn:
                rd, silent = station_reading(s, stn, w["current"], heat_delta, tick, now, ce.get("indoor"),
                                             use_real=(mode == "live"))
                if silent:
                    c["stale"] = True
                    model = base = crew_status(crew, c["temp_c"], c["rh_pct"], stale=True, solar=c["solar"])
                    sensor_note = f"Station {stn['id']} silent for over 2 min: ignored, weather model used with +2 °C margin."
                elif rd:
                    sens = crew_status(crew, rd["temp_c"], rd["rh_pct"], stale=c["stale"], solar=c["solar"],
                                       measured_wbgt=rd["wbgt_c"], measured_globe_c=rd.get("globe_c"))
                    stricter = sens if (sens["level"], sens["effective_wbgt"] or 0) >= (model["level"], model["effective_wbgt"] or 0) else model
                    base = stricter
                    sensor_note = (f"Station {stn['id']} ({rd['source']}): measured WBGT {rd['wbgt_c']} °C, giving "
                                   f"{sens['label']}; weather model gives {model['label']}. The stricter is used "
                                   f"({'sensor' if stricter is sens else 'model'}).")
                    readings[stn["id"]] = rd
            else:
                sensor_note = "No sensor at this work spot: weather-model estimate only."
            ck = checkin(crew.name, base["level"], bucket // 5 if mode == "live" else int(replay_hour * 6))
            watches = watch_reports(ce["watches"], base["level"], bucket if mode == "live" else int(replay_hour * 6))
            st = base
            reasons = list(base["reasons"]) + ([sensor_note] if sensor_note else [])
            if ck["kind"] == "unwell":
                st = crew_status(replace(crew, unwell_reports=1), c["temp_c"], c["rh_pct"], stale=c["stale"], solar=c["solar"])
                reasons = list(st["reasons"]) + ([sensor_note] if sensor_note else [])
            level = st["level"]
            for wr in watches:
                if wr["level"] > level:
                    level = wr["level"]
                    reasons.append(f"Watch {wr['watch']}: {WATCH_CODES[wr['reasons'][0]]} (level only; raw data stays on the watch).")
            if ck["kind"] == "break":
                reasons.append("A member asked for a break: break approved automatically.")
            fc = forecast_levels(ce, hourly, w["stale"], heat_delta)
            fc[0]["level"] = max(fc[0]["level"], level)
            iv = intervention(ce, level, fc, w["local_time"], hourly, w["stale"], heat_delta)
            counts[level] += 1
            if ck["kind"] != "ok":
                events.append({"site": s["name"], "crew": crew.name, "kind": "checkin", "level": level, "text": ck["text"]})
            for wr in watches:
                if wr["reasons"]:
                    events.append({"site": s["name"], "crew": crew.name, "kind": "watch", "level": wr["level"],
                                   "text": f"Watch {wr['watch']}: {WATCH_CODES[wr['reasons'][0]]}"})
            schedule = SCHEDULE["stop"] if level == 4 else st["schedule"]
            crews_out.append({
                "crew": crew.name, "location": crew.location, "size": crew.size, "workload": crew.workload,
                "level": level, "label": LEVELS[level], "schedule": schedule,
                "action": st["action"] if level == st["level"] else
                          "Check the worker now: rest in shade, cool down, recheck in 10 min.",
                "wbgt": st["effective_wbgt"], "zone": st["oshad_zone"], "reasons": reasons,
                "watches": watches, "checkin": ck, "forecast": fc, "intervention": iv, "pos": ce["pos"],
                "station": stn["id"] if stn else None})
        sites.append({"id": s["id"], "name": s["name"], "region": s["region"], "kind": s["kind"],
                      "lat": s["lat"], "lon": s["lon"], "local_time": w["local_time"], "tz": w.get("tz", ""),
                      "weather": {**w["current"], "temp_c": (None if w["current"]["temp_c"] is None
                                                             else round(w["current"]["temp_c"] + heat_delta, 1))},
                      "source": w["source"], "stale": w["stale"], "note": w.get("note", ""),
                      "level": max(c["level"] for c in crews_out), "crews": crews_out,
                      "sensors": list(readings.values())})
    nexts = [(c["intervention"]["minutes_ahead"], s["name"], c) for s in sites for c in s["crews"]
             if c["intervention"] and c["intervention"]["when"] != "now"]
    soonest = min(nexts, key=lambda x: x[0]) if nexts else None
    return {
        "mode": mode, "heat_delta": heat_delta, "server_time_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "refresh_s": SENSOR_PERIOD_S if mode != "replay" else 5,
        "layers": [
            {"layer": "Smart watch", "rate": "every few seconds, on the watch", "sends": "level + reason code only", "status": "simulated"},
            {"layer": "On-site WBGT station", "rate": "every 15 s", "sends": "air, humidity, globe, wet bulb, WBGT",
             "status": "simulated (real stations can post to /api/sensor)"},
            {"layer": "Worker check-in", "rate": "any time, one tap", "sends": "OK / need a break / feel unwell", "status": "simulated"},
            {"layer": "Weather model", "rate": "refreshed every 10 min; hourly 12-h forecast", "sends": "air, humidity, wind, sunshine",
             "status": "live (Open-Meteo)" if mode == "live" else ("live + what-if" if mode == "heatwave" else "replay of real 2025 data")},
            {"layer": "Weather satellite", "rate": "10-min full disk, 30 s in rapid-scan areas", "sends": "cloud and sunshine over the site",
             "status": "roadmap (Himawari-9 for Taiwan, Meteosat for the Gulf)"},
        ],
        "counts": counts, "workers": sum(c["size"] for s in sites for c in s["crews"]),
        "next_breach": ({"site": soonest[1], "crew": soonest[2]["crew"], "at": soonest[2]["intervention"]["breach_at"],
                         "act_at": soonest[2]["intervention"]["when"], "minutes_ahead": soonest[0]} if soonest else None),
        "sites": sites, "events": events,
        "labels": {"weather": "Live weather: Open-Meteo forecast API (CC BY 4.0)." if mode == "live" else
                   ("What-if: live weather plus %.0f °C." % heat_delta if mode == "heatwave" else
                    "Replay: real Abu Dhabi weather of %s (safe at dawn, dangerous by noon), applied to every site." % replay_day()["date"]),
                   "workers": "Workers, watches, check-ins and on-site stations are SIMULATED. Positions are synthetic.",
                   "medical": "Occupational safety alert, not a medical diagnosis. Not a medical device.",
                   "privacy": "Heart rate, body-heat estimate and age stay on the watch; only a level and reason code are sent."},
    }
