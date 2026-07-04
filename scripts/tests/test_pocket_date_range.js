#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const functionNames = [
  "uniqueValues",
  "pocketAvailabilityRecord",
  "pocketDateSummaries",
  "pocketHasCheckedSlots",
  "normalizePocketDateRange",
  "pocketDateRangeIsActive",
  "dateWithinPocketRange",
  "datesHavePocketRangeMatch",
  "setPocketDateRangeInput",
  "pocketPartyRangeMatches",
  "pocketSessionMatches",
  "pocketSummaryMatches",
  "pocketReservationDateMatchesUnknownDetails",
  "pocketAvailabilityMatches",
  "pocketSeatingLabel",
  "filterJapanRankings",
];

const context = {
  pocketDateFilter: { value: "" },
  pocketDateEndFilter: { value: "" },
  pocketPartySizeValue: () => 0,
  pocketSessionFilter: { value: "" },
  japanRankValue: (record) => record.score || 0,
  tabelogReviewCount: (record) => record.reviews || 0,
  isMobileRankView: () => false,
};
vm.runInNewContext(
  `${functionNames.map(extractFunction).join("\n")}\nObject.assign(globalThis, { ${functionNames.join(", ")} });`,
  context,
);

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

assert.deepStrictEqual(
  plain(context.normalizePocketDateRange("2026-07-10", "2026-07-08")),
  { start: "2026-07-08", end: "2026-07-10" },
);
assert.deepStrictEqual(
  plain(context.normalizePocketDateRange("2026-07-10", "")),
  { start: "2026-07-10", end: "2026-07-10" },
);

context.setPocketDateRangeInput("start", "2026-07-10");
assert.strictEqual(context.pocketDateFilter.value, "2026-07-10");
assert.strictEqual(context.pocketDateEndFilter.value, "2026-07-10");
context.setPocketDateRangeInput("end", "2026-07-08");
assert.strictEqual(context.pocketDateFilter.value, "2026-07-08");
assert.strictEqual(context.pocketDateEndFilter.value, "2026-07-08");

const record = {
  country: "Japan",
  pocket_availability: {
    reservation_dates: ["2026-07-02", "2026-07-05", "2026-09-10"],
    waitlist_dates: ["2026-07-09"],
    dates: {
      "2026-07-05": {
        sessions: ["DINNER"],
        party_ranges: [[2, 4]],
      },
    },
  },
};

assert.strictEqual(context.pocketAvailabilityMatches(record, "", "2026-07-01", "2026-07-04", 0, ""), true);
assert.strictEqual(context.pocketAvailabilityMatches(record, "", "2026-07-03", "", 0, ""), false);
assert.strictEqual(context.pocketPartyRangeMatches({ party_ranges: [[1, 2]] }, 2), true);
assert.strictEqual(context.pocketSeatingLabel({ seating: ["COUNTER", "PRIVATE_ROOM", "NONE"] }), "Counter, Private Room");
assert.strictEqual(context.pocketAvailabilityMatches(record, "", "2026-07-05", "", 3, "dinner"), true);
assert.strictEqual(context.pocketAvailabilityMatches(record, "", "2026-07-05", "", 5, "dinner"), false);
assert.strictEqual(context.pocketAvailabilityMatches(record, "bookable", "2026-09-10", "2026-09-17", 2, ""), true);
assert.strictEqual(context.pocketAvailabilityMatches(record, "bookable", "2026-09-10", "2026-09-17", 2, "dinner"), false);
assert.strictEqual(context.pocketAvailabilityMatches(record, "slots", "2026-07-05", "", 0, ""), true);
assert.strictEqual(context.pocketAvailabilityMatches(record, "slots", "2026-07-02", "", 0, ""), true);
assert.strictEqual(context.pocketAvailabilityMatches(record, "waitlist", "2026-07-08", "2026-07-10", 0, ""), true);

context.pocketDateFilter.value = "";
context.pocketDateEndFilter.value = "";
context.state = {
  japanRankAvailability: "",
  japanRankPrefecture: "Tokyo",
  japanRankCity: "Tokyo",
  japanRankDistrict: "Shibuya",
  japanRankCuisine: "Sushi",
  japanRankLunchBand: "5k-10k",
  japanRankDinnerBand: "10k-20k",
  japanRankMenu: "yes",
  japanRankReservation: "Request booking",
  japanRankPage: 1,
  japanRankPageSize: 25,
  japanRankTotal: 0,
  filtered: [],
  scopeRecords: [
    {
      id: "match",
      name: "A",
      country: "Japan",
      prefecture: "Tokyo",
      city: "Tokyo",
      district: "Shibuya",
      cuisines: ["Sushi"],
      price_lunch_band_key: "5k-10k",
      price_dinner_band_key: "10k-20k",
      english_menu: true,
      reservation_type: "Request booking",
      score: 4.1,
      reviews: 100,
    },
    {
      id: "wrong-menu",
      name: "B",
      country: "Japan",
      prefecture: "Tokyo",
      city: "Tokyo",
      district: "Shibuya",
      cuisines: ["Sushi"],
      price_lunch_band_key: "5k-10k",
      price_dinner_band_key: "10k-20k",
      english_menu: false,
      reservation_type: "Request booking",
      score: 4.2,
      reviews: 100,
    },
    {
      id: "wrong-area",
      name: "C",
      country: "Japan",
      prefecture: "Tokyo",
      city: "Tokyo",
      district: "Ginza",
      cuisines: ["Sushi"],
      price_lunch_band_key: "5k-10k",
      price_dinner_band_key: "10k-20k",
      english_menu: true,
      reservation_type: "Request booking",
      score: 4.3,
      reviews: 100,
    },
  ],
};
context.filterJapanRankings();
assert.deepStrictEqual(context.state.filtered.map((item) => item.id), ["match"]);
