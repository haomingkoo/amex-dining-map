#!/usr/bin/env node
// Card tiers on the TFT view: Centurion-only venues show, filter, and stay out of Platinum alerts.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");
const { extractFunction: extractFrom } = require("./extract_function");
const names = [
  "tableForTwoPayload",
  "tableForTwoVenueTiers",
  "tableForTwoVenues",
  "tableForTwoNotListedVenues",
  "tableForTwoAlertVenueNames",
  "tableForTwoTierMatches",
  "tableForTwoHasTierData",
  "tableForTwoPublishedMenus",
  "tableForTwoTierNote",
  "tableForTwoIsEarlierListing",
];

function load(venues) {
  const context = { state: { tableForTwo: { venues } } };
  vm.runInNewContext(
    `${names.map((name) => extractFrom(source, name)).join("\n")}\nObject.assign(globalThis, { ${names.join(", ")} });`,
    context,
  );
  return context;
}

const menu = (card, label) => ({ status: "published", url: `https://example.test/${card}.pdf`, label, card });
const tiered = [
  { id: "shared", name: "VUE", booking_project_status: "active", tiers: ["platinum", "centurion"],
    menu_pdfs: { platinum: menu("platinum", "Platinum"), centurion: menu("centurion", "Centurion") } },
  { id: "plat", name: "Sarnies", booking_project_status: "active", tiers: ["platinum"] },
  { id: "jaan", name: "JAAN By Kirk Westaway", booking_project_status: "not_listed", tiers: ["centurion"] },
  { id: "gone", name: "Kuriya Dining", booking_project_status: "not_listed", tiers: [] },
];
const ids = (records) => Array.from(records, (record) => record.id);

const tiers = load(tiered);
assert.deepEqual(ids(tiers.tableForTwoVenues()), ["shared", "plat", "jaan"]);
assert.deepEqual(ids(tiers.tableForTwoNotListedVenues()), ["gone"]);
assert.equal(tiers.tableForTwoHasTierData(), true);

const shown = (tier) => ids(tiers.tableForTwoVenues().filter((record) => tiers.tableForTwoTierMatches(record, tier)));
assert.deepEqual(shown(""), ["shared", "plat", "jaan"]);
assert.deepEqual(shown("platinum"), ["shared", "plat"]);
assert.deepEqual(shown("centurion"), ["shared", "jaan"]);

// Email alerts are Platinum-only until registration names a tier (Phase 3).
assert.deepEqual(Array.from(tiers.tableForTwoAlertVenueNames()), ["Sarnies", "VUE"]);

const vue = tiered[0];
assert.equal(tiers.tableForTwoPublishedMenus(vue, "centurion")[0].url, "https://example.test/centurion.pdf");
assert.equal(tiers.tableForTwoPublishedMenus(vue, "platinum")[0].url, "https://example.test/platinum.pdf");
assert.equal(tiers.tableForTwoPublishedMenus(vue).length, 2);

assert.equal(tiers.tableForTwoTierNote(tiered[2]), "Centurion slots are not tracked yet.");
// The focus card's "Earlier listing" layout is for venues no card can book.
assert.equal(tiers.tableForTwoIsEarlierListing(tiered[2]), false);
assert.equal(tiers.tableForTwoIsEarlierListing(tiered[3]), true);
assert.doesNotMatch(source, /if \(record\.booking_project_status === "not_listed"\) \{/);
assert.equal(tiers.tableForTwoTierNote(vue), "");

// A catalog from before card tiers keeps today's behaviour and hides the filter.
const legacy = load([
  { id: "active", name: "Sarai", booking_project_status: "active" },
  { id: "not-listed", name: "Osteria Mozza", booking_project_status: "not_listed" },
  { id: "unknown", name: "Legacy Venue" },
]);
assert.deepEqual(ids(legacy.tableForTwoVenues()), ["active", "unknown"]);
assert.deepEqual(ids(legacy.tableForTwoNotListedVenues()), ["not-listed"]);
assert.equal(legacy.tableForTwoHasTierData(), false);
assert.equal(legacy.tableForTwoTierMatches(legacy.tableForTwoVenues()[0], "centurion"), true);

assert.match(source, /id="tft-tier-filter"|getElementById\("tft-tier-filter"\)/);

console.log("TFT tier filter verification passed");

// The focus card's availability box explains untracked Centurion slots.
{
  const context = {
    state: {},
    escapeHtml: (value) => String(value),
    tableForTwoMatchingSlots: () => [],
    tableForTwoAvailabilityKey: () => "unknown",
    tableForTwoBestAvailabilityLine: () => "Source check pending.",
  };
  vm.runInNewContext(
    `${["tableForTwoVenueTiers", "tableForTwoTierNote", "tableForTwoSlotMatchesHtml"].map((name) => extractFrom(source, name)).join("\n")}\nglobalThis.render = tableForTwoSlotMatchesHtml;`,
    context,
  );
  const jaanHtml = context.render(tiered[2], {});
  assert.match(jaanHtml, /Centurion slots not tracked yet/);
  assert.doesNotMatch(jaanHtml, /Source check pending/);
  assert.match(context.render(tiered[1], {}), /Availability not checked yet/);
}
console.log("TFT tier availability box verification passed");
