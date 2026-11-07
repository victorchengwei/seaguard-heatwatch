"""Anti-rubber-stamp: supervisors must act on High / Stop alerts, not just click OK.

Automation bias is the weak spot of every human-in-the-loop system: a busy
supervisor sees a warning and confirms it without doing anything. Here:
1. At High or Stop the supervisor must choose a concrete action (no plain "OK").
2. Every choice is logged with the time and response time.
3. No decision within ESCALATE_AFTER_MIN minutes -> escalated to the site manager.
   After a decision the same crew is not re-alerted for REVIEW_AFTER_MIN minutes
   unless its level rises (no alarm spam), then the decision must be reviewed.
4. Adherence to controls (share acted on, response time, escalations) is reported,
   the measure the challenge brief asks for.

Times are minutes on a clock (a demo clock in the prototype). Crew-level only:
no personal or health data is stored.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Dict, List, Optional

ESCALATE_AFTER_MIN = 10
REVIEW_AFTER_MIN = 30  # after a decision, re-alert the same crew only after this, or if the level rises

ACTIONS = {
    "rest_in_shade": "Rest in shade now",
    "rotate_crew": "Rotate the crew",
    "move_task": "Move heavy work to a cooler time",
    "cool_down": "Active cooling (water, fans, cooling vests)",
    "stop_work": "Stop work",
    "call_medic": "Call the medic",
}
# Stop work needs a stopping action; High allows any real control.
ALLOWED = {
    3: ["rest_in_shade", "rotate_crew", "move_task", "cool_down", "stop_work"],
    4: ["stop_work", "cool_down", "call_medic"],
}


class DecisionError(ValueError):
    pass


@dataclass
class Alert:
    id: int
    crew: str
    level: int
    opened_min: int
    deadline_min: int
    action: Optional[str] = None
    acted_min: Optional[int] = None
    by: Optional[str] = None
    escalated: bool = False
    escalated_min: Optional[int] = None
    history: List[str] = field(default_factory=list)

    @property
    def response_min(self) -> Optional[int]:
        return None if self.acted_min is None else self.acted_min - self.opened_min

    def to_dict(self) -> dict:
        d = asdict(self)
        d["response_min"] = self.response_min
        d["allowed_actions"] = [{"id": a, "label": ACTIONS[a]} for a in ALLOWED[self.level]]
        d["action_label"] = ACTIONS.get(self.action) if self.action else None
        return d


class DecisionLog:
    def __init__(self) -> None:
        self.alerts: List[Alert] = []

    def _open_for(self, crew: str) -> Optional[Alert]:
        return next((a for a in self.alerts if a.crew == crew and a.action is None), None)

    def raise_alert(self, crew: str, level: int, now_min: int) -> Optional[Alert]:
        """Open an alert for a crew at High (3) or Stop (4). A crew has at most one open alert;
        if its level rises, the open alert is upgraded and keeps its original deadline."""
        if level < 3:
            return None
        open_alert = self._open_for(crew)
        if open_alert:
            if level > open_alert.level:
                open_alert.history.append(f"{now_min}: level raised {open_alert.level} -> {level}")
                open_alert.level = level
            return open_alert
        decided = [x for x in self.alerts if x.crew == crew and x.action is not None]
        if decided:
            last = max(decided, key=lambda x: x.acted_min)
            if now_min - last.acted_min < REVIEW_AFTER_MIN and level <= last.level:
                return None  # decision still in force: no alarm spam
        a = Alert(len(self.alerts) + 1, crew, level, now_min, now_min + ESCALATE_AFTER_MIN)
        a.history.append(f"{now_min}: opened at level {level}")
        self.alerts.append(a)
        return a

    def decide(self, alert_id: int, action: str, now_min: int, by: str = "supervisor") -> Alert:
        a = next((x for x in self.alerts if x.id == alert_id), None)
        if a is None:
            raise DecisionError("Unknown alert.")
        if a.action is not None:
            raise DecisionError("This alert already has a decision.")
        if action not in ACTIONS:
            raise DecisionError("Choose a concrete action; a plain OK is not accepted.")
        if action not in ALLOWED[a.level]:
            raise DecisionError(f"'{ACTIONS[action]}' is not enough at level {a.level}.")
        a.action, a.acted_min, a.by = action, now_min, by
        a.history.append(f"{now_min}: {by} chose '{ACTIONS[action]}'")
        return a

    def tick(self, now_min: int) -> List[Alert]:
        """Escalate every open alert past its deadline. Returns the newly escalated ones."""
        new = []
        for a in self.alerts:
            if a.action is None and not a.escalated and now_min >= a.deadline_min:
                a.escalated, a.escalated_min = True, now_min
                a.history.append(f"{now_min}: no decision in {ESCALATE_AFTER_MIN} min, escalated to site manager")
                new.append(a)
        return new

    def adherence(self) -> Dict:
        total = len(self.alerts)
        acted = [a for a in self.alerts if a.action is not None]
        on_time = [a for a in acted if not a.escalated]
        times = [a.response_min for a in acted]
        return {
            "alerts": total,
            "acted": len(acted),
            "acted_pct": round(100 * len(acted) / total, 1) if total else None,
            "acted_on_time_pct": round(100 * len(on_time) / total, 1) if total else None,
            "median_response_min": median(times) if times else None,
            "escalated": sum(a.escalated for a in self.alerts),
            "open": total - len(acted),
            "target_acted_pct": 80,
        }
