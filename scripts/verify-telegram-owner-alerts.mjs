#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const route = fs.readFileSync("reminders/app/owner_alert_routes.py", "utf8");
const config = fs.readFileSync("reminders/app/config.py", "utf8");
const store = fs.readFileSync("reminders/app/owner_alert_store.py", "utf8");

assert.match(route, /settings\.telegram_owner_chat_id/);
assert.doesNotMatch(route, /payload\.(chat|destination)/);
assert.match(route, /event\.status != "published"/);
assert.match(config, /OWNER_ALERT_INGEST_TOKEN/);
assert.match(config, /TELEGRAM_OWNER_CHAT_ID/);
assert.match(config, /OWNER_ALERT_NOT_BEFORE/);
assert.match(store, /PRIMARY KEY\(event_id, destination_chat_id\)/);
assert.match(store, /'unknown'/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest", "reminders/tests/test_owner_alerts.py", "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram owner alert verification passed");
