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

const names = ["tableForTwoDateOptionLabel", "tableForTwoShortDate", "tableForTwoDateRangeSummary"];
const context = { uniqueValues: (values) => [...new Set(values)] };
vm.runInNewContext(`${names.map(extractFunction).join("\n")}\nObject.assign(globalThis, { ${names.join(", ")} });`, context);

// A single date reads as a formatted day only, with no raw ISO prefix.
assert.equal(context.tableForTwoDateOptionLabel("2026-11-26"), "Thu, 26 Nov");
assert.equal(context.tableForTwoDateRangeSummary(["2026-11-26"]), "Thu, 26 Nov");

// The TFT card drops its meta date when the availability line already opens with it.
const renderList = extractFunction("renderTableForTwoList");
assert.match(renderList, /availabilityLine\.startsWith\(dateSummary\)/);

// Plat Stay rows are focusable and operable with Enter or Space.
const stayTable = extractFunction("renderStayTable");
assert.match(stayTable, /row\.tabIndex = 0/);
assert.match(stayTable, /event\.key !== "Enter" && event\.key !== " "/);
assert.match(css, /#stays-results-table-body tr:focus-visible/);

// Route changes bring the active tab into the scrolling phone tab strip.
assert.match(extractFunction("renderProgramShell"), /scrollIntoView\(\{ block: "nearest", inline: "nearest" \}\)/);

// The alert form offers every meal type the reminders backend accepts.
for (const meal of ["Lunch", "Dinner", "All-day Dining", "Afternoon Tea"]) {
  assert.match(html, new RegExp(`name="session" value="${meal}"`));
}

console.log("web audit a11y layout tests passed");
