"""Daily check-in, tone and respect rules."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from heatwatch import demo, wellbeing  # noqa: E402

c = TestClient(app)


def test_skip_changes_nothing():
    r = wellbeing.checkin(None, None)
    assert r["skipped"] and not r["extra_caution"]


def test_hard_day_only_makes_limits_stricter():
    from heatwatch.physiology import RANK
    for cid in ("B11", "B02", "T24", "T10", "T02"):
        plain = demo.timeline(cid, False)
        care = demo.timeline(cid, True)
        assert all(RANK[b["level"]] >= RANK[a["level"]] for a, b in zip(plain, care))


def test_checkin_never_creates_or_removes_red():
    for c_ in demo.CREW:
        plain = [p["level"] == "RED" for p in demo.timeline(c_["case"], False)]
        care = [p["level"] == "RED" for p in demo.timeline(c_["case"], True)]
        assert plain == care


def test_tired_welder_gets_earlier_break():
    assert demo.worker_at("W07", 30)["level"] == "GREEN"
    assert demo.worker_at("W07", 30, extra=True)["level"] == "AMBER"


def test_red_words_locked_firm():
    for tone in ("gentle", "direct", "anything"):
        m = wellbeing.message("RED", tone)
        assert m["locked"] and m["tone"] == "firm"


def test_tone_choice_for_everyday_messages():
    assert wellbeing.message("AMBER", "gentle")["text"] != wellbeing.message("AMBER", "direct")["text"]


def test_supervisor_board_never_shows_mood():
    b = c.get("/api/demo/board?minute=30&caution=W07").json()
    assert all(set(x) == {"worker", "level"} for x in b["board"])
    assert "mood" not in str(b["board"])


def test_reengage_no_blame_no_reset():
    t = wellbeing.reengage(5, 12)
    assert "12" in t and "still count" in t


def test_low_mood_streak_offers_support():
    assert wellbeing.low_mood_streak(["ok", "stressed", "stressed", "stressed"])
    assert not wellbeing.low_mood_streak(["stressed", "ok", "stressed"])


def test_acclimatisation_plan_steps_20pct():
    plan = wellbeing.acclimatisation_plan(2)
    assert [d["max_heat_exposure_pct"] for d in plan][:5] == [20, 40, 60, 80, 100]


def test_checkin_rate_suppressed_for_small_groups():
    assert "suppressed" in str(wellbeing.checkin_rate(2, 3))


def test_api_worker_checkin_private_reply():
    w = c.get("/api/demo/worker/W07?minute=30&mood=tired").json()
    assert w["level"] == "AMBER" and w["checkin"]["private"]
