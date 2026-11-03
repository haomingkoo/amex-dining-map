#!/usr/bin/env node
// The venue panel keeps a few pill actions; Telegram and reference links sit in quiet text rows.
const assert = require("node:assert/strict");
const fs = require("node:fs");

const source = fs.readFileSync("web/app.js", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");
const start = source.indexOf('<div class="focus-actions">', source.indexOf("const centurionBookingUrl"));
const block = source.slice(start, source.indexOf("`;", start));
const pills = block.slice(0, block.indexOf("</div>"));

// 1. Pills are only booking, menus and Maps.
assert.match(pills, /Centurion booking page/);
assert.match(pills, /\$\{menuPdfLinks\}/);
assert.match(pills, /Google Maps/);
for (const label of ["DiningCity", "Official list", "T&Cs", "Telegram", "Center on map"]) {
  assert.doesNotMatch(pills, new RegExp(label), `${label} is still a pill`);
}
// 2. One DiningCity link replaces the public page and profile pair.
assert.doesNotMatch(block, /Public DiningCity page|DiningCity profile/);
assert.equal((block.match(/>DiningCity<\/a>/g) || []).length, 1);
// 3. Telegram actions share one text row.
assert.match(block, /<div class="tft-link-row">[\s\S]*Ask on Telegram[\s\S]*Set Telegram reminder[\s\S]*?<\/div>/);
// 4. Reference links sit in the quiet row, with the map button.
const quiet = block.slice(block.indexOf('tft-link-row is-quiet'));
for (const label of [">DiningCity<", "Official list", "T&Cs PDF", "data-tft-focus-map"]) {
  assert.ok(quiet.includes(label), `${label} missing from the quiet row`);
}
// 5. Text rows have a visible focus ring and are not hidden on phones.
assert.match(css, /\.tft-link-row a:focus-visible,\s*\.tft-link-row button:focus-visible/);
assert.ok(!/\.tft-link-row(\.is-quiet)?\s*[,{][^}]*display:\s*none/.test(css), "a link row is hidden");

console.log("TFT detail actions verification passed");
