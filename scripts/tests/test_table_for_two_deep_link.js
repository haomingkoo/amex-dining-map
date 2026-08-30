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

assert.match(
  source,
  /setActiveTableForTwoRecord\(linkedVenueId, \{ scrollDetails: true \}\)/,
  "valid deep link does not select and reveal the venue",
);

console.log("Table for Two deep-link verification passed");
