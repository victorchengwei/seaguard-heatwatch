"""Supervisor readiness, worker languages, paid breaks, fasting."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from heatwatch import supervisor, wellbeing  # noqa: E402

c = TestClient(app)


def test_untrained_supervisor_never_alone():
    r = supervisor.route_alert("AMBER", ["heat_illness"])
    assert any("safety officer" in x for x in r["recipients"])


def test_trained_supervisor_routing():
    r = supervisor.route_alert("RED", supervisor.TRAINING_IDS)
    assert r["recipients"][0] == "supervisor"
    assert not any("safety officer" in x for x in r["recipients"])
    assert any("medic" in x for x in r["recipients"])


def test_green_needs_no_one():
    assert supervisor.route_alert("GREEN", [])["recipients"] == []


def test_training_covers_culture_language_pay():
    ids = set(supervisor.TRAINING_IDS)
    assert {"respect", "language", "culture", "pay_fear"} <= ids


def test_every_worker_language_has_every_level():
    for code, L in wellbeing.WORKER_LANGS.items():
        for lvl in ("GREEN", "AMBER", "RED", "DATA GAP"):
            name, text = L[lvl]
            assert name and text, (code, lvl)
        assert L["paid"]


def test_red_locked_in_every_language():
    for lang in wellbeing.ALL_LANGS:
        assert wellbeing.message("RED", "gentle", lang)["locked"]


def test_paid_break_on_amber_and_red_only():
    assert wellbeing.message("AMBER", lang="hi")["paid"]
    assert wellbeing.message("RED", lang="en")["paid"]
    assert wellbeing.message("GREEN", lang="en")["paid"] == ""


def test_urdu_is_right_to_left():
    assert wellbeing.message("AMBER", lang="ur")["rtl"]


def test_fasting_means_extra_caution():
    assert wellbeing.checkin(None, None, fasting=True)["extra_caution"]


def test_api_routing_when_untrained():
    w = c.get("/api/demo/worker/W06?minute=30&trained=heat_illness").json()
    assert any("safety officer" in x for x in w["routing"]["recipients"])
