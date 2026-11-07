/* SeaGuard HeatWatch - watch reminders (run ON the watch, nothing is sent).
 *
 * One call per minute. Returns at most one buzz, with every reminder that is due
 * merged into it, so workers are not flooded (alarm fatigue).
 *  - Water: 1 cup (250 ml) every 20 min at level 1, every 15 min at levels 2-3
 *    (ADOSH-SF TG: 2 L every 2-3 h; NIOSH 2017: 250 ml every 15-20 min);
 *    never more than 5 cups (1.25 L) in 60 min (NIOSH: no more than 1.4 L/h).
 *  - Rest: from the work-rest schedule: "rest in 5 min", "rest now", "back to work".
 *  - Meal: 5-minute warning and "meal now: eat, drink, a little extra salt"
 *    (ADOSH-SF TG 5.6: salt with meals; Appendix 6: snacks on site).
 *  - Fasting mode (e.g. Ramadan): no drink reminders; rest one step stricter and a
 *    "rest in shade, cool your skin" reminder every 30 min at level 2+.
 *    PROTOTYPE CHOICE, to review with clinicians and religious/community advisers.
 *  - Stop (level 4): "cool down" every 10 min.
 *  - Acclimatisation: percent of a full work assignment by day (ADOSH-SF TG section 3).
 * Urgent reminders (rest now, back to work, cool down) buzz at once; others wait
 * until 5 minutes have passed since the last buzz.
 */
(function (root) {
  "use strict";

  const WORK_MIN = { "75-100": 60, "50-75": 45, "25-50": 30, "0-25": 15 };
  const STRICTER = { "75-100": "50-75", "50-75": "25-50", "25-50": "0-25", "0-25": "0-25" };
  const MAX_CUPS_PER_HOUR = 5;
  const MIN_GAP = 5;
  const URGENT = ["rest_now", "back_to_work", "cool_down"];
  const TEXT = {
    drink: "Drink 1 cup of water (250 ml)",
    rest_soon: "Rest in 5 minutes",
    rest_now: "Rest now: shade or cooled rest area",
    back_to_work: "Rest over: back to work at your own pace",
    meal_soon: "Meal break in 5 minutes",
    meal_now: "Meal: eat, drink water, a little extra salt",
    fast_cool: "Fasting: rest in shade, cool your skin with water",
    cool_down: "Stop work: cool down, tell your supervisor",
  };
  const ACCLIM = { experienced: [50, 60, 80, 100, 100], new: [20, 40, 60, 80, 100] };

  function acclimPct(day, isNew) {
    const t = isNew ? ACCLIM.new : ACCLIM.experienced;
    if (day < 1) return t[0];
    return day > 5 ? 100 : t[day - 1];
  }

  function regimeFor(level, regime, fasting) {
    if (level >= 4) return "stop";
    return fasting ? STRICTER[regime] : regime;
  }

  // mem: {} at the start of a shift. ctx: {minute, level, regime, fasting, mealAt}
  function remindMinute(mem, ctx) {
    if (!mem.init) Object.assign(mem, { init: true, lastDrink: 0, cups: [], lastBuzz: -1000, lastFast: 0, lastCool: -1000, pending: [] });
    const m = ctx.minute, lv = ctx.level, due = [];
    const reg = regimeFor(lv, ctx.regime, ctx.fasting);

    if (lv >= 4) {
      if (m - mem.lastCool >= 10) { due.push("cool_down"); mem.lastCool = m; }
    } else {
      const w = WORK_MIN[reg], h = m % 60;
      if (w < 60) {
        if (h === w - 5) due.push("rest_soon");
        if (h === w) due.push("rest_now");
        if (h === 0 && m > 0) due.push("back_to_work");
      }
      if (ctx.fasting) {
        if (lv >= 2 && m - mem.lastFast >= 30) { due.push("fast_cool"); mem.lastFast = m; }
      } else {
        const every = lv >= 2 ? 15 : 20;
        mem.cups = mem.cups.filter((t) => m - t < 60);
        const pendingDrink = mem.pending.indexOf("drink") >= 0;
        if (!pendingDrink && m - mem.lastDrink >= every && mem.cups.length < MAX_CUPS_PER_HOUR) {
          due.push("drink"); mem.lastDrink = m; mem.cups.push(m);
        }
      }
    }
    if (ctx.mealAt != null) {
      if (m === ctx.mealAt - 5) due.push("meal_soon");
      if (m === ctx.mealAt) due.push("meal_now");
    }

    due.forEach((d) => { if (mem.pending.indexOf(d) < 0) mem.pending.push(d); });
    const urgent = mem.pending.some((d) => URGENT.indexOf(d) >= 0);
    let buzz = null;
    if (mem.pending.length && (urgent || m - mem.lastBuzz >= MIN_GAP)) {
      buzz = { minute: m, codes: mem.pending.slice(), pattern: urgent ? "long + short" : "1 short tick",
               text: mem.pending.map((c) => TEXT[c]) };
      mem.pending = []; mem.lastBuzz = m;
    }
    return { regime: reg, buzz: buzz };
  }

  function runDay(steps) {
    const mem = {};
    return steps.map((ctx) => remindMinute(mem, ctx));
  }

  const api = { remindMinute, runDay, acclimPct, regimeFor, TEXT, WORK_MIN };
  root.HeatWatchReminders = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
