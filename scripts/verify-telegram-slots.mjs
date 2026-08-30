#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const source = JSON.parse(fs.readFileSync("data/table-for-two-slots.json", "utf8"));
assert.equal(source.schema_version, 1);
assert.equal(source.source_project, "AMEXPlatSG");
assert.ok(source.venues.length > 0 && source.venues.length <= 50);
assert.ok(fs.statSync("data/table-for-two-slots.json").size < 1_000_000);

const alerts = fs.readFileSync(".github/workflows/table-for-two-alerts.yml", "utf8");
assert.match(alerts, /scripts\/build_tft_slot_snapshot\.py/);
assert.match(alerts, /scripts\/track_table_for_two_releases\.py[\s\S]*scripts\/build_tft_guide_catalog\.py/);
assert.match(alerts, /data\/table-for-two-slots\.json/);
assert.match(alerts, /reminders\/app\/tft_guide_catalog\.json/);
const pages = fs.readFileSync(".github/workflows/deploy-pages.yml", "utf8");
assert.match(pages, /table-for-two-slots\.json/);
const route = fs.readFileSync("reminders/app/telegram_bot_routes.py", "utf8");
assert.match(route, /"\/slots"/);
assert.match(route, /run_in_threadpool\(\s*tft_guide\.handle_message/);

execFileSync("python3", ["scripts/build_tft_slot_snapshot.py", "--check"], {
  cwd: root,
  stdio: "pipe",
});
execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "scripts/tests/test_tft_slot_snapshot.py",
  "reminders/tests/test_tft_slot_source.py",
  "reminders/tests/test_tft_slots.py",
  "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram slot verification passed");
