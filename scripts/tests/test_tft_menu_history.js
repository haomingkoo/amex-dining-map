#!/usr/bin/env node
// The venue panel shows how this card's menu changed, newest first, with the saved PDF of each version.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const source = fs.readFileSync("web/app.js", "utf8");
const context = {
  state: { tableForTwoMenuHistory: null },
  escapeHtml: (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
};
vm.runInNewContext(
  `${["tableForTwoLongDate", "tableForTwoMenuVersions", "tableForTwoMenuHistoryHtml"].map((name) => extractFunction(source, name)).join("\n")}
Object.assign(globalThis, { tableForTwoMenuVersions, tableForTwoMenuHistoryHtml });`,
  context,
);

const sha = (c) => c.repeat(64);
const version = (c, first, last, extra = {}) => ({
  sha256: sha(c), first_seen: first, last_seen: last, archive_path: `menu-archive/${sha(c)}.pdf`, changes: null, ...extra,
});
context.state.tableForTwoMenuHistory = { venues: { "tft-vineyard": {
  platinum: [
    { ...version("a", "2026-04-27T00:00:00Z", "2026-04-27T00:00:00Z"), archive_path: null },
    version("b", "2026-07-04T00:00:00Z", "2026-11-02T00:00:00Z"),
    version("c", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z", { changes: { added: ["Red Prawn Tartare"], removed: ["Blue Swimmer Crab <Rémoulade>"] } }),
  ],
  centurion: [version("d", "2026-07-04T00:00:00Z", "2026-11-03T00:00:00Z")],
} } };
const vineyard = { id: "tft-vineyard" };

// 1. Newest version first.
assert.deepEqual(Array.from(context.tableForTwoMenuVersions(vineyard, "platinum"), (v) => v.sha256[0]), ["c", "b", "a"]);
// 2. A card with one version has no history to show.
assert.equal(context.tableForTwoMenuHistoryHtml(vineyard, "centurion"), "");
assert.equal(context.tableForTwoMenuHistoryHtml({ id: "tft-unknown" }, "platinum"), "");
const html = context.tableForTwoMenuHistoryHtml(vineyard, "platinum");
// 3. Collapsed by default, with the change date in the summary.
assert.match(html, /<details class="tft-menu-history">\s*<summary>Menu changed 2 Nov 2026<\/summary>/);
// 4. Added and removed dishes are listed, escaped.
assert.match(html, /Added[\s\S]*Red Prawn Tartare/);
assert.match(html, /Removed[\s\S]*Blue Swimmer Crab &lt;Rémoulade>/);
// 5. Every saved version links to our archived PDF.
assert.equal((html.match(/href="\.\.\/menu-archive\/[0-9a-f]{64}\.pdf"/g) || []).length, 2);
// 6. Missing PDFs and missing diffs are stated, not hidden.
assert.match(html, /PDF not saved/);
assert.match(html, /earlier PDF was not saved, so the changes cannot be shown/i);
// 7. Dates read as a range, and the current one says so.
assert.match(html, /Current, since 2 Nov 2026/);
assert.match(html, /4 Jul 2026 to 2 Nov 2026/);
// 8. History loads with the rest of the Table for Two data and is rendered in the panel.
assert.match(source, /TABLE_FOR_TWO_MENU_HISTORY_URL = "\.\.\/data\/tft-menu-history\.json"/);
assert.match(extractFunction(source, "ensureTableForTwoDataLoaded"), /state\.tableForTwoMenuHistory = /);
assert.match(source, /\$\{tableForTwoMenuHistoryHtml\(record, tableForTwoDisplayTier\(record\)\)\}/);
// 9. No em dashes in the copy.
assert.doesNotMatch(extractFunction(source, "tableForTwoMenuHistoryHtml"), /—/);

console.log("TFT menu history verification passed");
