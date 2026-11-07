"""SeaGuard HeatWatch prototype API + worker app (FastAPI).

Runs anywhere Python runs; target host is Azure App Service / Container Apps.
No secrets in code: the optional AI explainer reads its key from an
environment variable at deploy time.
"""
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from heatwatch.rules import Conditions, Worker, assess, CLOTHING, WORKLOADS

app = FastAPI(title="SeaGuard HeatWatch", version="0.16.0")
STATIC = Path(__file__).parent / "static"


class AssessIn(BaseModel):
    temp_c: Optional[float] = None
    rh_pct: Optional[float] = None
    sun: bool = True
    measured_wbgt: Optional[float] = None
    stale: bool = False
    workload: str = "moderate"
    clothing: str = "work_clothes"
    acclimatized: bool = True
    stricter_limit: bool = False
    minutes_worked: int = 0
    feels_unwell: bool = False
    needs_break: bool = False
    wind_ms: Optional[float] = None
    pressure_hpa: Optional[float] = None
    measured_globe_c: Optional[float] = None
    use_twl: bool = True


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/options")
def options():
    return {"workloads": list(WORKLOADS), "clothing": list(CLOTHING)}


@app.post("/api/assess")
def api_assess(body: AssessIn):
    cond = Conditions(body.temp_c, body.rh_pct, body.sun, body.measured_wbgt, body.stale,
                      wind_ms=body.wind_ms, pressure_hpa=body.pressure_hpa,
                      measured_globe_c=body.measured_globe_c, use_twl=body.use_twl)
    worker = Worker(body.workload, body.clothing, body.acclimatized, body.stricter_limit,
                    body.minutes_worked, body.feels_unwell, body.needs_break)
    return asdict(assess(cond, worker))


@app.get("/i18n.js")
def i18n_js():
    return Response((STATIC / "i18n.js").read_text(encoding="utf-8"), media_type="text/javascript")


@app.get("/reminders.js")
def reminders_js():
    return Response((STATIC / "reminders.js").read_text(encoding="utf-8"), media_type="text/javascript")


@app.get("/watch.js")
def watch_js():
    """Watch logic. It runs in the browser (standing in for the watch), never on the server."""
    return Response((STATIC / "watch.js").read_text(encoding="utf-8"), media_type="text/javascript")


@app.get("/", response_class=HTMLResponse)
def worker_page():
    return (STATIC / "worker.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- supervisor
import math as _math
from heatwatch.planner import Crew, crew_status, plan_windows, solar_share


def demo_forecast(day: str = "2026-09-20", t_min: float = 27.0, t_max: float = 39.0,
                  rh_max: float = 70.0, rh_min: float = 30.0):
    """SYNTHETIC hot-season day (clearly labelled demo data, not a real forecast).
    Coolest ~05:00, hottest ~14:00; humidity moves opposite to temperature."""
    out = []
    for h in range(24):
        x = (_math.cos((h - 14) / 24 * 2 * _math.pi) + 1) / 2  # 1 at 14:00, 0 at 02:00
        out.append({"hour": f"{day}T{h:02d}:00",
                    "temp_c": round(t_min + (t_max - t_min) * x, 1),
                    "rh_pct": round(rh_max - (rh_max - rh_min) * x)})
    return out


DEMO_CREWS = [
    Crew("Crew A", "Main deck – cargo ops", "moderate", "work_clothes", True, 5, 0, 45),
    Crew("Crew B", "Engine room", "moderate", "woven_coveralls", False, 3, 1, 70),
    Crew("Crew C", "Quay – mooring", "heavy", "work_clothes", True, 4, 0, 20),
    Crew("Crew D", "Tank cleaning (chemical suit)", "moderate", "vapour_barrier_suit", False, 3, 0, 15),
]


def crews_at(hour: int):
    fc = demo_forecast()
    now = fc[max(0, min(23, hour))]
    # engine room: hotter than outside air, higher humidity (synthetic sensor)
    status = []
    for c in DEMO_CREWS:
        t, rh = now["temp_c"], now["rh_pct"]
        if c.location == "Engine room":
            t, rh = t + 6, min(rh + 10, 95)
        status.append(crew_status(c, t, rh, solar=solar_share(hour) if c.sun else 0.0))
    return fc, now, status


@app.get("/api/supervisor/demo")
def supervisor_demo(hour: int = 13):
    fc, now, status = crews_at(hour)
    return {"data_note": "Synthetic demo data – not a real forecast or real workers.",
            "now": now, "crews": status,
            "plans": [plan_windows(fc, "heavy"), plan_windows(fc, "moderate")]}


# ---------------------------------------------------------------- decisions (anti-rubber-stamp)
import time as _time
from fastapi import HTTPException
from heatwatch.decisions import DecisionError, DecisionLog

_LOGS: dict = {}  # demo session id -> (DecisionLog, last used); in production: a database
_MAX_SESSIONS = 500


def _log_for(session: str) -> DecisionLog:
    if not session or len(session) > 64:
        raise HTTPException(400, "Missing or invalid demo session id.")
    if session not in _LOGS and len(_LOGS) >= _MAX_SESSIONS:
        oldest = min(_LOGS, key=lambda k: _LOGS[k][1])
        del _LOGS[oldest]
    log = _LOGS.get(session, (DecisionLog(), 0))[0]
    _LOGS[session] = (log, _time.time())
    return log


def _state(log: DecisionLog, minute: int) -> dict:
    return {"minute": minute, "alerts": [a.to_dict() for a in log.alerts], "adherence": log.adherence()}


class SyncIn(BaseModel):
    session: str
    hour: int
    minute: int


class DecideIn(BaseModel):
    session: str
    alert_id: int
    action: str
    minute: int


@app.post("/api/supervisor/alerts/sync")
def alerts_sync(body: SyncIn):
    """Open alerts for crews at High or Stop, then escalate anything past its deadline."""
    log = _log_for(body.session)
    _, _, status = crews_at(body.hour)
    for c in status:
        log.raise_alert(c["crew"], c["level"], body.minute)
    log.tick(body.minute)
    return _state(log, body.minute)


@app.post("/api/supervisor/alerts/decide")
def alerts_decide(body: DecideIn):
    log = _log_for(body.session)
    try:
        log.decide(body.alert_id, body.action, body.minute)
    except DecisionError as e:
        raise HTTPException(400, str(e))
    return _state(log, body.minute)


@app.post("/api/supervisor/alerts/reset")
def alerts_reset(body: SyncIn):
    _LOGS.pop(body.session, None)
    return _state(_log_for(body.session), 0)


IMAGES = {"control_concept.jpg"}  # explicit list: nothing else under static/ is served by name


@app.get("/img/{name}")
def image(name: str):
    if name not in IMAGES:
        return Response(status_code=404)
    return Response((STATIC / "img" / name).read_bytes(), media_type="image/jpeg")


VENDOR = {"leaflet.js": "text/javascript", "leaflet.css": "text/css"}  # Leaflet 1.9.4, BSD-2-Clause


@app.get("/vendor/leaflet/{name}")
def vendor_leaflet(name: str):
    if name not in VENDOR:
        return Response(status_code=404)
    return Response((STATIC / "vendor" / "leaflet" / name).read_bytes(), media_type=VENDOR[name])


@app.get("/judges", response_class=HTMLResponse)
def judges_page():
    return (STATIC / "judges.html").read_text(encoding="utf-8")


@app.get("/control", response_class=HTMLResponse)
def control_page():
    return (STATIC / "control.html").read_text(encoding="utf-8")


@app.get("/supervisor", response_class=HTMLResponse)
def supervisor_page():
    return (STATIC / "supervisor.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- guided demo + benchmark (SIMULATED)
# Merged from the v0.1-v0.3 line: physiology (watch sensors), plain-language explainer,
# wellbeing check-in, supervisor readiness, privacy and the 52-case benchmark.
import json as _json
from fastapi import Query
from heatwatch import demo, wellbeing, supervisor
from heatwatch.explain import explain

ROOT = Path(__file__).parent


@app.get("/api/demo/crew")
def demo_crew():
    return {"crew": demo.crew(), "label": "SIMULATED"}


@app.get("/api/demo/board")
def demo_board(minute: int = Query(1, ge=1, le=600), caution: str = ""):
    """Supervisor board: colours only, no health numbers, no check-in answers."""
    return demo.state_at(minute, frozenset(w for w in caution.split(",") if w))


@app.get("/api/demo/worker/{worker}")
def demo_worker(worker: str, minute: int = Query(1, ge=1, le=600), lang: str = "en",
                fail_explainer: bool = False, technical: bool = False,
                mood: str = "", sleep: str = "", tone: str = "gentle", fasting: bool = False,
                trained: str = ",".join(supervisor.TRAINING_IDS)):
    ci = wellbeing.checkin(mood or None, sleep or None, lang, fasting)
    try:
        w = demo.worker_at(worker, minute, ci["extra_caution"])
    except StopIteration:
        raise HTTPException(404, "unknown worker")
    out = {k: w[k] for k in ("worker", "role", "role_ar", "story", "sector", "minute", "level",
                             "stages", "label")}
    out["explanation"] = explain(w["level"], w["reasons"], w["flags"], lang, fail=fail_explainer)
    out["routing"] = supervisor.route_alert(w["level"], [t for t in trained.split(",") if t])
    out["message"] = wellbeing.message(w["level"], tone, lang)   # RED is always firm and locked
    out["checkin"] = ci                                           # private: worker's own screen only
    if technical:  # judges' view: raw values, clearly SIMULATED
        out["technical"] = {k: w[k] for k in ("case", "reasons", "flags", "core_est", "ref_core", "hr", "wbgt")}
    return out


@app.get("/api/demo/trace/{worker}")
def demo_trace(worker: str):
    c = next((x for x in demo.CREW if x["worker"] == worker), None)
    if not c:
        raise HTTPException(404, "unknown worker")
    return {"worker": worker, "label": "SIMULATED",
            "points": [{k: p[k] for k in ("minute", "level", "core_est", "ref_core", "hr")}
                       for p in demo.timeline(c["case"])]}


@app.get("/api/benchmark")
def benchmark():
    return _json.loads((ROOT / "results" / "benchmark_summary.json").read_text(encoding="utf-8"))


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return (STATIC / "demo.html").read_text(encoding="utf-8")


@app.get("/worker", response_class=HTMLResponse)
def worker_tool():
    return (STATIC / "worker.html").read_text(encoding="utf-8")


@app.get("/api/wellbeing/plan")
def heat_plan(days_in_heat: int = Query(0, ge=0, le=60)):
    return {"plan": wellbeing.acclimatisation_plan(days_in_heat),
            "source": "NIOSH 2016 criteria document; to be confirmed by clinical mentors"}


@app.get("/api/principles")
def principles():
    return {"never_used_for": wellbeing.NOT_USED_FOR,
            "rules": ["Check-in is voluntary; skipping changes nothing.",
                      "Mood is private to the worker; supervisors never see it.",
                      "A check-in can only make limits stricter, never looser; RED never changes.",
                      "RED words are always firm and cannot be muted; other words follow the worker's tone choice.",
                      "No blame: missed days never reset progress."]}


@app.get("/api/supervisor/training")
def supervisor_training():
    return {"modules": supervisor.TRAINING,
            "rule": "Until training is complete, every alert is also copied to the site safety officer."}


@app.get("/api/languages")
def languages():
    return {"worker_languages": {"en": "English", "ar": "العربية",
                                 **{k: v["name"] for k, v in wellbeing.WORKER_LANGS.items()}},
            "note": "Hindi, Urdu, Bengali, Nepali and Tagalog texts are DRAFT translations; "
                    "native-speaker review required before field use."}
