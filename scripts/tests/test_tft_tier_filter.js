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
  "tableForTwoBotServesVenue",
  "tableForTwoHasTierData",
  "tableForTwoPublishedMenus",
  "tableForTwoTierNote",
  "tableForTwoDisplayTier",
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

// Email alert venues follow the card the member signs up with.
assert.deepEqual(Array.from(tiers.tableForTwoAlertVenueNames()), ["Sarnies", "VUE"]);
assert.deepEqual(Array.from(tiers.tableForTwoAlertVenueNames("centurion")), ["JAAN By Kirk Westaway", "VUE"]);

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
    `${["tableForTwoVenueTiers", "tableForTwoBotServesVenue", "tableForTwoTierNote", "tableForTwoDisplayTier", "tableForTwoSlotMatchesHtml"].map((name) => extractFrom(source, name)).join("\n")}\nglobalThis.render = tableForTwoSlotMatchesHtml;`,
    context,
  );
  const jaanHtml = context.render(tiered[2], {});
  assert.match(jaanHtml, /Centurion slots not tracked yet/);
  assert.doesNotMatch(jaanHtml, /Source check pending/);
  assert.match(context.render(tiered[1], {}), /Availability not checked yet/);
}
console.log("TFT tier availability box verification passed");

// Under the Centurion filter, shared venues must not present Platinum seats as Centurion's.
{
  const context = { state: {}, tableForTwoTierFilter: { value: "centurion" } };
  vm.runInNewContext(
    `${["tableForTwoVenueTiers", "tableForTwoTierNote", "tableForTwoDisplayTier", "tableForTwoBotServesVenue"].map((name) => extractFrom(source, name)).join("\n")}\nObject.assign(globalThis, { tableForTwoTierNote, tableForTwoBotServesVenue });`,
    context,
  );
  assert.equal(context.tableForTwoTierNote(tiered[0]), "Centurion slots are not tracked yet.");
  assert.equal(context.tableForTwoBotServesVenue(tiered[0]), true);
  assert.equal(context.tableForTwoBotServesVenue(tiered[2]), false);
  context.tableForTwoTierFilter.value = "platinum";
  assert.equal(context.tableForTwoTierNote(tiered[0]), "");
}
console.log("TFT Centurion filter availability verification passed");

// Untracked Centurion slots get a neutral pill and no Platinum date line.
{
  const vue = { ...tiered[0], availability: { visible_dates: ["2026-11-06", "2026-12-07"] } };
  const context = {
    state: {},
    tableForTwoTierFilter: { value: "centurion" },
    tableForTwoAvailabilityKey: () => "available",
    tableForTwoMatchingSlots: () => [{ date: "2026-11-06" }],
    uniqueValues: (values) => [...new Set(values)],
    tableForTwoDateRangeSummary: (dates) => `${dates.length} dates`,
  };
  vm.runInNewContext(
    `${["tableForTwoVenueTiers", "tableForTwoTierNote", "tableForTwoDisplayTier", "tableForTwoBotServesVenue", "tableForTwoAvailabilityBadgeClass", "tableForTwoDateSummary"].map((name) => extractFrom(source, name)).join("\n")}\nObject.assign(globalThis, { tableForTwoAvailabilityBadgeClass, tableForTwoDateSummary });`,
    context,
  );
  assert.equal(context.tableForTwoAvailabilityBadgeClass(vue, {}), "");
  assert.equal(context.tableForTwoDateSummary(vue, {}), "");
  context.tableForTwoTierFilter.value = "platinum";
  assert.equal(context.tableForTwoAvailabilityBadgeClass(vue, {}), "green");
  assert.equal(context.tableForTwoDateSummary(vue, {}), "1 dates");
}
console.log("TFT untracked tier display verification passed");

// Centurion slots from Railway replace the untracked note under the Centurion view.
{
  const fns = [
    "tableForTwoVenueTiers", "tableForTwoBotServesVenue", "tableForTwoDisplayTier",
    "tableForTwoSelectTierAvailability", "tableForTwoTierNote", "tableForTwoSlotSnapshotIsValid",
    "tableForTwoAvailabilityFromSlotVenue", "applyTableForTwoCenturionSnapshot", "tableForTwoCenturionBookingUrl",
  ];
  const platAvailability = { status: "live_available", project: "AMEXPlatSG", meals: [] };
  const venues = [
    { id: "tft-vue", name: "VUE", dining_city_id: "205194014", tiers: ["platinum", "centurion"], availability: platAvailability },
    { id: "tft-jaan", name: "JAAN", dining_city_id: "205189592", tiers: ["centurion"] },
  ];
  const context = {
    state: { tableForTwo: { venues } },
    tableForTwoTierFilter: { value: "" },
    tableForTwoSearchText: () => "",
  };
  vm.runInNewContext(
    `${fns.map((name) => extractFrom(source, name)).join("\n")}\nObject.assign(globalThis, { ${fns.join(", ")} });`,
    context,
  );
  const [vue, jaan] = venues;
  assert.equal(context.tableForTwoDisplayTier(vue), "platinum");
  assert.equal(context.tableForTwoDisplayTier(jaan), "centurion");
  context.tableForTwoTierFilter.value = "centurion";
  assert.equal(context.tableForTwoDisplayTier(vue), "centurion");

  const meals = [{ meal: "Lunch", status: "available", slots: [{ date: "2026-11-06", time: "11:45", max_seats: 4 }] }];
  const snapshot = {
    schema_version: 1, source_project: "AMEXCentSG", generated_at: "2026-11-02T14:00:00Z",
    refresh_status: "success", counts: { eligible: 2, succeeded: 2, failed: 0, retained: 0 },
    venues: [
      { id: "tft-jaan", project: "AMEXCentSG", status: "live_available", checked_at: "2026-11-02T14:00:00Z", attempted_at: "2026-11-02T14:00:00Z", result: "fresh", error_code: null, meals },
      { id: "tft-vue", project: "AMEXCentSG", status: "live_no_seats", checked_at: "2026-11-02T14:00:00Z", attempted_at: "2026-11-02T14:00:00Z", result: "fresh", error_code: null, meals: [] },
    ],
  };
  assert.equal(context.tableForTwoTierNote(jaan), "Centurion slots are not tracked yet.");
  assert.equal(context.applyTableForTwoCenturionSnapshot({ ...snapshot, source_project: "AMEXPlatSG" }), false);
  assert.equal(context.applyTableForTwoCenturionSnapshot(snapshot), true);

  context.tableForTwoSelectTierAvailability();
  assert.equal(vue.availability.project, "AMEXCentSG");
  assert.equal(vue.availability.status, "live_no_seats");
  assert.equal(jaan.availability.meals[0].slots[0].time, "11:45");
  assert.equal(context.tableForTwoTierNote(vue), "");
  assert.equal(context.tableForTwoTierNote(jaan), "");

  context.tableForTwoTierFilter.value = "platinum";
  context.tableForTwoSelectTierAvailability();
  assert.equal(vue.availability, platAvailability);
  assert.equal(context.tableForTwoBotServesVenue(jaan), false);

  assert.equal(
    context.tableForTwoCenturionBookingUrl(jaan),
    "https://partner.diningcity.asia/profile?program=AMEXCentSG&region_id=120&restaurant_id=205189592&lang=en",
  );
}
console.log("TFT Centurion live slots verification passed");

// Clean-up: per-card counts, the Centurion booking label, and the linked-only note.
{
  const fns = [
    "tableForTwoPayload", "tableForTwoVenueTiers", "tableForTwoVenues", "tableForTwoBotServesVenue",
    "tableForTwoDisplayTier", "tableForTwoPublishedMenus", "tableForTwoMenuGap", "tableForTwoMenuMetaLabel",
    "tableForTwoTierCountsLabel", "tableForTwoLinkedOnlyNote",
  ];
  const venues = [
    ...tiered,
    { id: "zyx", name: "Zui Yu Xuan", booking_project_status: "active", tiers: ["platinum", "centurion"], tier_membership: { centurion: "linked_only" } },
  ];
  const context = { state: { tableForTwo: { venues } }, tableForTwoTierFilter: { value: "" }, TABLE_FOR_TWO_TIER_LABELS: { platinum: "Platinum", centurion: "Centurion" } };
  vm.runInNewContext(
    `${fns.map((name) => extractFrom(source, name)).join("\n")}\nObject.assign(globalThis, { ${fns.join(", ")} });`,
    context,
  );
  assert.equal(context.tableForTwoTierCountsLabel(), "3 Platinum · 3 Centurion venues");
  assert.match(context.tableForTwoMenuMetaLabel(venues[0]), /Amex app$/);
  assert.match(context.tableForTwoMenuMetaLabel(venues[2]), /Centurion booking page$/);
  assert.equal(context.tableForTwoLinkedOnlyNote(venues[4]), "");
  context.tableForTwoTierFilter.value = "centurion";
  assert.match(context.tableForTwoMenuMetaLabel(venues[0]), /Centurion booking page$/);
  assert.match(context.tableForTwoLinkedOnlyNote(venues[4]), /not on the Centurion venue list/);
  assert.equal(context.tableForTwoLinkedOnlyNote(venues[0]), "");
}
console.log("TFT tier clean-up verification passed");
