#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const workflows = [
  "refresh-data.yml",
  "refresh-global-dining.yml",
  "refresh-love-dining.yml",
  "refresh-table-for-two.yml",
];
for (const name of workflows) {
  const contents = fs.readFileSync(`.github/workflows/${name}`, "utf8");
  assert.match(contents, /scripts\/dispatch_owner_updates\.py/, `${name} does not dispatch owner updates`);
  assert.match(contents, /OWNER_ALERT_INGEST_TOKEN/, `${name} does not use the isolated ingestion token`);
}

const dispatch = fs.readFileSync("scripts/dispatch_owner_updates.py", "utf8");
assert.match(dispatch, /status.*published/);
assert.doesNotMatch(dispatch, /TELEGRAM_BOT_TOKEN/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "scripts/tests/test_dispatch_owner_updates.py",
  "scripts/tests/test_owner_alert_event_contract.py",
  "-q",
], { cwd: process.cwd(), stdio: "pipe", env: { ...process.env, PYTHONPATH: process.cwd() } });

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "python", "-c",
  "import json; from app.owner_alerts import OwnerAlertEvent; p=json.load(open('data/updates.json')); [OwnerAlertEvent.model_validate(e) for e in p['updates']]",
], { cwd: process.cwd(), stdio: "pipe", env: { ...process.env, PYTHONPATH: "reminders" } });

console.log("Telegram change dispatch verification passed");
