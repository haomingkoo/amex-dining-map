#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("web/app.js", "utf8");

assert.match(
  app,
  /function renderTable\(\) \{\s*if \(!state\.tableOpen\) \{\s*resultsTableBody\.replaceChildren\(\);\s*return;/,
  "the detailed table must not build thousands of hidden rows while closed",
);
assert.match(
  app,
  /function setTableOpen\(isOpen\)[\s\S]*if \(isOpen\) \{\s*renderTable\(\);\s*\} else \{\s*resultsTableBody\.replaceChildren\(\);/,
  "opening must render the table and closing must release its DOM",
);

console.log("Lazy dining table verification passed");
