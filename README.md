# SeaGuard HeatWatch

**Heat-stress early warning for port, offshore and outdoor workers.**
Future Health Digital Innovation Challenge · [Population Health] Climate-Resilient Worker Health

> **Rules decide. AI only explains. People decide.**

**Live demo:** [Judge guide](https://seaguard-heatwatch-1061831968639.asia-east1.run.app/judges) · [Guided demo](https://seaguard-heatwatch-1061831968639.asia-east1.run.app/demo) · [Worker app](https://seaguard-heatwatch-1061831968639.asia-east1.run.app/)

**Backup mirror (Azure):** [Judge guide](https://seaguard-heatwatch-tw-hvgrhqhqfnachjcw.eastasia-01.azurewebsites.net/judges) · [Guided demo](https://seaguard-heatwatch-tw-hvgrhqhqfnachjcw.eastasia-01.azurewebsites.net/demo) · [Worker app](https://seaguard-heatwatch-tw-hvgrhqhqfnachjcw.eastasia-01.azurewebsites.net/) (free tier: the first load can take about 30 s)

**In 30 seconds:** Heat illness hits outdoor workers before they or their supervisors notice. HeatWatch combines site weather (WBGT and the Abu Dhabi ADOSH Thermal Work Limit), a watch's heart rate and each worker's context (workload, PPE, acclimatisation, how they feel today) in a transparent rules engine. Every level comes with one clear action. On a 52-case simulated benchmark it caught every RED case (15/15), with a median of about 7 minutes' warning, and gave **0 false alarms on 16 safe cases** versus 8/16 for WBGT alone. A back-test on real Abu Dhabi weather (May to September 2025) shows most dangerous hours fall outside the UAE midday work ban. It speaks 12 worker languages, works offline, fails safe, and never uses data for discipline, rating, hiring or insurance.

> ⚠️ All worker data is **SIMULATED**; weather in the back-test is real (Open-Meteo, CC BY 4.0). Results show the safety logic works as designed, not field performance. Not a medical device.

## Pages

| Page | What it shows |
| --- | --- |
| `/judges` | 3-minute judge guide: 6 one-click steps |
| `/` | Worker app: level, action, work-rest, water, ADOSH zone, simulated watch, 12 languages |
| `/supervisor` | Crew colours, 24-hour planner, decisions with no plain "OK" |
| `/control` | Control Centre: site map, live watches, man-down, human decision log |
| `/demo` | Guided demo: 7 simulated workers, supervisor board, worker band, health office, benchmark |

## What works now (v0.16)

v0.16 joins the two development lines: the v0.15 worker, supervisor and Control Centre app, and the guided demo with the 52-case benchmark.

### Worker, supervisor, Control Centre (`/`, `/supervisor`, `/control`, `/judges`)
- `heatwatch/rules.py`: rules engine. WBGT estimate (Stull wet bulb + standard WBGT weighting), adjusted for workload, clothing/PPE, acclimatization, clinician "stricter limit" flag and time worked; 4 levels with one action each.
- Safety rules: "I feel unwell" always escalates; missing data → fail-safe level High; stale data adds a +2 °C margin; going offline never lowers the last known level.
- `app.py`: FastAPI API (`/api/assess`, `/health`) and the worker web app (`/`).
- `heatwatch/planner.py` + `/supervisor`: crew-level colours (no personal data) and a 24-hour planner that finds the coolest safe window for heavy and moderate work. Sun strength varies with time of day.
- `heatwatch/backtest.py`: back-test on real Abu Dhabi hourly weather, May–Sep 2025 (`data/`, Open-Meteo, CC BY 4.0). Results in `data/backtest_results.json`. Forecasts are read +2 °C hotter (safety margin): for moderate work, simulated missed dangerous hours fall from 16.0% to 4.7%, false alarms rise from 8.0% to 15.3%. Of the High/Stop hours (moderate work), 12.4% fall inside the UAE midday ban, 57.0% on the same summer days outside 12:30–15:00, and 30.6% before or after the ban season. About 25% could move to safer early or late hours the same day; in July–August only about 3 safe hours a day remain, so work–rest cycles and cooling matter most.
- Work–rest in plain words on every level (e.g. "Work 45 min, rest 15 min each hour"); Stop work always shows "No work", and time already worked makes the schedule one step stricter.
- `static/watch.js` (+ Python mirror `heatwatch/watch.py`): simulated watch, one reading per minute. Core temperature estimated from heart rate with the Kalman filter of Buller et al. (2013); excessive-strain limits from ACGIH as given in the OSHA Technical Manual (sustained heart rate > 180 − age; core temperature 38.5 °C acclimatized / 38.0 °C not acclimatized); fall followed by no movement = possible man down. Runs in the browser (standing in for the watch): heart rate, temperature estimate and age never leave it; only level, reason codes and an escalate flag are sent. Warning bands 0.7 °C and 0.3 °C below the limit are prototype choices for clinical review. Scenarios are synthetic.
- Cooling what-if (`cooling_what_if` in `backtest.py`, scenario only): if cooling workwear lowered the heat a worker feels by 1, 1.5 or 2 °C WBGT, daytime High/Stop hours for moderate work in Abu Dhabi 2025 would fall by 18%, 27% or 39% (heavy work: 9%, 16%, 23%). The real effect of any garment must be measured in the pilot.
- `heatwatch/decisions.py` + "Decisions needed" on `/supervisor` (anti-rubber-stamp, against automation bias): at High or Stop the supervisor must choose a real action (rest, rotate crew, move task, cooling, stop, call medic; Stop only accepts stopping actions); a plain "OK" is refused. Every decision is logged with its response time. No decision within 10 minutes escalates to the site manager. After a decision the same crew is not re-alerted for 30 minutes unless its level rises (no alarm spam). The panel reports adherence to controls: share acted on, share within 10 minutes, median response, escalations (pilot target ≥80% acted on). Demo clock; each browser tab has its own demo log; in production the log lives in a database.
- Kidney protection: every level carries a hydration prompt (NIOSH 2017: about 250 ml every 15–20 minutes, no more than 1.4 L per hour), and the worker app has a private urine-colour self-check (based on Armstrong's validated chart; never recorded). Background: 15% of workers in regular heat stress had kidney disease or acute kidney injury (Flouris et al., Lancet Planetary Health 2018). The clinician "stricter limit" flag covers workers with kidney conditions without storing a diagnosis.
- `heatwatch/twl.py` (new in v0.9): Abu Dhabi ADOSH-SF Thermal Work Limit (ADOSH-SF = Abu Dhabi Occupational Safety and Health System Framework, called OSHAD-SF before v4.0; CoP 11.0 "Safety in the Heat" v4.0, July 2024, and its Technical Guideline). TWL (W/m²) is estimated with a transparent heat-balance model on Brake & Bates' principles (core 38.2 °C, maximal skin blood flow, sweat ≤ about 1.2 L/h, ISO/ASHRAE heat-exchange coefficients); it is NOT the official calculator and must be validated against it. Zones: > 220 Unrestricted, 140–220 Acclimatisation, 115–140 Buffer, < 115 Withdrawal (also dry bulb > 44 °C or wet bulb > 32 °C). The final level is the stricter of WBGT (ACGIH) and TWL (ADOSH); unacclimatised workers may not work in Buffer. Withdrawal shows the ADOSH schedule (emergency work only, under permit, 20 min work / 40 min rest, 1.2 L per hour). Unknown wind is taken as calm (fail-safe); impermeable suits skip TWL (not valid) and use WBGT. Worker and supervisor screens show the zone and its rules. `twl_zone_hours` in `backtest.py` gives daytime hours per zone in Abu Dhabi 2025 (`data/twl_zone_hours.json`; estimated globe and wind, indicative only). The published WBGT back-test numbers are unchanged.
- Watch face (new in v0.10, concept v0.1) on the worker app's simulated watch: one glance = colour + big level number + one word + icon (drop / shade / stop), so it works for colour-blind workers and in any language; a 4-segment ring lights only the current level; "MAN DOWN" replaces the word after a fall with no movement; vibration pattern shown per level (1 pulse Caution, 2 High, long and repeating Stop). Brand-neutral: a "Watch model" selector (Wear OS, Apple Watch, Garmin, Huawei, other brands through the phone's health app, chest strap + phone) shows how each would connect; the same rules and the same face run on every device. No real device is connected yet: all simulated.
- Watch reminders (new in v0.11, `static/reminders.js` + Python mirror `heatwatch/reminders.py`, run on the watch, nothing sent): water 1 cup (250 ml) every 20 min at level 1 and every 15 min at levels 2–3, never more than 5 cups (1.25 L) in 60 minutes; rest countdown from the work–rest schedule ("rest in 5 min", "rest now", "back to work"); meal reminder with a little extra salt (ADOSH-SF TG 5.6); fasting mode (e.g. Ramadan): no drink reminders, rest one step stricter, "rest in shade, cool your skin" every 30 min (prototype choice for clinical and community review); Stop: "cool down" every 10 minutes; acclimatisation day counter on the face (ADOSH-SF table, e.g. "DAY 2/5 · 40% WORK"). Alarm limit: reminders are merged into one buzz, at most one every 5 minutes unless urgent; reminders use their own vibration patterns (long + short, short tick) so they are never confused with level alarms. Worker colour themes (Night, Navy, Olive, Sand) change only the background and clock; the safety colours never change.
- Worker alerts in 12 languages (new in v0.12, `static/i18n.js`): English, Arabic, Hindi, Urdu, Bengali, Malayalam, Tamil, Nepali, Filipino, Sinhala, Swahili, Chinese. 38 safety phrases each: level names, watch-face words, actions, work–rest schedules, water advice, reminders and the two emergency buttons. Arabic and Urdu read right to left. The device translates the English messages from the rules engine, so the rules never change by language; numbers (minutes, ml, litres) are identical in every language and a test enforces it (it caught "one cup" written as a word in Arabic and Sinhala). Read-aloud button uses the phone's own voices (if the phone has a voice for that language). The chosen language is remembered on the device. ALL NON-ENGLISH TEXT IS AN AI-DRAFTED TRANSLATION and must be checked by native speakers (ideally with occupational-health knowledge) before real use; the screen says so. Not yet translated: the Abu Dhabi zone details and the technical "why" list (shown in English, left to right). Next languages, with native translators first: Pashto, Punjabi, Telugu, Kannada.
- Control Centre (`/control`, new in v0.13): the "human in command" view that joins the watches, the crews and the decisions. Flow on screen: Detect (watches, weather, sensors) → Recommend (fixed rules; AI only explains) → Human decides → Log and learn. Live simulated watches (three work IDs, synthetic scenarios) send only level and reason code; a watch at High or Stop opens an event that a duty officer must answer with a real action (e.g. "Send first aider now", "Call worker by radio", "Checked: false alarm"); no answer in 3 minutes escalates to the site manager (ADOSH-SF TG Appendix 6: first aid within 3 minutes). Crew decisions use the same anti-rubber-stamp API as the supervisor view. A human decision log records who chose what and when. A navigation bar links Worker, Supervisor and Control centre. The header image is an AI-generated concept image and is labelled as such on screen.
- Site map in the Control Centre (new in v0.14): Khalifa Port area, Abu Dhabi; each crew is a big dot and each watch a small dot, coloured by level (green, yellow, orange, red) and updated with the hour slider and the live watch demo; a watch reporting a possible man down blinks. Positions are synthetic and labelled so. Map library Leaflet 1.9.4 is bundled in `static/vendor/leaflet` with its BSD-2-Clause licence (no CDN needed); map tiles come from CARTO basemaps with OpenStreetMap data, credited on the map. For a commercial pilot: a paid tile plan or Azure Maps. If the map cannot load (offline), the crew list still works.
- Judge guide (`/judges`, new in v0.15): a 3-minute walk-through in 5 one-click steps (warm morning; Abu Dhabi Withdrawal zone; man down in Arabic; supervisor with no plain "OK"; Control Centre), language and fasting-mode shortcuts, where to see each of the 6 assessment criteria, and honest notes (synthetic data, AI-drafted translations, TWL estimate, not a medical device). Every page reads URL settings so a link opens a ready scenario, e.g. `/?sc=man_down&play=1&lang=ar`, `/supervisor?hour=13`, `/control?hour=9&live=1`. All pages link to it from the top bar.


### Guided demo and benchmark (`/demo`)
- `heatwatch/physiology.py`: sensor guardrails, core-temperature estimate (Kalman filter, Buller et al. 2013), body-based rules, consent gate, PPE adjustment.
- `heatwatch/explain.py`: plain-language explanations. If the explainer fails, the screen says so and the rule-based action stays.
- `heatwatch/wellbeing.py`: optional private daily check-in (mood, sleep, fasting). A hard day triggers AMBER earlier; RED thresholds never change. RED wording is always firm. Never used for discipline, rating, hiring or insurance.
- `heatwatch/supervisor.py`: 7 training modules before going on site (heat illness, respect, language, culture and faith incl. Ramadan, fear of losing pay, rules incl. the UAE midday break, using HeatWatch). Until training is done, every alert is copied to the site safety officer.
- `heatwatch/privacy.py`: colour-only crew board; small-cell suppression (counts below 5 shown as "<5").
- `heatwatch/simulate.py`, `heatwatch/bench.py`: SIMULATED sensor streams and the 52-case benchmark.

## Validation

### Simulated benchmark (52 cases)
6 smoke, 22 normal, 24 tough (sensor faults, wrong units, no network, clock drift, duplicate readings, no consent, PPE). Three approaches on the same cases. 95% confidence intervals use the Wilson method.

| Approach | RED recall | RED precision (PPV) | False alarms on safe (GREEN) cases¹ |
|---|---|---|---|
| A: WBGT rule only (today's practice) | 15/15 (80–100%) | 15/31 (32–65%) | 8/16 (28–72%) |
| B: WBGT + heart rate | 15/15 (80–100%) | 15/17 (66–97%) | 8/16 (28–72%) |
| **C: HeatWatch** | **15/15 (80–100%)** | **15/17 (66–97%)** | **0/16 (0–19%)** |

¹ *False alarm = an AMBER or RED alert on one of the 16 cases whose correct answer is GREEN.*

| Additional metric | HeatWatch |
|---|---|
| RED lead time before simulated core temp 38.5 °C | median 7.3 min (440 s), shortest 50 s, measured on 12 of 15 RED cases |
| AMBER cases | 10/20 correct, 2/20 raised higher as RED (safe side), **8/20 missed as GREEN** |
| Core-temperature estimate error | mean 0.3 °C, max 1.04 °C (48 cases) |

### Back-test on real weather
See the `heatwatch/backtest.py` entry above: Abu Dhabi hourly weather, May to September 2025, with the +2 °C forecast margin, the midday-ban split and the cooling what-if.

### Known limitations, stated openly
- **8 of 20 AMBER cases were missed (shown as GREEN).** The core-temperature estimator lags. RED was never missed, but earlier AMBER is the next fix.
- The estimator was validated mainly in military volunteers; it must be validated for port, offshore and construction workers in a pilot.
- The same team built the rules and the simulator. A held-out set and real field data are needed.
- All non-English worker text is an AI-drafted translation and must be checked by native speakers.

Reproduce:
```bash
python -m heatwatch.simulate   # SIMULATED sensor streams
python -m heatwatch.bench      # results/benchmark_summary.json
pytest                         # 142 tests
```

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
# open http://127.0.0.1:8000/judges
```

## Deploy
Live on Google Cloud Run (asia-east1), built from this repository's `Dockerfile` on every push to `main`. The same container runs on Azure App Service or Container Apps (`DEPLOY_AZURE.md`). No secrets in code; the optional AI explainer key is an environment variable.

## Assumptions and limitations
- WBGT is estimated from air temperature and humidity; a measured WBGT sensor overrides it. Sun assumes a globe temperature 12 °C above air (conservative).
- Work–rest limits follow the ACGIH TLV / Action Limit screening table; values checked against the table as reproduced by Cal/OSHA (dir.ca.gov heat-tlv.pdf). Clinical mentors to review before any use.
- Historical weather: Open-Meteo, CC BY 4.0. "Weather data by Open-Meteo.com" must be shown wherever it is displayed.
- Official zone name "Withdrawal Zone" confirmed in the Technical Guideline v4.0 (Appendix 5). TWL zone limits come from HAAD (The National 2011), Miller & Bates 2007 and Wikipedia; the official Table 1 in the Technical Guideline v4.0 is an image and its wording still has to be checked. TWL is checked against one published point (33/28 °C, 0.5 m/s ≈ 174 W/m² with light clothing); default work clothes are 0.6 clo (conservative).
- Not a medical device; it does not diagnose. Prototype data is synthetic; no personal data is used.

## Next
Validate TWL against the official ADOSH calculator · earlier AMBER in the benchmark (estimator lag) · seafarer and port-worker questionnaire · Azure OpenAI multilingual explanations · Azure AI Speech voice alerts · physics-based (Liljegren) WBGT · tester feedback from seafarers.

## Team
**SeaGuard HeatWatch**: Victor Chen (team lead). Licensed Chief Mate with 2+ years on a DP2 offshore vessel; M.S. in Information and Electrical Engineering (computer vision for ship detection).

## License
MIT (see `LICENSE`).
