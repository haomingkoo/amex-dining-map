#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");

function extractFunction(name) {
  const start = app.indexOf(`function ${name}(`);
  const end = app.indexOf("\nfunction ", start + 10);
  assert.ok(start >= 0 && end > start, `${name} helper not found`);
  return app.slice(start, end);
}

const context = { Date, Number };
vm.runInNewContext(
  `${extractFunction("sourceHealthDisplayState")}
   ${extractFunction("sourceHealthCoverageLabel")}
   ${extractFunction("sourceHealthPublicSummary")}
   this.displayState = sourceHealthDisplayState;
   this.coverageLabel = sourceHealthCoverageLabel;
   this.publicSummary = sourceHealthPublicSummary;`,
  context,
);

const now = Date.parse("2026-08-30T12:00:00Z");
assert.equal(context.displayState({
  status: "current",
  last_success_at: "2026-08-30T11:30:00Z",
  stale_after_minutes: 60,
}, now).key, "current");
assert.equal(context.displayState({
  status: "current",
  last_success_at: "2026-08-30T10:30:00Z",
  stale_after_minutes: 60,
}, now).key, "stale", "runtime age must override a stored current status");
assert.equal(context.displayState({
  status: "current",
  last_attempt_outcome: "failed",
  last_success_at: "2026-08-30T11:30:00Z",
  stale_after_minutes: 60,
  retained_snapshot: true,
}, now).key, "failed");
assert.equal(context.displayState({
  status: "current",
  review_required: true,
  last_success_at: "2026-08-30T11:30:00Z",
  stale_after_minutes: 60,
}, now).key, "review");
assert.equal(context.displayState({
  state: "mixed_age",
  checked_at: "2026-08-30T11:30:00Z",
  stale_after_hours: 1,
}, now).label, "May be outdated");
assert.equal(
  context.coverageLabel({ current: 18, total: 23, stale: 2, missing: 1, failed: 2 }),
  "18 of 23 checked recently · 2 older checks · 1 not found · 2 checks unavailable",
);
assert.equal(
  context.coverageLabel({ covered: 781, total: 825, unavailable: 44 }),
  "781 of 825 available · 44 unavailable",
);
assert.equal(context.publicSummary([{
  tier: "primary",
  status: "review_required",
  review_required: true,
}]), "Some venue or benefit information is being verified.");
assert.equal(context.publicSummary([{
  tier: "enrichment",
  status: "stale",
  checked_at: "2026-08-30T11:30:00Z",
}]), "Some availability or rating information may be older than usual.");

assert.match(html, /id="source-health"[\s\S]*id="source-health-groups"/);
assert.match(html, /Official programme sources define venue and benefit information/);
assert.match(html, /<details class="source-health" id="source-health" hidden>/);
assert.match(app, /SOURCE_HEALTH_DATA_URL = "\.\.\/data\/source-health\.json"/);
assert.match(app, /\["primary", "Official programme information"/);
assert.match(app, /\["enrichment", "Availability and ratings"/);
assert.match(app, /source\.tier \|\| source\.kind/);
assert.match(app, /Showing the last verified information/);
assert.match(app, /Last checked successfully \$\{formatTimestamp\(success\)\}/);
assert.match(app, /updatesShell\.hidden = !hasUpdates && !hasHealth/);
assert.match(css, /\.source-health-row-head[\s\S]*minmax\(0, 1fr\)/);
assert.match(css, /\.source-health-row h4[\s\S]*overflow-wrap: anywhere/);
assert.match(css, /\.source-health-links a[\s\S]*min-height: 44px/);

console.log("Source health UI verification passed");
