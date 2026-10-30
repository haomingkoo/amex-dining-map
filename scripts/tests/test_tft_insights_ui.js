#!/usr/bin/env node
// Eligible days, blackouts, value and release panels on the Table for Two card.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const source = fs.readFileSync("web/app.js", "utf8");
const names = [
  "tableForTwoInsights", "tableForTwoClock", "tableForTwoLongDate", "tableForTwoBlackouts",
  "tableForTwoNeverOfferedDay", "tableForTwoDateWarningHtml", "tableForTwoVerdictHtml",
  "tableForTwoWeekStripHtml", "tableForTwoEligibilityHtml", "tableForTwoHourChartHtml",
  "tableForTwoReturnBarsHtml", "tableForTwoWhenTablesHtml", "tableForTwoSeatings",
  "tableForTwoUpcomingBlackouts", "tableForTwoBestTime", "tableForTwoFurthestOpenDate",
  "tableForTwoWhenToBookHtml",
];
const consts = source.match(/const TFT_WEEKDAYS[\s\S]*?\];\nconst TFT_NEXT_BLACKOUT_DAYS = \d+;\nconst TFT_MIN_SIGHTINGS_FOR_CHART = \d+;\nconst TFT_RETURN_BUCKETS = \[[\s\S]*?\];/)[0];

const insights = {
  eligibility_source: { terms_current: true, observed_since: "2026-08-18", new_dates_since: "2026-08-19" },
  venues: {
    "tft-colony": {
      eligibility: {
        terms_current: true,
        observed_meals: [
          { meal: "Lunch", days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], days_label: "Mon–Sat", rare_days: [], never_days: ["Sun"], first_time: "12:30", last_time: "13:30" },
          { meal: "Dinner", days: ["Mon", "Tue", "Wed", "Thu", "Sun"], days_label: "Sun–Thu", rare_days: ["Fri"], never_days: ["Sat"] },
        ],
        merchant_blackouts: ["Easter Sunday"],
        blackout_dates: [{ date: "2099-11-07", reason: "Eve of Deepavali" }, { date: "2000-01-01", reason: "Old" }],
      },
      release: {
        lines: ["Until 30 Sep, new lunch dates opened one day at a time, 61 days ahead. None since."],
        best_time: null, precise_sightings: 6, hour_counts: Array.from({ length: 24 }, (_, i) => (i === 12 ? 6 : 0)),
        furthest_open_dates: { Lunch: "2026-11-30" },
      },
      verdict: {
        line: "Typical value: extra diners pay S$108++ a head, close to the usual S$100++. <b>x</b>",
        tier: "higher",
        facts: [
          "Each of you gets a full set.",
          "Extra diners pay S$108++ a head, about S$129 with service charge and GST.",
          "Google rating 4.6.",
        ],
      },
    },
  },
};

const context = {
  state: { tableForTwoInsights: insights, tableForTwoPatterns: null },
  escapeHtml: (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  singaporeTodayKey: () => "2099-11-01",
  tableForTwoDateOptionLabel: (d) => `label:${d}`,
  Date: class extends Date { static now() { return new Date("2099-11-01T00:00:00Z").getTime(); } },
};
vm.createContext(context);
vm.runInContext(`${consts}\n${names.map((n) => extractFunction(source, n)).join("\n")}`, context);
const colony = { id: "tft-colony" };

assert.equal(context.tableForTwoBlackouts(colony).get("2099-11-07"), "Eve of Deepavali");
assert.match(context.tableForTwoDateWarningHtml(colony, "2099-11-07", []), /black out this day \(Eve of Deepavali\)/);
// 2099-11-07 is a Saturday: dinner was never offered on Saturdays.
assert.match(context.tableForTwoDateWarningHtml(colony, "2099-11-14", [{ meal: "Dinner" }]), /Dinner on this weekday has not been offered/);
assert.equal(context.tableForTwoDateWarningHtml(colony, "2099-11-16", [{ meal: "Lunch" }]), "");

const verdict = context.tableForTwoVerdictHtml(colony);
assert.match(verdict, /tft-verdict is-higher/);
assert.ok(!verdict.includes("<b>"), "verdict text is escaped");
assert.match(verdict, /Each of you gets a full set\./);
assert.match(verdict, /<li>About S\$129 a head with service charge and GST\.<\/li>/);
assert.ok(!verdict.includes("Extra diners pay"), "price is not repeated under the line");
assert.ok(!verdict.includes("Google rating"), "rating badge already shows Google");
insights.venues["tft-colony"].verdict.facts.push("Extra diners pay S$100 nett a head.");
assert.ok(!context.tableForTwoVerdictHtml(colony).includes("S$100 nett"), "a fact that only repeats the line is dropped");
insights.venues["tft-colony"].verdict.facts.pop();

const eligibility = context.tableForTwoEligibilityHtml(colony);
assert.match(eligibility, /Not published\. Check before booking\./);
assert.match(eligibility, /since 18 Aug 2026/);
assert.match(eligibility, /Seatings 12:30pm to 1:30pm/);
assert.match(eligibility, /label:2099-11-07/);
assert.ok(!eligibility.includes("2000-01-01"), "past blackouts are not listed");
assert.match(eligibility, /tft-week-day is-rare/);

const stale = JSON.parse(JSON.stringify(insights));
stale.eligibility_source.terms_current = false;
context.state.tableForTwoInsights = stale;
assert.match(context.tableForTwoEligibilityHtml(colony), /terms changed since our last review/);
context.state.tableForTwoInsights = insights;

const when = context.tableForTwoWhenTablesHtml(colony);
assert.match(when, /New dates <span>since 19 Aug 2026<\/span>/);
assert.match(when, /<svg viewBox/);
assert.ok(!when.includes("Best time to look"), "no best time without data");

context.state.tableForTwoPatterns = {
  started_at: "2026-10-26T13:19:32Z",
  venues: { "tft-colony": { best_time: "Best time to look: weekday mornings, when cancellations have come back most often.", lines: [], returned_tables: 12, return_buckets: { "weekday morning": 8, "weekend evening": 4 } } },
};
const live = context.tableForTwoWhenTablesHtml(colony);
assert.match(live, /Cancelled tables that came back <span>since 26 Oct 2026<\/span>/);
assert.match(live, /When the 12 tables that came back reappeared/);

assert.match(context.tableForTwoEligibilityHtml({ id: "unknown" }), /public holidays and their eves/);

const book = context.tableForTwoWhenToBookHtml(colony);
assert.match(book, /<h4 class="tft-panel-title">When to book<\/h4>/);
assert.match(book, /<strong>Lunch:<\/strong> Mon–Sat, 12:30pm to 1:30pm\./);
assert.match(book, /<strong>Dinner:<\/strong> Sun–Thu\./);
assert.match(book, /Not on public holidays or their eves\. Next: label:2099-11-07, Eve of Deepavali\./);
assert.match(book, /<strong>Best time to look:<\/strong> weekday mornings/);
assert.match(book, /Open dates run to label:2026-11-30\./);
const [summary, details] = book.split("<details");
assert.ok(!summary.includes("<svg"), "charts stay behind the toggle");
assert.match(details, /tft-week-strip/);
assert.match(details, /<svg viewBox/);
assert.equal((book.match(/tft-panel-title/g) || []).length, 1, "one heading for all booking timing");
context.state.tableForTwoInsights = stale;
assert.match(context.tableForTwoWhenToBookHtml(colony), /terms changed since our last review\. Check blackouts/);
context.state.tableForTwoInsights = insights;
assert.match(context.tableForTwoWhenToBookHtml({ id: "unknown" }), /Days and meals are not published/);
console.log("tft insights UI ok");
