#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const workflows = [
  "refresh-data.yml",
  "refresh-global-dining.yml",
  "refresh-love-dining.yml",
  "refresh-ratings.yml",
  "refresh-table-for-two.yml",
  "table-for-two-alerts.yml",
  "monitor-source-health.yml",
];
for (const name of workflows) {
  const contents = fs.readFileSync(`.github/workflows/${name}`, "utf8");
  assert.match(contents, /scripts\/dispatch_owner_updates\.py/, `${name} does not dispatch owner updates`);
  assert.match(contents, /OWNER_ALERT_INGEST_TOKEN/, `${name} does not use the isolated ingestion token`);
  assert.match(contents, /id: owner_dispatch/, `${name} does not identify the dispatch step`);
  assert.match(
    contents,
    /if: always\(\) && steps\.owner_dispatch\.outcome != 'skipped'/,
    `${name} does not persist receipts after an attempted dispatch`,
  );
  assert.match(contents, /MUST_STAGE: data\/updates\.json/, `${name} does not limit receipt commits to the ledger`);
}

const dispatch = fs.readFileSync("scripts/dispatch_owner_updates.py", "utf8");
assert.match(dispatch, /status.*published/);
assert.doesNotMatch(dispatch, /TELEGRAM_BOT_TOKEN/);
assert.match(dispatch, /record_owner_delivery_states/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "scripts/tests/test_dispatch_owner_updates.py",
  "scripts/tests/test_owner_alert_event_contract.py",
  "scripts/tests/test_source_change_updates.py",
  "scripts/tests/test_tft_menu_reviews.py",
  "scripts/tests/test_tft_roster_reviews.py",
  "scripts/tests/test_source_health.py",
  "scripts/tests/test_tft_official_documents.py",
  "scripts/tests/test_apply_love_dining_document_review.py",
  "scripts/tests/test_apply_love_dining_review.py",
  "scripts/tests/test_tft_release_patterns.py",
  "reminders/tests/test_owner_alerts.py",
  "-q",
], { cwd: process.cwd(), stdio: "pipe", env: { ...process.env, PYTHONPATH: process.cwd() } });

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "python", "-c",
  "import json; from app.owner_alerts import OwnerAlertEvent; p=json.load(open('data/updates.json')); [OwnerAlertEvent.model_validate(e) for e in p['updates']]",
], { cwd: process.cwd(), stdio: "pipe", env: { ...process.env, PYTHONPATH: "reminders" } });

console.log("Telegram change dispatch verification passed");
