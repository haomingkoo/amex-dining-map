#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");
const start = source.indexOf("function tableForTwoVenueIdFromHash(");
const end = source.indexOf("\nfunction ", start + 10);
assert.ok(start >= 0 && end > start, "deep-link parser not found");

const context = { URLSearchParams };
vm.runInNewContext(
  `${source.slice(start, end)}\nthis.parseVenue = tableForTwoVenueIdFromHash;`,
  context,
);

assert.equal(context.parseVenue("#/table-for-two?venue=tft-vue"), "tft-vue");
assert.equal(
  context.parseVenue("#/table-for-two?venue=tft-15-stamford-restaurant"),
  "tft-15-stamford-restaurant",
);
assert.equal(context.parseVenue("#/table-for-two?venue=../../etc/passwd"), null);
assert.equal(context.parseVenue("#/table-for-two?venue=amex-global-singapore-vue"), null);
assert.equal(context.parseVenue("#/table-for-two"), null);

const filtersStart = source.indexOf("function tableForTwoFiltersFromHash(");
const filtersEnd = source.indexOf("\nfunction ", filtersStart + 10);
assert.ok(filtersStart >= 0 && filtersEnd > filtersStart, "filter deep-link parser not found");
const filtersContext = { URLSearchParams, Date };
vm.runInNewContext(
  `${source.slice(filtersStart, filtersEnd)}\nthis.parseFilters = tableForTwoFiltersFromHash;`,
  filtersContext,
);
assert.deepEqual(
  JSON.parse(JSON.stringify(filtersContext.parseFilters(
    "#/table-for-two?venue=tft-vue&party=2&meal=dinner&date=2026-10-29&time=19:00&day=weekday",
  ))),
  { party: "2", session: "Dinner", date: "2026-10-29", time: "19:00", day: "weekday" },
);
assert.deepEqual(
  JSON.parse(JSON.stringify(filtersContext.parseFilters(
    "#/table-for-two?party=99&meal=breakfast&date=2026-02-30&time=19:17&day=holiday",
  ))),
  { party: "", session: "", date: "", time: "", day: "" },
);

assert.match(
  source,
  /setActiveTableForTwoRecord\(linkedVenueId, \{ scrollDetails: true \}\)/,
  "valid deep link does not select and reveal the venue",
);
assert.match(
  source,
  /currentRoute\?\.programId === requestedRoute\?\.programId[\s\S]*window\.location\.hash/,
  "intro gate does not preserve a matching deep-link route and its parameters",
);
assert.match(source, /payload\.menu_source\?\.review_required/);
assert.match(source, /Some menu details are being verified/);
assert.match(source, /A possible menu change is being verified/);
assert.match(source, /applyTableForTwoFiltersFromHash\(\);[\s\S]*refreshTableForTwoDateOptions\(\);/);

const reviewStart = source.indexOf("function tableForTwoVenueMenuReviewItems(");
const reviewEnd = source.indexOf("\nfunction ", reviewStart + 10);
assert.ok(reviewStart >= 0 && reviewEnd > reviewStart, "venue review helper not found");
const reviewContext = {};
vm.runInNewContext(
  `${source.slice(reviewStart, reviewEnd)}\nthis.reviewItems = tableForTwoVenueMenuReviewItems;`,
  reviewContext,
);
const reviewPayload = {
  menu_source: {
    review_queue: [
      { venue_id: "tft-one-ninety" },
      { candidate_venue_id: "tft-osteria-mozza" },
      { candidate_venue_ids: ["tft-a", "tft-b"] },
    ],
  },
};
assert.equal(reviewContext.reviewItems(reviewPayload, { id: "tft-vue" }).length, 0);
assert.equal(reviewContext.reviewItems(reviewPayload, { id: "tft-one-ninety" }).length, 1);
assert.equal(reviewContext.reviewItems(reviewPayload, { id: "tft-osteria-mozza" }).length, 1);
assert.equal(reviewContext.reviewItems(reviewPayload, { id: "tft-b" }).length, 1);
assert.match(source, /A possible menu change is being verified/);
assert.match(source, /We could not verify an official menu for this venue/);

console.log("Table for Two deep-link verification passed");
