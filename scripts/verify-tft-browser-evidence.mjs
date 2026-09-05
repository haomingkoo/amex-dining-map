#!/usr/bin/env node
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";

// Mirrors tableForTwoPublishedMenus in web/app.js, legacy fallback included, so a
// venue that still carries only the single menu_pdf field is not read here as
// menu-less while its card links a menu.
function publishedMenuUrls(record) {
  const menus = Object.values(record.menu_pdfs || {}).filter((menu) => menu?.status === "published" && menu.url);
  if (menus.length) return menus.map((menu) => menu.url).sort();
  const legacy = record.menu_pdf || {};
  return legacy.status === "published" && legacy.url ? [legacy.url] : [];
}

const evidencePath = "docs/evidence/tft-browser-production.json";
assert.ok(fs.existsSync(evidencePath), "production browser evidence is missing");
const evidence = JSON.parse(fs.readFileSync(evidencePath, "utf8"));

assert.equal(evidence.schema_version, 1);
assert.equal(evidence.site_url, "https://amex-explorer.kooexperience.com/");
assert.equal(evidence.route, "#/table-for-two?venue=tft-vue");
assert.equal(evidence.selected_venue_id, "tft-vue");
assert.equal(evidence.console_error_count, 0);
assert.deepEqual(evidence.unhandled_failed_page_resources, []);
assert.equal(evidence.api_key_watermark_visible, false);
assert.equal(evidence.reminder_form_visible, true);
assert.match(evidence.app_sha256, /^[0-9a-f]{64}$/);
for (const size of ["390x844", "320x740"]) {
  assert.equal(evidence.viewports[size].horizontal_overflow, false, `${size} has horizontal overflow`);
  assert.deepEqual(evidence.viewports[size].overflow_offenders, [], `${size} has clipped descendants`);
}
assert.deepEqual(evidence.tile_hosts, ["tile.openstreetmap.de"]);
assert.ok(evidence.loaded_tile_count > 0, "no loaded map tiles were browser-verified");
for (const key of [
  "venue_details_visible",
  "availability_visible",
  "menus_visible",
  "terms_pdf_linked",
  "official_roster_linked",
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
// The queue count moves with the roster, so pin it to the capture rather than a
// literal: a number frozen in this file rots the gate the next time a venue is added.
assert.equal(table.menu_source.review_queue_count, evidence.review_queue_count);
assert.ok(table.venues.length > 0, "deployed payload lists no venues");
// The capture walks the deployed roster, so any drift means the evidence predates
// the payload it is being checked against and has to be recaptured.
assert.deepEqual(
  Object.keys(evidence.venues).sort(),
  table.venues.map((venue) => venue.id).sort(),
  "browser evidence does not cover every deployed venue; recapture it",
);

const withMenus = table.venues.filter((venue) => publishedMenuUrls(venue).length > 0);
const withoutMenus = table.venues.filter((venue) => publishedMenuUrls(venue).length === 0);
assert.ok(withMenus.length > 0, "no deployed venue publishes a menu; recheck this gate's premise");
assert.ok(withoutMenus.length > 0, "every deployed venue publishes a menu, so the missing-menu rule proves nothing; recheck this gate's premise");

for (const venue of table.venues) {
  const captured = evidence.venues[venue.id];
  assert.equal(captured.deep_link_survives_reload, true, `${venue.id} deep link did not survive a reload`);
  assert.equal(captured.google_maps_visible, true, `${venue.id} card offers no Google Maps link`);
  // Never present an unverified menu as official, and never drop a reviewed one:
  // the card's menu PDFs must be exactly the payload's published set. This is what
  // keeps the unreviewed Osteria Mozza candidate (Menu-Platinum.pdf beside the
  // published Menu_Platinum.pdf) off the card, without pinning either filename.
  assert.deepEqual(
    captured.card_menu_pdf_urls,
    publishedMenuUrls(venue),
    `${venue.id} card menus differ from the payload's published set`,
  );
}

// A venue with no published menu has to tell the reader so. The gate checks that
// in two copy-free halves, because the previous version pinned the exact sentence
// and sat red for five days after production reworded it.
//
// Today those cards read "Buffet venue - no set menu PDF." for the four buffets and
// "We could not verify an official menu for this venue. Check the official source
// before booking." for the other six; while payload.manual_review_required is set,
// web/app.js replaces the second with a payload-wide review banner. All three are
// accepted, and so is a reword, because the assertions below are about the payload
// holding a reason and the card carrying a note, not about which words are used.
const missingMenuQueue = new Set(
  (table.menu_source.review_queue || [])
    .filter((item) => item?.kind === "missing_venue_menu" && item.venue_id)
    .map((item) => item.venue_id),
);
for (const venue of withoutMenus) {
  assert.ok(
    venue.menu_pdf?.status === "buffet_no_menu_expected" || missingMenuQueue.has(venue.id),
    `${venue.id} publishes no menu and the payload holds no reason to caveat it, so its card has nothing to say`,
  );
  assert.ok(
    evidence.venues[venue.id].card_notes.length > 0,
    `${venue.id} publishes no menu and its card tells the reader nothing`,
  );
}

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

console.log(
  `missing-menu rule enforced on ${withoutMenus.length} of ${table.venues.length} browser-verified venues`,
);
console.log("TFT browser evidence verification passed");
