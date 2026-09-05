#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");

const helpersStart = app.indexOf("const PUBLIC_UPDATE_KINDS");
const helpersEnd = app.indexOf("\nfunction updateValueLabel", helpersStart);
assert.ok(helpersStart >= 0 && helpersEnd > helpersStart, "public update helpers not found");

const context = { Set, String, Boolean, Array };
vm.runInNewContext(
  `${app.slice(helpersStart, helpersEnd)}
   this.isPublicDecisionUpdate = isPublicDecisionUpdate;
   this.isPrimaryPublicUpdate = isPrimaryPublicUpdate;
   this.updateKindLabel = updateKindLabel;
   this.updateKindBadgeLabel = updateKindBadgeLabel;
   this.publicUpdateChanges = publicUpdateChanges;
   this.publicUpdateSummary = publicUpdateSummary;`,
  context,
);

assert.equal(context.isPublicDecisionUpdate({ status: "published", kind: "added" }), true);
assert.equal(context.isPublicDecisionUpdate({ status: "published", kind: "menu_updated" }), true);
assert.equal(context.isPublicDecisionUpdate({ status: "published", kind: "source_recovered" }), false);
assert.equal(context.isPublicDecisionUpdate({ status: "published", kind: "source_stale" }), false);
assert.equal(context.isPublicDecisionUpdate({ status: "review_required", kind: "menu_updated" }), false);
assert.equal(context.isPrimaryPublicUpdate({ kind: "added" }), true);
assert.equal(context.isPrimaryPublicUpdate({ kind: "menu_updated" }), true);
assert.equal(context.isPrimaryPublicUpdate({ kind: "correction" }), false);

// A venue the source renamed must reach readers as a rename, not vanish from the feed.
assert.equal(context.isPublicDecisionUpdate({ status: "published", kind: "renamed" }), true);
assert.equal(context.isPrimaryPublicUpdate({ kind: "renamed" }), true);
assert.equal(context.updateKindBadgeLabel("renamed"), "Renamed");
assert.equal(context.updateKindLabel("renamed"), "Restaurant renamed");
assert.equal(
  context.updateKindLabel("renamed", { program_id: "plat-stay" }),
  "Property renamed",
);
assert.equal(
  context.publicUpdateSummary([{ kind: "renamed" }, { kind: "renamed" }, { kind: "added" }]),
  "1 restaurant added · 2 venues renamed",
);
assert.equal(context.publicUpdateSummary([{ kind: "renamed" }]), "1 venue renamed");

assert.equal(
  context.publicUpdateSummary([
    { kind: "added" },
    { kind: "added" },
    { kind: "removed" },
    { kind: "menu_updated" },
  ]),
  "2 restaurants added · 1 restaurant removed · 1 menu changed",
);
assert.equal(
  context.publicUpdateSummary([
    { kind: "added", program_id: "plat-stay" },
    { kind: "removed", program: "Plat Stay" },
  ]),
  "1 property added · 1 property removed",
);

const semanticMenuChanges = context.publicUpdateChanges({
  kind: "menu_updated",
  changes: [
    { field: "Main choices", before: "Cod", after: "Barramundi" },
    { field: "Menu version", before: "abc123", after: "def456" },
    { field: "Platinum menu version", before: "abc123", after: "def456" },
  ],
});
assert.deepEqual(JSON.parse(JSON.stringify(semanticMenuChanges)), [
  { field: "Main choices", before: "Cod", after: "Barramundi" },
]);

const fallbackMenuChanges = context.publicUpdateChanges({
  kind: "menu_updated",
  changes: [
    { field: "Menu file", before: "old.pdf", after: "new.pdf" },
    { field: "Menu version", before: "abc123", after: "def456" },
  ],
});
assert.deepEqual(JSON.parse(JSON.stringify(fallbackMenuChanges)), [{
  field: "Official menu",
  before: "Previous reviewed menu",
  after: "Updated reviewed menu",
}]);

assert.match(html, />What's new</);
assert.match(html, /<h2 id="updates-history-title">Confirmed changes<\/h2>/);
assert.match(html, /<details class="updates-secondary" id="updates-secondary" hidden>/);
assert.match(html, />Other confirmed corrections</);
assert.match(html, /<details class="source-health" id="source-health" hidden>/);
assert.ok(
  html.indexOf('id="updates-history"') < html.indexOf('id="source-health"'),
  "confirmed changes must appear before data freshness",
);
assert.doesNotMatch(html, /<details class="source-health"[^>]*\sopen(?:\s|>)/);
assert.match(html, /<strong>Data freshness<\/strong>/);
assert.match(html, /It does not explain why/);

const shellStart = app.indexOf("function renderUpdatesShell(");
const shellEnd = app.indexOf("\nfunction readUpdatesTimestamp", shellStart);
const shellSource = app.slice(shellStart, shellEnd);
assert.match(shellSource, /publicUpdateSummary\(unread\)/);
assert.match(shellSource, /unreadUpdates\(\)\.filter\(isPrimaryPublicUpdate\)/);
assert.doesNotMatch(shellSource, /healthAttention|need attention/);
assert.match(shellSource, /updatesCount\.hidden = unread\.length === 0/);
assert.match(app, /\.filter\(isPublicDecisionUpdate\)/);
assert.match(app, /const secondary = published\.filter\(\(update\) => !isPrimaryPublicUpdate\(update\)\)/);
assert.match(app, /Some availability or rating information may be older than usual/);
assert.match(app, /Some venue or benefit information is being verified/);
assert.match(app, /Availability may be outdated/);
assert.doesNotMatch(app, /stale source check/);

assert.match(css, /\.source-health-summary-row[\s\S]*min-height: 56px/);
assert.match(css, /\.source-health-summary-row:focus-visible/);
assert.match(css, /\.updates-secondary > summary[\s\S]*min-height: 48px/);
assert.match(css, /\.updates-headline[\s\S]*-webkit-line-clamp: 2/);

console.log("Public updates UI verification passed");
