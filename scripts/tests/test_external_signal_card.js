#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");
const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

const context = {
  escapeHtml: (value) => String(value),
  formatSourceDate: (value) => value,
};
vm.runInNewContext(
  ["sourceConfidenceLabel", "formatReviewCount", "externalSignalCard"].map(extractFunction).join("\n") +
    "\nObject.assign(globalThis, { externalSignalCard });",
  context,
);

const card = context.externalSignalCard("tabelog", {
  honest_stars: 4.5,
  score_raw: 3.75,
  review_count: 649,
  match_confidence: "auto_verified_86",
  last_checked_at: "2026-10-07",
  notes: "Auto-matched: phone_exact, district_match",
  url: "https://tabelog.com/aichi/A2301/A230106/23000001/",
});
// Same score the desktop panel shows; matcher codes and notes are internal.
assert.match(card, />3\.75 on Tabelog</);
assert.match(card, /649 reviews/);
assert.doesNotMatch(card, /honest stars|raw 3\.75|auto_verified|Auto-matched|phone_exact/);

const verified = context.externalSignalCard("tabelog", { score_raw: 3.6, match_confidence: "manual_verified" });
assert.match(verified, /Verified listing/);

console.log("external signal card verification passed");
