"""Python mirror of static/reminders.js (watch reminders). See that file for the rules
and sources. Kept identical so the logic can be tested and reviewed in one language."""
from __future__ import annotations

from typing import Dict, List, Optional

WORK_MIN = {"75-100": 60, "50-75": 45, "25-50": 30, "0-25": 15}
STRICTER = {"75-100": "50-75", "50-75": "25-50", "25-50": "0-25", "0-25": "0-25"}
MAX_CUPS_PER_HOUR = 5
MIN_GAP = 5
URGENT = ("rest_now", "back_to_work", "cool_down")
TEXT = {
    "drink": "Drink 1 cup of water (250 ml)",
    "rest_soon": "Rest in 5 minutes",
    "rest_now": "Rest now: shade or cooled rest area",
    "back_to_work": "Rest over: back to work at your own pace",
    "meal_soon": "Meal break in 5 minutes",
    "meal_now": "Meal: eat, drink water, a little extra salt",
    "fast_cool": "Fasting: rest in shade, cool your skin with water",
    "cool_down": "Stop work: cool down, tell your supervisor",
}
ACCLIM = {"experienced": [50, 60, 80, 100, 100], "new": [20, 40, 60, 80, 100]}


def acclim_pct(day: int, is_new: bool) -> int:
    t = ACCLIM["new"] if is_new else ACCLIM["experienced"]
    if day < 1:
        return t[0]
    return 100 if day > 5 else t[day - 1]


def regime_for(level: int, regime: str, fasting: bool) -> str:
    if level >= 4:
        return "stop"
    return STRICTER[regime] if fasting else regime


def remind_minute(mem: Dict, ctx: Dict) -> Dict:
    if not mem.get("init"):
        mem.update(init=True, lastDrink=0, cups=[], lastBuzz=-1000, lastFast=0, lastCool=-1000, pending=[])
    m, lv, due = ctx["minute"], ctx["level"], []
    reg = regime_for(lv, ctx["regime"], ctx.get("fasting", False))

    if lv >= 4:
        if m - mem["lastCool"] >= 10:
            due.append("cool_down")
            mem["lastCool"] = m
    else:
        w, h = WORK_MIN[reg], m % 60
        if w < 60:
            if h == w - 5:
                due.append("rest_soon")
            if h == w:
                due.append("rest_now")
            if h == 0 and m > 0:
                due.append("back_to_work")
        if ctx.get("fasting"):
            if lv >= 2 and m - mem["lastFast"] >= 30:
                due.append("fast_cool")
                mem["lastFast"] = m
        else:
            every = 15 if lv >= 2 else 20
            mem["cups"] = [t for t in mem["cups"] if m - t < 60]
            if ("drink" not in mem["pending"] and m - mem["lastDrink"] >= every
                    and len(mem["cups"]) < MAX_CUPS_PER_HOUR):
                due.append("drink")
                mem["lastDrink"] = m
                mem["cups"].append(m)
    meal: Optional[int] = ctx.get("mealAt")
    if meal is not None:
        if m == meal - 5:
            due.append("meal_soon")
        if m == meal:
            due.append("meal_now")

    for d in due:
        if d not in mem["pending"]:
            mem["pending"].append(d)
    urgent = any(d in URGENT for d in mem["pending"])
    buzz = None
    if mem["pending"] and (urgent or m - mem["lastBuzz"] >= MIN_GAP):
        buzz = {"minute": m, "codes": list(mem["pending"]),
                "pattern": "long + short" if urgent else "1 short tick",
                "text": [TEXT[c] for c in mem["pending"]]}
        mem["pending"] = []
        mem["lastBuzz"] = m
    return {"regime": reg, "buzz": buzz}


def run_day(steps: List[Dict]) -> List[Dict]:
    mem: Dict = {}
    return [remind_minute(mem, ctx) for ctx in steps]
