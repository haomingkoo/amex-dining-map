#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const catalog = JSON.parse(fs.readFileSync("reminders/app/tft_guide_catalog.json", "utf8"));
assert.equal(catalog.schema_version, 4);
// Review status, extractor version and venue patterns are refreshed data, so check shape only.
assert.deepEqual(catalog.documents.map((doc) => doc.id).sort(), ["tft-faq", "tft-terms"]);
for (const doc of catalog.documents) {
  assert.equal(typeof doc.review_status, "string", `${doc.id} has no review status`);
  assert.match(doc.extractor, /^pypdf \d+\.\d+\.\d+ extract_text /, `${doc.id} extractor is unversioned`);
}
const source = JSON.parse(fs.readFileSync("data/table-for-two.json", "utf8"));
const activeVenueCount = source.venues.filter((venue) => venue.booking_project_status !== "not_listed").length;
assert.equal(catalog.venues.length, activeVenueCount);
assert.ok(catalog.venues.every((venue) => Array.isArray(venue.release_patterns)));
assert.equal(catalog.release_source.source, "data/table-for-two-release-history.json");
assert.equal(catalog.release_source.project, "AMEXPlatSG");
assert.equal(catalog.slot_source.project, "AMEXPlatSG");
assert.equal(catalog.slot_source.stale_after_minutes, 30);

execFileSync("python3", ["scripts/build_tft_guide_catalog.py", "--check"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("node", ["scripts/tests/test_table_for_two_deep_link.js"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("node", ["scripts/verify-telegram-slots.mjs"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("node", ["scripts/verify-telegram-reminders.mjs"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest", "reminders/tests/test_tft_guide.py", "reminders/tests/test_tft_documents.py", "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram guide verification passed");
