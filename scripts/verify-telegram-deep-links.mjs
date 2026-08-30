#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const run = (command, args, options = {}) => execFileSync(command, args, {
  cwd: process.cwd(),
  encoding: "utf8",
  stdio: "pipe",
  ...options,
});

run("node", ["scripts/tests/test_table_for_two_deep_link.js"]);
run("node", ["scripts/tests/test_table_for_two_telegram_links.js"]);
run("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "reminders/tests/test_tft_guide.py",
  "reminders/tests/test_tft_slots.py",
  "reminders/tests/test_telegram_reminders.py",
  "reminders/tests/test_telegram_transport.py",
  "scripts/tests/test_build_telegram_public_config.py",
  "scripts/tests/test_check_telegram_readiness.py",
  "-q",
], { env: { ...process.env, PYTHONPATH: process.cwd() } });

const workflow = fs.readFileSync(".github/workflows/deploy-pages.yml", "utf8");
const disabledConfig = JSON.parse(fs.readFileSync("data/telegram-guide.json", "utf8"));
assert.match(workflow, /TELEGRAM_GUIDE_BOT_USERNAME:.*vars\.TELEGRAM_GUIDE_BOT_USERNAME/);
assert.match(workflow, /build_telegram_public_config\.py --output site\/data\/telegram-guide\.json/);
assert.deepEqual(disabledConfig, { schema_version: 1, enabled: false, bot_username: null });

console.log("Telegram deep-link verification passed");
