"""Run the 50-case benchmark: approaches A, B and C on the SIMULATED streams.

Usage:
    python -m heatwatch.simulate        # build data/simulated/ first
    python -m heatwatch.bench           # writes results/benchmark_results.csv

Approach C never reads truth.csv. The reference core is used only to score
the core estimate (absolute error).
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from heatwatch.physiology import Profile, assess_a, assess_b, assess_c, readings_from_rows

ROOT = Path(__file__).resolve().parents[1]
RANK_ = {"GREEN": 0, "DATA GAP": 1, "AMBER": 1, "RED": 2}


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """95 % Wilson score interval for k successes out of n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def run(sim_dir: Path = ROOT / "data" / "simulated",
        cases_csv: Path = ROOT / "data" / "benchmark" / "cases.csv",
        out_dir: Path = ROOT / "results") -> dict:
    streams = defaultdict(list)
    with open(sim_dir / "streams.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            streams[r["case_id"]].append(r)
    truth = defaultdict(list)
    with open(sim_dir / "truth.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[r["case_id"]].append(r)
    profiles = {p["case_id"]: p for p in json.loads((sim_dir / "profiles.json").read_text())}
    with open(cases_csv, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    rows = []
    for c in cases:
        cid = c["case_id"]
        pr = profiles[cid]
        prof = Profile(pr["age"], pr["acclimatised_days"], pr["workload"],
                       pr.get("consent", True), pr.get("clothing", "work_clothes"))
        res = {}
        for name, fn in (("A", assess_a), ("B", assess_b), ("C", assess_c)):
            res[name] = fn(readings_from_rows([dict(r) for r in streams[cid]]), prof)
        ref = [float(t["ref_core_c"]) for t in truth[cid] if t["ref_core_c"] != ""]
        ref_end = ref[-1] if ref else None
        est = res["C"].core_est
        err = abs(est - ref_end) if (est is not None and ref_end is not None) else None
        # Time to alert: replay the stream minute by minute (streaming, as on the band).
        stream_rows = [dict(r) for r in streams[cid]]
        t_alert = None
        if c["expected_level"] in ("AMBER", "RED"):
            for k in range(6, len(stream_rows) + 1, 6):
                lv = assess_c(readings_from_rows([dict(r) for r in stream_rows[:k]]), prof).level
                if RANK_[lv] >= RANK_[c["expected_level"]]:
                    t_alert = int(float(stream_rows[k - 1]["t_s"]))
                    break
        # Lead time for RED: reference core first reaching 38.5 C minus alert time.
        t_danger = next((int(float(t["t_s"])) for t in truth[cid]
                         if t["ref_core_c"] != "" and float(t["ref_core_c"]) >= 38.5), None)
        lead = (t_danger - t_alert) if (c["expected_level"] == "RED" and t_alert is not None
                                        and t_danger is not None) else None
        rows.append({
            "case_id": cid, "set": c["set"], "expected": c["expected_level"],
            "A": res["A"].level, "B": res["B"].level, "C": res["C"].level,
            "pass_A": res["A"].level == c["expected_level"],
            "pass_B": res["B"].level == c["expected_level"],
            "pass_C": res["C"].level == c["expected_level"],
            "C_core_est": est, "ref_core_end": ref_end,
            "core_abs_err": None if err is None else round(err, 2),
            "C_time_to_alert_s": t_alert,
            "C_lead_time_s": lead,
            "C_reasons": " | ".join(res["C"].reasons),
            "C_flags": " | ".join(res["C"].flags),
            "C_stages": json.dumps(res["C"].stages),
            "age": pr["age"], "acclimatised_days": pr["acclimatised_days"], "workload": pr["workload"],
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "benchmark_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for a in "ABC":
        red = [r for r in rows if r["expected"] == "RED"]
        tp = sum(r[a] == "RED" for r in red)
        green = [r for r in rows if r["expected"] == "GREEN"]
        fa = sum(r[a] in ("AMBER", "RED") for r in green)
        false_red = sum(r[a] == "RED" and r["expected"] != "RED" for r in rows)
        acc = sum(r[f"pass_{a}"] for r in rows)
        raised = sum(r[a] == "RED" for r in rows)
        ppv = tp / raised if raised else float("nan")
        plo, phi = wilson(tp, raised)
        lo, hi = wilson(tp, len(red))
        summary[a] = {"red_recall": f"{tp}/{len(red)}", "red_recall_ci95": [round(lo, 3), round(hi, 3)],
                      "false_alarms_on_green": f"{fa}/{len(green)}", "false_red": false_red,
                      "red_ppv": f"{tp}/{raised}", "red_ppv_ci95": [round(plo, 3), round(phi, 3)],
                      "accuracy": f"{acc}/{len(rows)}"}
    errs = [r["core_abs_err"] for r in rows if r["core_abs_err"] is not None]
    summary["C_core_estimate"] = {"cases": len(errs),
                                  "mean_abs_err_c": round(sum(errs) / len(errs), 2) if errs else None,
                                  "max_abs_err_c": max(errs) if errs else None}
    tta = [r["C_time_to_alert_s"] for r in rows if r["C_time_to_alert_s"] is not None]
    leads = [r["C_lead_time_s"] for r in rows if r["C_lead_time_s"] is not None]
    summary["C_alerting"] = {
        "cases_alerted": len(tta),
        "median_time_to_alert_s": sorted(tta)[len(tta) // 2] if tta else None,
        "red_lead_time_s": {"cases": len(leads),
                            "median": sorted(leads)[len(leads) // 2] if leads else None,
                            "min": min(leads) if leads else None},
        "note": "Evaluated every 60 s on the stream; on-device latency is not measured in simulation.",
    }
    summary["note"] = ("All data SIMULATED. Results show the safety logic runs, "
                       "not field performance.")
    (out_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
