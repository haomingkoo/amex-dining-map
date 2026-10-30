#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const { extractFunction } = require("./extract_function");

const source = fs.readFileSync("web/app.js", "utf8");
const context = {};
vm.runInNewContext(
  `${extractFunction(source, "stayRangeOverlaps")}\nglobalThis.stayRangeOverlaps = stayRangeOverlaps;`,
  context,
);
const stay = (from, to) => ({ start: new Date(`${from}T00:00:00Z`), end: new Date(`${to}T00:00:00Z`) });
const annual = (start_month_day, end_month_day) => ({ recurring: "annual", start_month_day, end_month_day });

// Annual ranges apply in whichever year the stay falls.
assert.strictEqual(context.stayRangeOverlaps(annual("11-07", "12-10"), stay("2027-11-20", "2027-11-22")), true);
assert.strictEqual(context.stayRangeOverlaps(annual("11-07", "12-10"), stay("2031-12-11", "2031-12-13")), false);
// A range across New Year blocks both sides of 1 January.
assert.strictEqual(context.stayRangeOverlaps(annual("12-28", "01-03"), stay("2028-01-02", "2028-01-04")), true);
assert.strictEqual(context.stayRangeOverlaps(annual("12-28", "01-03"), stay("2027-12-30", "2027-12-31")), true);
assert.strictEqual(context.stayRangeOverlaps(annual("12-28", "01-03"), stay("2028-01-04", "2028-01-06")), false);
// Dated ranges are unchanged; the end date is inclusive.
assert.strictEqual(context.stayRangeOverlaps({ start: "2026-12-24", end: "2026-12-26" }, stay("2026-12-26", "2026-12-27")), true);
assert.strictEqual(context.stayRangeOverlaps({ start: "2026-12-24", end: "2026-12-26" }, stay("2027-12-24", "2027-12-25")), false);
console.log("stay blackout range tests passed");
