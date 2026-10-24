#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const app = fs.readFileSync("web/app.js", "utf8");
const names = [
  "tftAlertDateSelectable",
  "tftAlertAddDays",
  "tftAlertShiftMonth",
  "tftAlertClampDates",
  "tftAlertToggleDate",
  "tftAlertQuickPick",
];
const context = {};
vm.runInNewContext(`${names.map((name) => extractFunction(app, name)).join("\n")}\nObject.assign(globalThis, { ${names.join(", ")} });`, context);
const range = { from: "2026-11-01", to: "2026-11-30", today: "2026-11-05" };

// Only days inside the range and not before Singapore today are selectable.
assert.equal(context.tftAlertDateSelectable("2026-11-10", range), true);
assert.equal(context.tftAlertDateSelectable("2026-11-30", range), true);
assert.equal(context.tftAlertDateSelectable("2026-12-01", range), false);
assert.equal(context.tftAlertDateSelectable("2026-11-04", range), false);
assert.equal(context.tftAlertDateSelectable("2026-11-10", { ...range, to: "" }), false);

// Narrowing the range drops out-of-range days and keeps the rest sorted.
assert.deepEqual(
  [...context.tftAlertClampDates(["2026-11-20", "2026-11-03", "2026-12-02", "2026-11-08"], range)],
  ["2026-11-08", "2026-11-20"],
);

// Month and day arithmetic crosses year boundaries.
assert.equal(context.tftAlertAddDays("2026-12-31", 1), "2027-01-01");
assert.equal(context.tftAlertShiftMonth("2026-12", 1), "2027-01");
assert.equal(context.tftAlertShiftMonth("2027-01", -1), "2026-12");

// Toggling adds sorted, removes on repeat, and refuses past the cap.
assert.deepEqual([...context.tftAlertToggleDate(["2026-11-20"], "2026-11-10", 31).dates], ["2026-11-10", "2026-11-20"]);
assert.deepEqual([...context.tftAlertToggleDate(["2026-11-10"], "2026-11-10", 31).dates], []);
const full = context.tftAlertToggleDate(["2026-11-10", "2026-11-11"], "2026-11-12", 2);
assert.equal(full.limited, true);
assert.deepEqual([...full.dates], ["2026-11-10", "2026-11-11"]);

// Weekend quick pick skips past days: 2026-11-01 (Sun) is before today.
assert.deepEqual(
  [...context.tftAlertQuickPick(range, [0, 6], 31).dates],
  ["2026-11-07", "2026-11-08", "2026-11-14", "2026-11-15", "2026-11-21", "2026-11-22", "2026-11-28", "2026-11-29"],
);
assert.deepEqual([...context.tftAlertQuickPick(range, [5, 6], 31).dates].slice(0, 2), ["2026-11-06", "2026-11-07"]);

// Quick picks respect the cap and report truncation.
const capped = context.tftAlertQuickPick({ from: "2026-11-05", to: "2027-03-01", today: "2026-11-05" }, [0, 6], 31);
assert.equal(capped.dates.length, 31);
assert.equal(capped.limited, true);
assert.equal(context.tftAlertQuickPick(range, [0, 6], 31).limited, false);

console.log("alert form date calendar tests passed");
