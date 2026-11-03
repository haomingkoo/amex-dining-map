#!/usr/bin/env node
// Platinum and Centurion seats are separate; the card switch picks one and cards show both.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const source = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");

const slot = (date, time, seats = 10) => ({ date, time, max_seats: seats });
const open = (slots) => ({ status: "live_available", meals: [{ meal: "Lunch", slots }] });
const closed = { status: "live_no_seats", meals: [] };

const context = {
  state: { tableForTwoCenturionById: new Map() },
  escapeHtml: (value) => String(value),
  tableForTwoAvailabilityFromSlotVenue: (venue) => ({ status: venue.status, meals: venue.meals }),
  tableForTwoMatchingSlots: (record, filters = {}) => (record.availability.status === "live_available"
    ? record.availability.meals.flatMap((meal) => meal.slots).filter((s) => s.max_seats >= (filters.partySize || 2))
    : []),
  tableForTwoAvailabilityKey: (record, filters) => {
    if (record.availability.status === "live_no_seats") return "no_seats";
    if (record.availability.status !== "live_available") return "unknown";
    return context.tableForTwoMatchingSlots(record, filters).length ? "available" : "no_seats";
  },
};
vm.runInNewContext(
  `${["tableForTwoTierSeatText", "tableForTwoTierSeatRows", "tableForTwoTierSeatsHtml"].map((name) => extractFunction(source, name)).join("\n")}
Object.assign(globalThis, { tableForTwoTierSeatRows, tableForTwoTierSeatsHtml });`,
  context,
);

const vue = { id: "tft-vue", tiers: ["platinum", "centurion"], availability: closed, availability_platinum: closed };
context.state.tableForTwoCenturionById.set("tft-vue", open([slot("2026-11-10", "12:00"), slot("2026-11-10", "12:30"), slot("2026-11-11", "12:00", 3)]));

// 1. Both cards listed side by side, Platinum first.
const rows = context.tableForTwoTierSeatRows(vue, {});
assert.deepEqual(Array.from(rows, (row) => row.tier), ["platinum", "centurion"]);
// 2. Closed Platinum reads "No seats" and is not marked open.
assert.equal(rows[0].text, "No seats");
assert.equal(rows[0].open, false);
// 3. Centurion counts times and distinct dates.
assert.equal(rows[1].text, "3 times over 2 dates");
assert.equal(rows[1].open, true);
// 4. Party size filters both counts.
assert.equal(context.tableForTwoTierSeatRows(vue, { partySize: 4 })[1].text, "2 times on 1 date");
// 5. Single-card venues get no comparison.
assert.deepEqual(Array.from(context.tableForTwoTierSeatRows({ id: "x", tiers: ["centurion"] }, {})), []);
// 6. Untracked Centurion seats say so rather than borrowing Platinum's.
const untracked = context.tableForTwoTierSeatRows({ id: "nope", tiers: ["platinum", "centurion"], availability_platinum: closed }, {});
assert.equal(untracked[1].text, "Not tracked yet");
// 7. The selected card is marked in the markup.
const markup = context.tableForTwoTierSeatsHtml(vue, {}, "centurion");
assert.match(markup, /is-selected[^>]*>\s*<dt>Centurion/);
assert.match(markup, /<dd class="is-open">3 times over 2 dates<\/dd>/);

// 8. The switch sits in the map panel head, outside the Refine drawer.
const head = html.slice(html.indexOf("<h2>Table for Two map</h2>"), html.indexOf('id="tft-map-filter-shell"'));
assert.match(head, /id="tft-card-switch"/);
assert.match(head, /data-tier="platinum"[^>]*aria-pressed/);
assert.match(head, /data-tier="centurion"[^>]*aria-pressed/);
// 9. The card is not a filter: Clear filters keeps it and the filter count ignores it.
assert.doesNotMatch(extractFunction(source, "tableForTwoActiveFilterCount"), /tableForTwoTierFilter/);
const reset = source.slice(source.indexOf("tableForTwoResetFiltersBtn.addEventListener"), source.indexOf("introSkipTopButton?.addEventListener"));
assert.doesNotMatch(reset, /tableForTwoTierFilter/);
// 10. The choice is remembered per browser.
assert.match(source, /TABLE_FOR_TWO_CARD_STORAGE_KEY/);

console.log("TFT card switch verification passed");

// Menus follow the selected card; a missing card menu is said plainly, never swapped silently.
{
  const tier = { value: "platinum" };
  const menuContext = { tableForTwoTierFilter: tier, TABLE_FOR_TWO_TIER_LABELS: { platinum: "Platinum", centurion: "Centurion" } };
  vm.runInNewContext(
    `${["tableForTwoVenueTiers", "tableForTwoBotServesVenue", "tableForTwoDisplayTier", "tableForTwoPublishedMenus", "tableForTwoMenuGap", "tableForTwoMenuMetaLabel"].map((name) => extractFunction(source, name)).join("\n")}
Object.assign(globalThis, { tableForTwoMenuGap, tableForTwoMenuMetaLabel });`,
    menuContext,
  );
  const pdf = (label) => ({ status: "published", url: `https://example.test/${label}.pdf`, label });
  const both = { tiers: ["platinum", "centurion"], menu_pdfs: { platinum: pdf("Platinum"), centurion: pdf("Centurion") } };
  const platOnly = { tiers: ["platinum", "centurion"], menu_pdfs: { platinum: pdf("Platinum") } };
  const buffet = { tiers: ["platinum", "centurion"], menu_pdf: { status: "buffet_no_menu_expected" } };

  // 11. The list card names the selected card's menu, not a count of both.
  assert.equal(menuContext.tableForTwoMenuMetaLabel(both), "Platinum menu · Amex app");
  tier.value = "centurion";
  assert.equal(menuContext.tableForTwoMenuMetaLabel(both), "Centurion menu · Centurion booking page");
  // 12. Only the other card's menu exists: say the selected card's menu is missing.
  assert.equal(menuContext.tableForTwoMenuMetaLabel(platOnly), "No Centurion menu yet · Centurion booking page");
  assert.equal(menuContext.tableForTwoMenuGap(platOnly), "centurion");
  assert.equal(menuContext.tableForTwoMenuGap(both), "");
  // 13. Buffets and venues with no menus at all get no gap note.
  assert.equal(menuContext.tableForTwoMenuGap(buffet), "");
  assert.equal(menuContext.tableForTwoMenuMetaLabel(buffet), "Centurion booking page");
  tier.value = "platinum";
  assert.equal(menuContext.tableForTwoMenuGap(platOnly), "");
}
// 14. The detail panel explains the gap next to the menu links.
assert.match(source, /No \$\{escapeHtml\(gapLabel\)\} menu found yet/);
console.log("TFT card menu verification passed");
