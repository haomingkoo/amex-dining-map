#!/usr/bin/env node
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";

const evidencePath = "docs/evidence/tft-browser-production.json";
assert.ok(fs.existsSync(evidencePath), "production browser evidence is missing");
const evidence = JSON.parse(fs.readFileSync(evidencePath, "utf8"));

assert.equal(evidence.schema_version, 1);
assert.equal(evidence.site_url, "https://amex-explorer.kooexperience.com/");
assert.equal(evidence.route, "#/table-for-two?venue=tft-vue");
assert.equal(evidence.selected_venue_id, "tft-vue");
assert.equal(evidence.console_error_count, 0);
assert.deepEqual(evidence.unhandled_failed_page_resources, []);
assert.equal(evidence.expected_handled_diningcity_404_count, 2);
assert.equal(evidence.api_key_watermark_visible, false);
assert.equal(evidence.reminder_form_visible, true);
assert.match(evidence.app_sha256, /^[0-9a-f]{64}$/);
for (const size of ["390x844", "320x740"]) {
  assert.equal(evidence.viewports[size].horizontal_overflow, false, `${size} has horizontal overflow`);
  assert.deepEqual(evidence.viewports[size].overflow_offenders, [], `${size} has clipped descendants`);
}
assert.deepEqual(evidence.tile_hosts, ["tile.openstreetmap.de"]);
assert.ok(evidence.loaded_tile_count > 0, "no loaded map tiles were browser-verified");
assert.equal(evidence.venues["tft-vue"].deep_link_survives_reload, true);
assert.deepEqual(evidence.venues["tft-vue"].review_warnings, []);
assert.equal(evidence.venues["tft-osteria-mozza"].deep_link_survives_reload, true);
assert.deepEqual(evidence.venues["tft-osteria-mozza"].review_warnings, [
  "An alternate menu candidate is under review. Published menu links remain active until owner review is complete.",
]);
assert.equal(evidence.venues["tft-one-ninety"].deep_link_survives_reload, true);
assert.deepEqual(evidence.venues["tft-one-ninety"].review_warnings, [
  "No indexed official menu PDF was found for this venue. The missing-menu result is awaiting owner review.",
]);
for (const venue of Object.values(evidence.venues)) {
  assert.equal(venue.terms_visible, true);
  assert.equal(venue.google_maps_visible, true);
}
for (const key of [
  "venue_details_visible",
  "availability_visible",
  "menus_visible",
  "terms_visible",
  "official_roster_visible",
  "release_qualification_visible",
  "menu_freshness_visible",
]) assert.equal(evidence[key], true, `${key} was not browser-verified`);

const capturedAt = Date.parse(evidence.captured_at);
assert.ok(Number.isFinite(capturedAt), "browser evidence timestamp is invalid");
assert.ok(capturedAt <= Date.now() + 5 * 60_000, "browser evidence is future-dated");
assert.ok(Date.now() - capturedAt <= 24 * 60 * 60_000, "browser evidence is older than 24 hours");
assert.match(evidence.revision, /^[0-9a-f]{7,40}$/);

const noCache = { "Cache-Control": "no-cache" };
const [indexResponse, tableResponse, healthResponse, preflightResponse] = await Promise.all([
  fetch(`${evidence.site_url}?qa=${Date.now()}`, { headers: noCache }),
  fetch(`${evidence.site_url}data/table-for-two.json?qa=${Date.now()}`, { headers: noCache }),
  fetch("https://amex-reminders-production.up.railway.app/healthz", { headers: noCache }),
  fetch("https://amex-reminders-production.up.railway.app/api/subscribe", {
    method: "OPTIONS",
    headers: {
      Origin: evidence.site_url.replace(/\/$/, ""),
      "Access-Control-Request-Method": "POST",
      "Access-Control-Request-Headers": "content-type",
    },
  }),
]);
for (const response of [indexResponse, tableResponse, healthResponse, preflightResponse]) {
  assert.ok(response.ok, `production probe failed: ${response.url} ${response.status}`);
}

const index = await indexResponse.text();
const revisionMatch = index.match(/app\.js\?v=([0-9a-f]{7})/);
assert.ok(revisionMatch, "deployed index has no revision-bound app asset");
const appUrl = new URL(index.match(/<script[^>]+src=["']([^"']*app\.js\?v=[^"']+)/)?.[1], evidence.site_url);
const appResponse = await fetch(appUrl, { headers: noCache });
assert.ok(appResponse.ok, `deployed app probe failed: ${appResponse.status}`);
const appSource = await appResponse.text();
assert.equal(crypto.createHash("sha256").update(appSource).digest("hex"), evidence.app_sha256);

const table = await tableResponse.json();
assert.equal(table.menu_source.checked_at, evidence.menu_checked_at);
assert.equal(table.menu_source.review_queue_count, 2);
const vue = table.venues.find((venue) => venue.id === "tft-vue");
assert.ok(vue, "deployed VUE record is missing");
assert.equal(Object.values(vue.menu_pdfs || {}).filter((menu) => menu.status === "published").length, 2);
const osteria = table.venues.find((venue) => venue.id === "tft-osteria-mozza");
assert.ok(osteria, "deployed Osteria Mozza record is missing");
const reviewedOsteriaMenus = Object.values(osteria.menu_pdfs || {})
  .filter((menu) => menu.status === "published")
  .map((menu) => menu.url)
  .sort();
assert.deepEqual(evidence.venues["tft-osteria-mozza"].menu_urls.slice().sort(), reviewedOsteriaMenus);
assert.ok(!reviewedOsteriaMenus.some((url) => url.includes("Menu-Platinum.pdf")), "unreviewed Osteria candidate leaked");

const health = await healthResponse.json();
assert.equal(health.ok, true);
assert.equal(health.catalog_ok, true);
assert.equal(health.catalog_menu_checked_at, evidence.menu_checked_at);
assert.equal(health.feature_state.email_delivery_configured, true);
assert.equal(health.feature_state.owner_alerts_enabled, false);
assert.equal(health.feature_state.telegram_guide_enabled, false);
assert.equal(health.feature_state.telegram_reminders_enabled, false);
assert.equal(
  preflightResponse.headers.get("access-control-allow-origin"),
  evidence.site_url.replace(/\/$/, ""),
);

console.log("TFT browser evidence verification passed");
