"""Guided demo + explainer: privacy, visible failure, levels never changed by words."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from heatwatch import demo  # noqa: E402
from heatwatch.explain import explain  # noqa: E402

c = TestClient(app)


def test_board_has_colours_only():
    b = c.get("/api/demo/board?minute=15").json()
    assert b["label"] == "SIMULATED"
    for w in b["board"]:
        assert set(w) == {"worker", "level"}


def test_worker_view_hides_health_numbers_by_default():
    w = c.get("/api/demo/worker/W06?minute=20").json()
    assert "technical" not in w and "hr" not in w and "core_est" not in w
    assert w["level"] == "RED"


def test_offshore_no_network_goes_red():
    assert demo.worker_at("W06", 30)["level"] == "RED"


def test_spike_worker_never_alerts():
    assert all(p["level"] == "GREEN" for p in demo.timeline("T01"))


def test_off_wrist_never_green():
    assert all(p["level"] != "GREEN" for p in demo.timeline("T02"))


def test_explainer_failure_is_visible_and_keeps_action():
    ok = explain("RED", ["Estimated core 38.7 C"], [], "en")
    bad = explain("RED", ["Estimated core 38.7 C"], [], "en", fail=True)
    assert bad["status"] == "failed" and bad["notice"]
    assert bad["level"] == ok["level"] == "RED" and bad["action"] == ok["action"]


def test_arabic_available_for_every_level():
    for lvl in ("GREEN", "AMBER", "RED", "DATA GAP"):
        e = explain(lvl, [], [], "ar")
        assert e["action"] and e["does_not_mean"]


def test_red_has_escalation_ladder():
    steps = explain("RED", [], [], "en")["ladder"]
    assert steps[0]["min"] == 0 and any(s["min"] >= 2 for s in steps)


def test_plain_reasons_have_no_numbers():
    e = explain("RED", ["WBGT in danger zone and HR 150 > 142: RED"], [], "en")
    assert e["why"] and not any(ch.isdigit() for line in e["why"] for ch in line)


def test_demo_page_served():
    assert "SIMULATED" in c.get("/demo").text
