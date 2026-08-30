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
   this.displayState = sourceHealthDisplayState;
   this.coverageLabel = sourceHealthCoverageLabel;`,
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
}, now).label, "Mixed age");
assert.equal(
  context.coverageLabel({ current: 18, total: 23, stale: 2, missing: 1, failed: 2 }),
  "18 of 23 current · 2 stale · 1 missing · 2 failed",
);
assert.equal(
  context.coverageLabel({ covered: 781, total: 825, unavailable: 44 }),
  "781 of 825 covered · 44 unavailable",
);

assert.match(html, /id="source-health"[\s\S]*id="source-health-groups"/);
assert.match(html, /Primary sources define the explorer/);
assert.match(app, /SOURCE_HEALTH_DATA_URL = "\.\.\/data\/source-health\.json"/);
assert.match(app, /\["primary", "Primary sources"/);
assert.match(app, /\["enrichment", "Enrichment sources"/);
assert.match(app, /source\.tier \|\| source\.kind/);
assert.match(app, /Last verified snapshot retained/);
assert.match(app, /Last successful check \$\{formatTimestamp\(success\)\}/);
assert.match(app, /updatesShell\.hidden = !hasUpdates && !hasHealth/);
assert.match(css, /\.source-health-row-head[\s\S]*minmax\(0, 1fr\)/);
assert.match(css, /\.source-health-row h4[\s\S]*overflow-wrap: anywhere/);
assert.match(css, /\.source-health-links a[\s\S]*min-height: 44px/);

console.log("Source health UI verification passed");
