#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const lifecycle = fs.readFileSync("reminders/app/telegram_reminders.py", "utf8");
const route = fs.readFileSync("reminders/app/telegram_bot_routes.py", "utf8");
const config = fs.readFileSync("reminders/app/config.py", "utf8");
const pages = fs.readFileSync(".github/workflows/deploy-pages.yml", "utf8");
const docs = fs.readFileSync("reminders/README.md", "utf8");
const dispatch = fs.readFileSync("scripts/dispatch-telegram-reminders.sh", "utf8");

for (const table of [
  "telegram_reminder_conversations",
  "telegram_reminders",
  "telegram_reminder_deliveries",
]) assert.match(lifecycle, new RegExp(table));
assert.doesNotMatch(
  lifecycle.slice(
    lifecycle.indexOf("CREATE TABLE IF NOT EXISTS telegram_reminder_conversations"),
    lifecycle.indexOf("CREATE TABLE IF NOT EXISTS telegram_reminders"),
  ),
  /chat_id/,
);
assert.match(lifecycle, /BEGIN IMMEDIATE/);
assert.match(lifecycle, /reminder delivery receipt conflict/);
assert.match(lifecycle, /state = 'unknown', chat_id = 0/);
assert.match(lifecycle, /state = 'active'.*state = 'claimed'/s);
assert.match(lifecycle, /def begin_notification/);
assert.match(route, /X-Telegram-Reminder-Dispatch-Token/);
assert.match(route, /begin_notification/);
assert.match(route, /run_id=run_id/);
assert.match(config, /TELEGRAM_REMINDERS_ENABLED/);
assert.match(config, /independent Telegram reminder dispatch token/);
assert.ok(
  pages.indexOf("Deploy attempt 1") <
    pages.indexOf("Dispatch Telegram reminders from deployed snapshot"),
);
assert.match(dispatch, /expected_generated_at/);
assert.match(pages, /TELEGRAM_REMINDER_DISPATCH_TOKEN/);
assert.match(dispatch, /::warning::Telegram reminder dispatch/);
assert.match(dispatch, /for attempt in \$\(seq 1 25\)/);
assert.match(dispatch, /if response=.*curl/s);
assert.match(dispatch, /bounded_response/);
assert.doesNotMatch(pages, /TELEGRAM_GUIDE_BOT_TOKEN/);
assert.match(docs, /at-most-once across ambiguous Telegram failures/);
assert.match(docs, /never logged or exported/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "reminders/tests/test_telegram_reminders.py",
  "reminders/tests/test_telegram_bot.py",
  "reminders/tests/test_health.py",
  "scripts/tests/test_dispatch_telegram_reminders_workflow.py",
  "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram reminder verification passed");
