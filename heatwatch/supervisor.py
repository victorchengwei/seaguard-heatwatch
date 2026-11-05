"""Supervisor readiness and alert routing.

Gulf sites bring together workers from many countries, languages, faiths and
habits. Many left home to earn for their families. A supervisor must be
trained before going on site, so alerts are handled with skill and respect.

Rule (tested): a supervisor who has not finished the training is never the
only person who receives an alert. Every AMBER, RED or DATA GAP alert is also
copied to the site safety officer until the training is complete.
"""
from __future__ import annotations

TRAINING = [
    {"id": "heat_illness", "title": "Heat illness first",
     "detail": "Early signs (cramps, dizziness, confusion, no sweating), first aid, cool-down, when to call the medic."},
    {"id": "respect", "title": "Respect and dignity",
     "detail": "Speak privately and calmly. No shouting, shaming or blame. The worker's dignity comes first."},
    {"id": "language", "title": "Language access",
     "detail": "Use the worker's language in the app and pictograms; use a trusted interpreter, not a random co-worker; "
               "check understanding by asking the worker to say the instruction back."},
    {"id": "culture", "title": "Culture and faith",
     "detail": "Prayer times, Ramadan fasting (higher dehydration risk: plan heavy work for cooler hours), "
               "food habits, personal space and gender norms."},
    {"id": "pay_fear", "title": "Fear of losing pay",
     "detail": "Most workers support families at home and may hide symptoms to protect their wages. "
               "Say clearly and often: heat breaks never cost pay."},
    {"id": "rules", "title": "Rules and rights",
     "detail": "UAE midday break: no outdoor work 12:30-15:00, 15 June to 15 September (MOHRE). "
               "Health data is private; HeatWatch is never used for discipline."},
    {"id": "app", "title": "Using HeatWatch",
     "detail": "Acknowledge within 2 minutes, follow the escalation ladder, explain what each colour means and does not mean."},
]
TRAINING_IDS = [t["id"] for t in TRAINING]


def readiness(done: list) -> dict:
    missing = [t["id"] for t in TRAINING if t["id"] not in set(done)]
    return {"ready": not missing, "done": len(TRAINING) - len(missing),
            "total": len(TRAINING), "missing": missing}


def route_alert(level: str, done: list) -> dict:
    """Who receives an alert. An untrained supervisor is never alone."""
    r = readiness(done)
    to = []
    if level in ("AMBER", "RED", "DATA GAP"):
        to.append("supervisor")
        if not r["ready"]:
            to.append("safety officer (supervisor training not complete)")
    if level == "RED":
        to.append("site medic if not acknowledged within 2 min")
    return {"level": level, "recipients": to, "supervisor_ready": r["ready"]}
