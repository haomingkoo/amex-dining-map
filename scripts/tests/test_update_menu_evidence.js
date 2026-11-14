#!/usr/bin/env node
// A "Menu changed" entry in What's new shows what actually changed, from the saved menu history.
// It never shows placeholder labels as if they were content.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const app = fs.readFileSync("web/app.js", "utf8");
const PLACEHOLDERS = /Previous reviewed menu|Updated reviewed menu/;

// 1. The placeholder strings are gone from the app.
assert.doesNotMatch(app, PLACEHOLDERS);

const context = {
  escapeHtml: (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
};
vm.runInNewContext(
  `${[
    "tableForTwoLongDate",
    "isNoOpMenuUpdate",
    "menuUpdateVersions",
    "findMenuHistoryVersion",
    "menuUpdateEvidenceHtml",
  ].map((name) => extractFunction(app, name)).join("\n")}
   Object.assign(globalThis, { isNoOpMenuUpdate, menuUpdateVersions, findMenuHistoryVersion, menuUpdateEvidenceHtml });`,
  context,
);

const sha = (c) => c.repeat(64);
const history = { venues: { "tft-vue": { centurion: [
  { sha256: sha("a"), first_seen: "2026-07-04T00:00:00Z", last_seen: "2026-11-02T00:00:00Z", archive_path: `menu-archive/${sha("a")}.pdf`, changes: null },
  { sha256: sha("b"), first_seen: "2026-11-02T16:00:00Z", last_seen: "2026-11-14T00:00:00Z", archive_path: `menu-archive/${sha("b")}.pdf`,
    changes: { added: ["Grilled White Asparagus", "Banana <Mocha>"], removed: ["Holland White Asparagus"] } },
] } } };
const menuUpdate = (before, after, extra = {}) => ({
  kind: before === "Not published" ? "menu_added" : "menu_updated",
  status: "published",
  subject: "VUE · Centurion menu",
  source_url: "https://www.americanexpress.com/vue.pdf",
  before: { fields: { "Menu file": "VUE.pdf", "Menu version": before } },
  after: { fields: { "Menu file": "VUE.pdf", "Menu version": after } },
  changes: [
    { field: "Menu file", before: "VUE.pdf", after: "VUE.pdf" },
    { field: "Menu version", before, after },
  ],
  ...extra,
});

// 2. A real change lists the dishes added and removed, escaped, with both saved PDFs.
const updated = context.menuUpdateEvidenceHtml(menuUpdate("aaaaaaaaaaaa", "bbbbbbbbbbbb"), history);
assert.match(updated, /Added[\s\S]*Grilled White Asparagus/);
assert.match(updated, /Banana &lt;Mocha&gt;/);
assert.match(updated, /Removed[\s\S]*Holland White Asparagus/);
assert.match(updated, new RegExp(`href="\\.\\./menu-archive/${sha("a")}\\.pdf"[^>]*>Previous menu`));
assert.match(updated, new RegExp(`href="\\.\\./menu-archive/${sha("b")}\\.pdf"[^>]*>New menu`));
assert.match(updated, /In use since 2 Nov 2026/);
assert.doesNotMatch(updated, PLACEHOLDERS);

// 3. A first menu says so and links the saved PDF; it does not invent a "before".
const added = context.menuUpdateEvidenceHtml(menuUpdate("Not published", "aaaaaaaaaaaa"), history);
assert.match(added, /First menu published for this card/);
assert.match(added, new RegExp(`menu-archive/${sha("a")}\\.pdf`));
assert.doesNotMatch(added, /Removed/);

// 4. A previous version we never saved is stated plainly, with the current menu still linked.
const unrecorded = context.menuUpdateEvidenceHtml(menuUpdate("cccccccccccc", "bbbbbbbbbbbb"), history);
assert.match(unrecorded, /previous menu was not recorded/i);
assert.match(unrecorded, new RegExp(`menu-archive/${sha("b")}\\.pdf`));
assert.doesNotMatch(unrecorded, /Grilled White Asparagus/, "a diff against another version must not be shown");

// 5. Unreadable PDFs: say so and point to both saved menus.
const noDiff = { venues: { "tft-vue": { centurion: [history.venues["tft-vue"].centurion[0], { ...history.venues["tft-vue"].centurion[1], changes: null }] } } };
assert.match(context.menuUpdateEvidenceHtml(menuUpdate("aaaaaaaaaaaa", "bbbbbbbbbbbb"), noDiff), /could not be read/i);

// 6. A version missing from the history, or history that failed to load, still links the official menu.
const missing = context.menuUpdateEvidenceHtml(menuUpdate("aaaaaaaaaaaa", "dddddddddddd"), history);
assert.match(missing, /was not saved/);
assert.match(missing, /href="https:\/\/www\.americanexpress\.com\/vue\.pdf"/);
assert.match(context.menuUpdateEvidenceHtml(menuUpdate("aaaaaaaaaaaa", "bbbbbbbbbbbb"), null), /could not be loaded[\s\S]*americanexpress/);

// 7. A menu field that only moved (same file, same bytes, now also listed under "Menu") is not a change.
const relabel = {
  kind: "menu_updated",
  status: "published",
  before: { fields: { "Centurion menu file": "Lerouy.pdf", "Centurion menu version": "62adc69e0ad8" } },
  after: { fields: { "Menu file": "Lerouy.pdf", "Menu version": "62adc69e0ad8", "Centurion menu file": "Lerouy.pdf", "Centurion menu version": "62adc69e0ad8" } },
  changes: [
    { field: "Menu file", before: null, after: "Lerouy.pdf" },
    { field: "Menu version", before: null, after: "62adc69e0ad8" },
  ],
};
assert.equal(context.isNoOpMenuUpdate(relabel), true);
assert.equal(context.isNoOpMenuUpdate(menuUpdate("aaaaaaaaaaaa", "bbbbbbbbbbbb")), false);
assert.equal(context.isNoOpMenuUpdate(menuUpdate("Not published", "aaaaaaaaaaaa")), false);
assert.equal(context.isNoOpMenuUpdate({ kind: "added", changes: [] }), false);
// 8. Such entries are kept out of the public feed and its counts.
assert.match(extractFunction(app, "isPublicDecisionUpdate"), /!isNoOpMenuUpdate\(update\)/);

// 9. Every published menu entry in the real data renders real evidence and no placeholder.
const updates = JSON.parse(fs.readFileSync("data/updates.json", "utf8")).updates;
const realHistory = JSON.parse(fs.readFileSync("data/tft-menu-history.json", "utf8"));
const menuEntries = updates.filter((update) => update.status === "published" && String(update.kind).startsWith("menu_"));
assert.ok(menuEntries.length > 0);
for (const update of menuEntries.filter((entry) => !context.isNoOpMenuUpdate(entry))) {
  const out = context.menuUpdateEvidenceHtml(update, realHistory);
  assert.doesNotMatch(out, PLACEHOLDERS, update.subject);
  assert.match(out, /href="(\.\.\/menu-archive\/[0-9a-f]{64}\.pdf|https:\/\/)/, `${update.subject} has no menu link`);
}

// 10. Menu history loads on demand when a menu entry is opened from any page.
assert.match(extractFunction(app, "renderUpdateRow"), /ensureMenuHistoryLoaded\(\)/);

console.log("update menu evidence verification passed");
