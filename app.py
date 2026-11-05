"""SeaGuard HeatWatch prototype API + worker app (FastAPI).

Runs anywhere Python runs; target host is Azure App Service / Container Apps.
No secrets in code: the optional AI explainer reads its key from an
environment variable at deploy time.
"""
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from heatwatch.rules import Conditions, Worker, assess, CLOTHING, WORKLOADS
from heatwatch import demo
from heatwatch.explain import explain
from heatwatch import wellbeing, supervisor

app = FastAPI(title="SeaGuard HeatWatch", version="0.2.0")
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/options")
def options():
    return {"workloads": list(WORKLOADS), "clothing": list(CLOTHING)}


@app.post("/api/assess")
def api_assess(body: AssessIn):
    cond = Conditions(body.temp_c, body.rh_pct, body.sun, body.measured_wbgt, body.stale)
    worker = Worker(body.workload, body.clothing, body.acclimatized, body.stricter_limit,
                    body.minutes_worked, body.feels_unwell, body.needs_break)
    return asdict(assess(cond, worker))


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/demo")


# ------------------------------------------------------------ guided demo (SIMULATED)
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
    return json.loads((ROOT / "results" / "benchmark_summary.json").read_text(encoding="utf-8"))


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
