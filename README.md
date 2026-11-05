# SeaGuard HeatWatch

**Heat-stress early warning for port, offshore and outdoor workers.**
Future Health Digital Innovation Challenge · [Population Health] Climate-Resilient Worker Health

> **Rules decide. AI only explains. People decide.**

**In 30 seconds:** Heat illness hits outdoor workers before they or their supervisors notice. HeatWatch combines site weather (WBGT), wearable heart rate and each worker's context (workload, PPE, acclimatization, how they feel today) into a transparent rules engine that gives one of four levels, each with one clear action. On a 52-case simulated benchmark it caught every RED case (15/15), with a median of about 7 minutes' warning before the simulated core temperature reached 38.5 °C, and gave **0 false alarms on 16 safe (GREEN) cases**, versus 8/16 for today's WBGT-only practice. It works offline, fails safe, speaks 7 worker languages, and never uses data for discipline, rating, hiring or insurance.

> ⚠️ All results use **SIMULATED** data. They show the safety logic works as designed, not field performance. Not a medical device.

---

## Why it matters

- Port, offshore, construction and logistics workers face rising heat with heavy work and PPE.
- Today's practice (a WBGT reading and a work–rest table) ignores the individual: an unacclimatized worker in coveralls on a bad night's sleep is treated the same as a rested, acclimatized one.
- Many workers are migrants who may not report symptoms for fear of losing pay, or because alerts are not in their language.

## How it works

```
Sensors / weather ──► Guardrails ──► Rules engine ──► Level + one action ──► Worker · Supervisor · Health office
  (WBGT, HR, check-in)  (units, faults,   (WBGT + body +      (GREEN / AMBER /         (AI explainer adds plain words,
                         staleness)        context)            ORANGE / RED)            never changes the level)
```

**Site level** (`heatwatch/rules.py`, from weather and work context):

| Level | Action |
|---|---|
| 1 · Normal | Drink water regularly. |
| 2 · Caution | Drink water now, take shade breaks, check on your buddy. |
| 3 · High | Rest in shade, rotate the crew, move heavy tasks to a cooler time. |
| 4 · Stop work | Stop work, cool down, call the medic or supervisor. |

**Worker alert** (`heatwatch/physiology.py`, from the body): **GREEN** · **AMBER** (take a paid break now) · **RED** (stop work, cool down, supervisor attends) · **DATA GAP** (sensor missing or invalid; treated as at least AMBER, never as safe).

### Safety rules (non-negotiable)
- **"I feel unwell" always escalates.**
- **Missing data → fail-safe level High.** Missing is never treated as zero.
- **Stale data adds a +2 °C margin.**
- **Going offline never lowers the last known level.**
- **AI words never change a level.** If the explainer fails, the app says so openly and still shows the rule-based action.

## What works now (v0.1)

| Module | What it does |
|---|---|
| `heatwatch/rules.py` | WBGT estimate (Stull wet bulb + standard WBGT weighting), adjusted for workload, clothing/PPE, acclimatization, clinician "stricter limit" flag and time worked. 4 site levels, one action each. |
| `heatwatch/physiology.py` | Sensor guardrails, core-temperature estimate (Kalman filter, Buller et al. 2013), body-based rules, consent gate, PPE adjustment. |
| `heatwatch/explain.py` | Plain-language explanations (English/Arabic). Explainer failure is shown, not hidden. |
| `heatwatch/wellbeing.py` | **Workers are people.** Optional private daily check-in (good / OK / tired / stressed, sleep). A hard day triggers AMBER **earlier**; RED thresholds never change. Gentle or direct wording (RED is always firm and cannot be muted). Blame-free welcome back, confidential support offer after several low days (worker only), 7-day heat-adaptation plan (NIOSH 20 %/day), "fasting today" = extra caution. |
| `heatwatch/supervisor.py` | **Supervisor readiness.** 7 training modules before going on site: heat illness, respect and dignity, language access, culture and faith (incl. Ramadan), fear of losing pay, rules (incl. the UAE midday work break), using HeatWatch. Until training is complete, every alert is copied to the site safety officer. |
| `heatwatch/privacy.py` | Colour-only crew board; small-cell suppression for site and regional reports. |
| `heatwatch/demo.py`, `static/demo.html` | **Guided demo at `/demo`.** Six SIMULATED workers (port, offshore, construction, logistics) replayed minute by minute through the same logic as the benchmark. Supervisor board, worker band/phone, health office view, escalation ladder, explainer-failure switch, technical view for judges. |
| `app.py` | FastAPI: `/api/assess`, `/health`, worker web app at `/`. |
| `tests/` | 69 automated tests. |

**Languages:** English, Arabic, Hindi, Urdu, Bengali, Nepali, Tagalog, with pictograms and "heat breaks are paid" on AMBER/RED (site policy setting). Hindi, Urdu, Bengali, Nepali and Tagalog are **draft** translations and need native-speaker review.

## Validation (simulated benchmark)

52 cases: 6 smoke, 22 normal, 24 tough (sensor faults, wrong units, no network, clock drift, duplicate readings, no consent, PPE). Three approaches on the same cases. 95% confidence intervals use the Wilson method.

| Approach | RED recall | RED precision (PPV) | False alarms on safe (GREEN) cases¹ |
|---|---|---|---|
| A: WBGT rule only (today's practice) | 15/15 (80–100%) | 15/31 (32–65%) | 8/16 (28–72%) |
| B: WBGT + heart rate | 15/15 (80–100%) | 15/17 (66–97%) | 8/16 (28–72%) |
| **C: HeatWatch** | **15/15 (80–100%)** | **15/17 (66–97%)** | **0/16 (0–19%)** |

¹ *False alarm = an AMBER or RED alert on one of the 16 cases whose correct answer is GREEN (the other "normal" cases are expected to reach AMBER).*

| Additional metric | HeatWatch |
|---|---|
| RED lead time before simulated core temp 38.5 °C | median 7.3 min (440 s), shortest 50 s, measured on 12 of 15 RED cases |
| AMBER cases | 10/20 correct, 2/20 raised higher as RED (safe side), **8/20 missed as GREEN** |
| Core-temperature estimate error | mean 0.3 °C, max 1.04 °C (48 cases) |
| Behaviour with missing inputs | Fail-safe High in all missing-data cases |
| Data latency handling | Stale data → +2 °C margin |

**Known limitations — stated openly**
- **8 of 20 AMBER cases were missed (shown as GREEN).** The core-temperature estimator lags. RED was never missed, but earlier AMBER is the next fix.
- The estimator was validated mainly in military volunteers; it must be validated for port, offshore and construction workers in a pilot.
- The same team built the rules and the simulator. A held-out set and real field data are needed to rule out designing to the test.

Reproduce:
```bash
python -m heatwatch.simulate   # generate SIMULATED sensor streams
python -m heatwatch.bench      # writes results/benchmark_summary.json
pytest                         # 69 tests
```

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
# open http://127.0.0.1:8000/demo
```

## Deploy (Azure App Service, free F1 tier)
See `DEPLOY_AZURE.md`. No secrets in code; the optional AI explainer key is the environment variable `HEATWATCH_AI_KEY`.

## Assumptions
- WBGT is estimated from air temperature and humidity; a measured WBGT sensor overrides the estimate. Sun exposure assumes a globe temperature 12 °C above air (conservative). The Stull wet-bulb formula is valid for roughly RH 5–99 % and −20 to 50 °C.
- Work–rest limits follow the ACGIH TLV / Action Limit table. **Every threshold must be verified against the current ACGIH booklet and reviewed by clinical mentors before use.**
- UAE midday break rules (typically 15 June–15 September, 12:30–15:00) must be checked against each year's official decision.

## Ethics and privacy
- Not a medical device; it does not diagnose.
- Prototype uses synthetic data only; no personal data.
- Supervisors see colours, not health data. Health office sees anonymous counts with small-cell suppression.
- Wellbeing check-ins are optional and private, and are **never** used for discipline, performance rating, hiring or insurance.

## Roadmap
1. Earlier AMBER (fix estimator lag).
2. Azure OpenAI multilingual explanations; Azure AI Speech voice alerts.
3. Back-test on historical UAE weather.
4. Native-speaker review of all draft translations.
5. Pilot with a port or offshore operator, with clinical oversight.

## Team
**SeaGuard HeatWatch** — Victor Chen (team lead). Licensed Chief Mate with 2+ years on a DP2 offshore vessel; M.S. in Information and Electrical Engineering (computer vision for ship detection).

## License
MIT (see `LICENSE`).
