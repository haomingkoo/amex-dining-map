#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const route = fs.readFileSync("reminders/app/telegram_bot_routes.py", "utf8");
assert.match(route, /X-Telegram-Bot-Api-Secret-Token/);
assert.match(route, /message\.chat\.type != "private"/);
assert.match(route, /message\.chat\.id != message\.sender\.id/);
assert.match(route, /await run_in_threadpool\(\s*telegram\.send_message/);
assert.doesNotMatch(route, /telegram_owner_chat_id|owner_alert/);
assert.doesNotMatch(route, /urlopen|load_remote_catalog/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "reminders/tests/test_telegram_bot.py",
  "reminders/tests/test_telegram_reminders.py",
  "reminders/tests/test_health.py",
  "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram security verification passed");
