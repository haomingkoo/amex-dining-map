#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const catalog = JSON.parse(fs.readFileSync("reminders/app/tft_guide_catalog.json", "utf8"));
assert.equal(catalog.schema_version, 1);
assert.equal(catalog.venues.length, 23);
assert.ok(catalog.venues.some((venue) => venue.id === "tft-vue"));

execFileSync("python3", ["scripts/build_tft_guide_catalog.py", "--check"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("node", ["scripts/tests/test_table_for_two_deep_link.js"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest", "reminders/tests/test_tft_guide.py", "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram guide verification passed");
