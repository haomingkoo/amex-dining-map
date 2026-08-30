#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("web/app.js", "utf8");

const applyRoute = app.slice(
  app.indexOf("async function applyRoute(routeId)"),
  app.indexOf("function handleHashRoute()"),
);
assert.doesNotMatch(
  applyRoute,
  /ensureTableForTwoLiveRefresh\(/,
  "opening TFT must not fan out a whole-roster browser scrape",
);

const auxiliaryRerender = app.slice(
  app.indexOf("function rerenderCurrentRouteAfterAuxiliaryData()"),
  app.indexOf("async function loadGoogleRatings"),
);
assert.doesNotMatch(
  auxiliaryRerender,
  /filterRestaurants\(|filterStays\(|filterLoveDining\(|filterTableForTwo\(/,
  "late ratings must not rebuild every map marker",
);

assert.match(app, /const SEARCH_DEBOUNCE_MS = 200;/);
assert.match(
  app,
  /searchInput\.addEventListener\("input", \(\) => \{[\s\S]*window\.setTimeout\([\s\S]*filterRestaurants\(\)[\s\S]*SEARCH_DEBOUNCE_MS/,
  "broad dining search must be debounced",
);

console.log("Frontend work-budget verification passed");
