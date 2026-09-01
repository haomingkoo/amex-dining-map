#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");

assert.match(
  html,
  /<details class="tft-freshness-details" id="tft-freshness-details">[\s\S]*<summary>Data sources &amp; freshness<\/summary>/,
  "freshness disclosure must exist and be closed by default",
);
assert.doesNotMatch(
  html,
  /<details class="tft-freshness-details"[^>]*\sopen(?:\s|>)/,
  "freshness disclosure must not be open by default",
);

const filterStart = app.indexOf("function filterTableForTwo(");
const filterEnd = app.indexOf("\nfunction tableForTwoActiveFilterCount", filterStart);
const filterSource = app.slice(filterStart, filterEnd);
assert.ok(filterStart >= 0 && filterEnd > filterStart, "Table for Two filter renderer not found");
assert.doesNotMatch(filterSource, /Availability checked \$\{formatTimestamp/);
assert.doesNotMatch(filterSource, /Roster checked \$\{formatTimestamp/);
assert.doesNotMatch(filterSource, /Official menu index checked/);
assert.match(filterSource, /availability check\$\{staleCaptureCount === 1/);
assert.match(filterSource, /availability check\$\{pendingCount === 1/);

const listStart = app.indexOf("function renderTableForTwoList(");
const listEnd = app.indexOf("\nfunction renderTableForTwoCard", listStart);
const listSource = app.slice(listStart, listEnd);
assert.ok(listStart >= 0 && listEnd > listStart, "Table for Two list renderer not found");
assert.doesNotMatch(listSource, /tableForTwoFreshnessLabel\(record\)/);
assert.match(listSource, /dateSummary === "Availability may be outdated" \? "" : dateSummary/);
assert.match(listSource, /card\.setAttribute\("role", "button"\)/);
assert.match(listSource, /card\.setAttribute\("tabindex", "0"\)/);
assert.match(listSource, /card\.setAttribute\("aria-controls", "tft-focus-card"\)/);
assert.match(listSource, /event\.key !== "Enter" && event\.key !== " "/);
assert.match(listSource, /focusDetails: true/);

const cardStart = app.indexOf("function renderTableForTwoCard(");
const cardEnd = app.indexOf("\nfunction ", cardStart + 10);
const cardSource = app.slice(cardStart, cardEnd);
assert.doesNotMatch(cardSource, /<span class="focus-label">Refreshed<\/span>/);
assert.doesNotMatch(cardSource, /Official menu index checked/);
assert.match(cardSource, /sourceReviewWarning/);

assert.match(css, /\.tft-freshness-details > summary[\s\S]*min-height: 44px/);
assert.match(css, /\.tft-freshness-details > summary:focus-visible/);
assert.match(css, /\.tft-card:focus-visible/);
assert.match(css, /\.tft-freshness-row[\s\S]*overflow-wrap: anywhere/);

console.log("Table for Two freshness UI verification passed");
