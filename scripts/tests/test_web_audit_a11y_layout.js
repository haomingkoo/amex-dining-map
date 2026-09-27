#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("web/app.js", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");

function extractFunction(name) {
  const start = app.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `Missing ${name}`);
  const bodyStart = app.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < app.length; index += 1) {
    if (app[index] === "{") depth += 1;
    if (app[index] === "}") depth -= 1;
    if (depth === 0) return app.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const names = ["tableForTwoYearSuffix", "tableForTwoDateOptionLabel", "tableForTwoShortDate", "tableForTwoDateRangeSummary"];
// Pin "today" so the year rule is deterministic.
class FixedDate extends Date {
  constructor(...args) {
    super(...(args.length ? args : ["2026-09-27T00:00:00Z"]));
  }
}
const context = { Date: FixedDate, uniqueValues: (values) => [...new Set(values)] };
vm.runInNewContext(`${names.map(extractFunction).join("\n")}\nObject.assign(globalThis, { ${names.join(", ")} });`, context);

// A current-year date reads as a formatted day only, with no raw ISO prefix.
assert.equal(context.tableForTwoDateOptionLabel("2026-11-26"), "Thu, 26 Nov");
assert.equal(context.tableForTwoDateRangeSummary(["2026-11-26"]), "Thu, 26 Nov");

// Dates in another year carry the year, so ranges across New Year stay clear.
assert.equal(context.tableForTwoDateOptionLabel("2027-01-05"), "Tue, 05 Jan 2027");
assert.equal(
  context.tableForTwoDateRangeSummary(["2026-12-20", "2027-01-05"]),
  "2 dates · 20 Dec to 05 Jan 2027",
);

// The TFT card drops its meta date when the availability line already opens with it.
const renderList = extractFunction("renderTableForTwoList");
assert.match(renderList, /availabilityLine\.startsWith\(dateSummary\)/);

// Plat Stay and dining rows share one keyboard helper and one focus style.
const keyboardRow = extractFunction("makeRowKeyboardOperable");
assert.match(keyboardRow, /row\.tabIndex = 0/);
assert.match(keyboardRow, /event\.key !== "Enter" && event\.key !== " "/);
for (const [renderer, body] of [["renderStayTable", "staysResultsTableBody"], ["renderTable", "resultsTableBody"]]) {
  const source = extractFunction(renderer);
  assert.match(source, /makeRowKeyboardOperable\(row\)/);
  // Any rebuild, including late data refreshes, keeps keyboard focus on the active row.
  assert.match(source, new RegExp(`refocusActiveRow\\(${body}, hadRowFocus\\)`));
}
assert.match(css, /\.keyboard-row:focus-visible/);

// Route changes bring the active tab into the scrolling phone tab strip.
assert.match(extractFunction("renderProgramShell"), /scrollIntoView\(\{ block: "nearest", inline: "nearest" \}\)/);

// The alert form offers every meal type the reminders backend accepts.
for (const meal of ["Lunch", "Dinner", "All-day Dining", "Afternoon Tea"]) {
  assert.match(html, new RegExp(`name="session" value="${meal}"`));
}

console.log("web audit a11y layout tests passed");
