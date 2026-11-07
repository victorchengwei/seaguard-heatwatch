import pytest

from heatwatch.decisions import DecisionError, DecisionLog, ESCALATE_AFTER_MIN


def test_no_alert_below_high():
    log = DecisionLog()
    assert log.raise_alert("Crew A", 2, 0) is None and log.alerts == []


def test_plain_ok_is_refused():
    log = DecisionLog()
    a = log.raise_alert("Crew A", 3, 0)
    for bad in ("ok", "OK", "acknowledge", ""):
        with pytest.raises(DecisionError):
            log.decide(a.id, bad, 1)
    assert a.action is None


def test_stop_needs_a_stopping_action():
    log = DecisionLog()
    a = log.raise_alert("Crew B", 4, 0)
    with pytest.raises(DecisionError):
        log.decide(a.id, "move_task", 1)
    log.decide(a.id, "stop_work", 2)
    assert a.action == "stop_work" and a.response_min == 2


def test_decision_is_logged_and_final():
    log = DecisionLog()
    a = log.raise_alert("Crew A", 3, 5)
    log.decide(a.id, "rotate_crew", 9)
    assert a.acted_min == 9 and any("rotate" in h.lower() for h in a.history)
    with pytest.raises(DecisionError):
        log.decide(a.id, "rest_in_shade", 10)


def test_escalates_after_deadline_only_once():
    log = DecisionLog()
    a = log.raise_alert("Crew C", 3, 0)
    assert log.tick(ESCALATE_AFTER_MIN - 1) == []
    assert log.tick(ESCALATE_AFTER_MIN) == [a] and a.escalated
    assert log.tick(ESCALATE_AFTER_MIN + 5) == []


def test_one_open_alert_per_crew_and_level_rise():
    log = DecisionLog()
    a = log.raise_alert("Crew D", 3, 0)
    b = log.raise_alert("Crew D", 4, 3)
    assert a is b and a.level == 4 and a.deadline_min == ESCALATE_AFTER_MIN
    assert len(log.alerts) == 1


def test_adherence_numbers():
    log = DecisionLog()
    a = log.raise_alert("A", 3, 0)
    b = log.raise_alert("B", 4, 0)
    log.raise_alert("C", 3, 0)
    log.decide(a.id, "rest_in_shade", 4)
    log.tick(ESCALATE_AFTER_MIN)  # B and C escalate
    log.decide(b.id, "stop_work", 12)  # acted, but late
    r = log.adherence()
    assert r["alerts"] == 3 and r["acted"] == 2 and r["escalated"] == 2 and r["open"] == 1
    assert r["acted_pct"] == 66.7 and r["acted_on_time_pct"] == 33.3
    assert r["median_response_min"] == 8


def test_review_window_prevents_alarm_spam():
    from heatwatch.decisions import REVIEW_AFTER_MIN
    log = DecisionLog()
    a = log.raise_alert("A", 3, 0)
    log.decide(a.id, "rotate_crew", 2)
    assert log.raise_alert("A", 3, 10) is None          # decision still in force
    assert log.raise_alert("A", 4, 11) is not None      # worse level: new alert at once
    log2 = DecisionLog()
    b = log2.raise_alert("B", 3, 0)
    log2.decide(b.id, "rest_in_shade", 1)
    assert log2.raise_alert("B", 3, 1 + REVIEW_AFTER_MIN) is not None  # time to review
