/* SeaGuard HeatWatch - simulated watch (runs ON the device).
 *
 * Body data (heart rate, estimated core temperature, age) never leaves this code.
 * Only the watch level (1-4), short reason codes and an escalate flag are sent on.
 *
 * Core temperature from heart rate: Kalman filter of Buller et al. (2013),
 * Physiol. Meas. 34:781 (parameters as published; also in US patent 10,702,165).
 * Strain limits: ACGIH excessive-heat-strain criteria as given in the OSHA Technical
 * Manual (Sec. III, Ch. 4): sustained HR > 180 - age; core temperature > 38.5 C
 * (acclimatized, medically selected) or > 38.0 C (unacclimatized).
 * Prototype only: thresholds to be reviewed with clinical mentors before any use.
 * All scenarios are SYNTHETIC demo data.
 */
(function (root) {
  "use strict";

  const KF = { a: 1.0, gamma: 0.022, b0: -7887.1, b1: 384.4286, b2: -4.5714, sigma: 18.88, ct0: 37.1, v0: 0.0 };
  const SUSTAINED_MIN = 5;      // minutes above the HR limit = "sustained"
  const NO_MOTION_ALONE_MIN = 5; // no movement at all for this long during work
  const FALL_NO_MOTION_MIN = 1;  // after a fall, no movement for this long
  const NEAR_C = 0.3, RISING_C = 0.7; // prototype warning bands below the ACGIH limit (to review)

  function ectempStep(state, hr) {
    const xp = KF.a * state.ct;
    const vp = KF.a * KF.a * state.v + KF.gamma * KF.gamma;
    const c = 2 * KF.b2 * xp + KF.b1;
    const k = (vp * c) / (c * c * vp + KF.sigma * KF.sigma);
    const expected = KF.b2 * xp * xp + KF.b1 * xp + KF.b0;
    return { ct: xp + k * (hr - expected), v: (1 - k * c) * vp };
  }

  function ectemp(hrSeries, ct0) {
    let s = { ct: ct0 === undefined ? KF.ct0 : ct0, v: KF.v0 };
    return hrSeries.map(hr => { s = ectempStep(s, hr); return Math.round(s.ct * 100) / 100; });
  }

  /* One minute of watch logic. `mem` carries counters between minutes (stays on device). */
  function watchMinute(mem, sample, settings) {
    const hrLimit = 180 - settings.age;
    const ctLimit = settings.acclimatized ? 38.5 : 38.0;
    mem.kf = mem.kf ? ectempStep(mem.kf, sample.hr) : ectempStep({ ct: KF.ct0, v: KF.v0 }, sample.hr);
    mem.overHr = sample.hr > hrLimit ? (mem.overHr || 0) + 1 : 0;
    mem.still = sample.moving ? 0 : (mem.still || 0) + 1;
    if (sample.fall) mem.fell = true;
    if (sample.moving) mem.fell = false;

    const ct = mem.kf.ct;
    let level = 1;
    const reasons = [];
    if ((mem.fell && mem.still >= FALL_NO_MOTION_MIN) || mem.still >= NO_MOTION_ALONE_MIN) {
      level = 4; reasons.push("possible_man_down");
    }
    if (ct >= ctLimit) { level = 4; reasons.push("core_temp_over_limit"); }
    else if (ct >= ctLimit - NEAR_C) { level = Math.max(level, 3); reasons.push("core_temp_near_limit"); }
    else if (ct >= ctLimit - RISING_C) { level = Math.max(level, 2); reasons.push("core_temp_rising"); }
    if (mem.overHr >= SUSTAINED_MIN) { level = 4; reasons.push("sustained_heart_rate_over_limit"); }
    else if (mem.overHr >= 2) { level = Math.max(level, 2); reasons.push("heart_rate_over_limit"); }

    // What leaves the watch: level, reason codes, escalate flag. Never HR, temperature or age.
    const outbound = { level, reasons, escalate: level === 4 };
    // What the worker sees on their own watch:
    const local = { hr: sample.hr, ct_est: Math.round(ct * 100) / 100, hr_limit: hrLimit, ct_limit: ctLimit };
    return { outbound, local };
  }

  /* Synthetic 60-minute scenarios (deterministic, clearly labelled as demo data). */
  function scenario(name) {
    const out = [];
    for (let m = 0; m < 60; m++) {
      const wobble = 3 * Math.sin(m / 3);
      if (name === "rising") {
        out.push({ minute: m, hr: Math.round(100 + m * 1.0 + wobble), moving: true, fall: false });
      } else if (name === "man_down") {
        const down = m >= 25;
        out.push({ minute: m, hr: Math.round((down ? 125 - (m - 25) * 0.8 : 108) + wobble),
                   moving: !down, fall: m === 25 });
      } else {
        out.push({ minute: m, hr: Math.round(105 + wobble), moving: true, fall: false });
      }
    }
    return out;
  }

  function run(name, settings) {
    const mem = {};
    return scenario(name).map(s => ({ minute: s.minute, ...watchMinute(mem, s, settings) }));
  }

  const api = { KF, ectemp, watchMinute, scenario, run };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HeatWatchWatch = api;
})(this);
