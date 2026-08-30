#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "web/app.js"), "utf8");

function functionSource(name) {
  const signature = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const match = signature.exec(source);
  assert.ok(match, `missing function ${name}`);
  const start = match.index;
  const parametersStart = source.indexOf("(", match.index);
  let parameterDepth = 0;
  let parametersEnd = -1;
  for (let index = parametersStart; index < source.length; index += 1) {
    if (source[index] === "(") parameterDepth += 1;
    if (source[index] === ")") parameterDepth -= 1;
    if (parameterDepth === 0) {
      parametersEnd = index;
      break;
    }
  }
  const bodyStart = source.indexOf("{", parametersEnd);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated function ${name}`);
}

const diningLoader = functionSource("ensureDiningDataLoaded");
assert.doesNotMatch(diningLoader, /POCKET_AVAILABILITY_URL/, "core Dining load must not fetch Pocket availability");
for (const url of ["DATA_URL", "JAPAN_META_URL", "GLOBAL_DATA_URL", "GLOBAL_META_URL"]) {
  assert.match(diningLoader, new RegExp(`fetchJson\\(${url}\\)`), `core Dining load must retain ${url}`);
}

const routeLoader = functionSource("ensureRouteDataLoaded");
assert.match(routeLoader, /currentRouteNeedsPocketAvailability\(route\)[\s\S]*await ensurePocketAvailabilityLoaded\(\)/);
assert.match(routeLoader, /shouldLoadGoogleRatingsInBackground\(route\)/);

const routeHelpers = new Function(
  "isDiningRoute",
  "diningFiltersNeedPocketAvailability",
  `${functionSource("isJapanDiningRoute")}\n${functionSource("currentRouteNeedsPocketAvailability")}\nreturn { isJapanDiningRoute, currentRouteNeedsPocketAvailability };`,
)(() => true, () => false);
assert.equal(routeHelpers.isJapanDiningRoute({ id: "dining/japan" }), true);
assert.equal(routeHelpers.isJapanDiningRoute({ id: "dining/japan/top" }), true);
assert.equal(routeHelpers.isJapanDiningRoute({ id: "dining/world" }), false);
assert.equal(routeHelpers.currentRouteNeedsPocketAvailability({ id: "dining/world" }), false,
  "default world must not load Pocket without an explicit filter");
assert.equal(routeHelpers.currentRouteNeedsPocketAvailability({ id: "dining/japan" }), true,
  "Japan must load Pocket before filtering and rendering");

const backgroundRatingsHelper = new Function(
  "isLiveDataRoute",
  "isDiningRoute",
  "isJapanDiningRoute",
  "isTableForTwoRoute",
  `${functionSource("shouldLoadGoogleRatingsInBackground")}\nreturn shouldLoadGoogleRatingsInBackground;`,
)(
  () => true,
  (route) => route.id.startsWith("dining/"),
  (route) => ["dining/japan", "dining/japan/top"].includes(route.id),
  (route) => route.id === "table-for-two",
);
assert.equal(backgroundRatingsHelper({ id: "dining/world" }), false,
  "default world must not start ratings as an automatic background load");
assert.equal(backgroundRatingsHelper({ id: "dining/japan" }), true,
  "Japan must retain its background ratings enrichment");
assert.equal(backgroundRatingsHelper({ id: "table-for-two" }), false,
  "TFT uses its bounded ratings projection instead of the global payload");
assert.equal(backgroundRatingsHelper({ id: "stays/world" }), true,
  "non-Dining routes must retain their background ratings enrichment");

const activeRecord = functionSource("setActiveRecord");
assert.match(activeRecord, /loadGoogleRatings\(\{ refreshCurrentRoute: true \}\)/,
  "selecting a venue must opt in to ratings loading");
assert.match(activeRecord, /activeRecord\?\.country === "Japan"[\s\S]*ensurePocketAvailabilityLoaded\(\{ refreshCurrentRoute: true \}\)/,
  "selecting a Japan venue must opt in to Pocket loading");

const ratingHandler = functionSource("applyDiningRatingFilter");
assert.match(ratingHandler, /currentRouteNeedsGoogleRatings\(\)[\s\S]*await loadGoogleRatings\(\)[\s\S]*filterRestaurants\(\)/);

const pocketHandler = functionSource("applyPocketFilter");
assert.match(pocketHandler, /diningFiltersNeedPocketAvailability\(\)[\s\S]*await ensurePocketAvailabilityLoaded\(\)[\s\S]*filterRestaurants\(\)/);

console.log("deferred Dining auxiliary data checks passed");
