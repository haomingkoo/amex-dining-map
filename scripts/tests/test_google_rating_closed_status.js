#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const app = fs.readFileSync("web/app.js", "utf8");
const today = new Date().toISOString().slice(0, 10);
const ratings = {
  open: { rating: 4.5, review_count: 10, scraped_at: today },
  closed: { rating: null, review_count: null, status: "permanently_closed", scraped_at: today },
};
const context = { state: { googleRatings: ratings }, GOOGLE_RATING_ID_ALIASES: {}, GOOGLE_RATING_STALE_DAYS: 90, Date, Number };
vm.runInNewContext(
  `${extractFunction(app, "googleRating")}\n${extractFunction(app, "googleRatingForRanking")}\nglobalThis.ranked = googleRatingForRanking;`,
  context,
);

assert.equal(context.ranked({ id: "open" }).rating, 4.5);
// A closed venue keeps its entry but must not count as rated.
assert.equal(context.ranked({ id: "closed" }), null);

console.log("google rating closed status tests passed");
