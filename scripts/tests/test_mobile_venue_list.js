#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");

const css = fs.readFileSync("web/styles.css", "utf8");

// Phones hide the full table, so the card list is the only way to reach venues without a map pin.
assert.match(css, /\.table-shell \{\s*display: none !important;/);
const phoneRules = [...css.matchAll(/@media \(max-width: 820px\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]);
assert.ok(phoneRules.length > 0);
phoneRules.forEach((rules) => {
  assert.doesNotMatch(rules, /\n  \.mobile-results-panel \{\s*display: none;/);
});
assert.ok(phoneRules.some((rules) => /\n  \.mobile-results-panel \{\s*display: block;/.test(rules)));

console.log("mobile venue list verification passed");
