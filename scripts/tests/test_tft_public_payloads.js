#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("web/app.js", "utf8");

assert.match(
  app,
  /TABLE_FOR_TWO_RELEASE_HISTORY_URL = "\.\.\/data\/table-for-two-release-history-summary\.json"/,
);
assert.match(
  app,
  /TABLE_FOR_TWO_RELEASE_HISTORY_FALLBACK_URL = "\.\.\/data\/table-for-two-release-history\.json"/,
);
assert.match(
  app,
  /TABLE_FOR_TWO_GOOGLE_RATINGS_URL = "\.\.\/data\/google-maps-ratings-table-for-two\.json"/,
);

const routeLoader = app.slice(
  app.indexOf("async function ensureRouteDataLoaded"),
  app.indexOf("function renderRouteLoadingState"),
);
assert.match(
  routeLoader,
  /isTableForTwoRoute\(route\)[\s\S]*loadTableForTwoGoogleRatings\(\{ refreshCurrentRoute: true \}\)/,
  "TFT must load the bounded ratings projection",
);

const tftRatingsLoader = app.slice(
  app.indexOf("async function loadTableForTwoGoogleRatings"),
  app.indexOf("function currentRouteNeedsGoogleRatings"),
);
assert.match(tftRatingsLoader, /fetchJson\(TABLE_FOR_TWO_GOOGLE_RATINGS_URL\)/);
assert.match(
  tftRatingsLoader,
  /fetchJson\(TABLE_FOR_TWO_GOOGLE_RATINGS_URL\)[\s\S]*\|\| await fetchJson\(GOOGLE_RATINGS_URL\)/,
  "the global ratings file is only a local/deployment fallback",
);

console.log("TFT public-payload verification passed");
