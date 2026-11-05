import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app

c = TestClient(app)


def test_health():
    assert c.get("/health").json() == {"status": "ok"}


def test_assess_returns_level_and_reasons():
    r = c.post("/api/assess", json={"temp_c": 36, "rh_pct": 55, "workload": "heavy"}).json()
    assert r["level"] == 4 and r["reasons"]


def test_unwell_via_api():
    r = c.post("/api/assess", json={"temp_c": 20, "rh_pct": 40, "feels_unwell": True}).json()
    assert r["level"] == 4 and r["escalate"]


def test_worker_page_served():
    assert "HeatWatch" in c.get("/worker").text
    assert "HeatWatch" in c.get("/").text  # redirects to the guided demo
