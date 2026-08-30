#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(path, "utf8");
const compact = (value) => value.replace(/\s+/g, " ").trim();
const docs = compact(read("reminders/README.md"));
const envText = read("reminders/.env.example");
const config = read("reminders/app/config.py");
const main = read("reminders/app/main.py");
const ownerRoutes = read("reminders/app/owner_alert_routes.py");
const telegramRoutes = read("reminders/app/telegram_bot_routes.py");
const routes = read("reminders/app/routes.py");
const dispatch = read("scripts/dispatch_owner_updates.py");
const pages = read(".github/workflows/deploy-pages.yml");
const projectVerifier = read("scripts/verify-project.mjs");
const documentRunbook = compact(read("docs/tft-document-review-runbook.md"));

for (const heading of [
  "## Deployment (Railway)",
  "## Private owner alerts",
  "## Public Telegram guide",
  "### Guide bot activation and operations",
  "## Operational logs",
]) assert.ok(docs.includes(heading), `missing operations section: ${heading}`);

const envEntries = new Map(
  envText.split(/\r?\n/)
    .filter((line) => line && !line.startsWith("#") && line.includes("="))
    .map((line) => {
      const split = line.indexOf("=");
      return [line.slice(0, split), line.slice(split + 1)];
    }),
);
const configKeys = new Set(
  [...config.matchAll(/(?:os\.getenv|_env_bool|_env_int|_env_datetime)\(\s*["']([A-Z][A-Z0-9_]*)["']/g)]
    .map((match) => match[1]),
);
for (const key of configKeys) assert.ok(envEntries.has(key), `.env.example omits ${key}`);
for (const key of ["OWNER_ALERTS_ENABLED", "TELEGRAM_GUIDE_ENABLED", "TELEGRAM_REMINDERS_ENABLED"]) {
  assert.equal(envEntries.get(key), "false", `${key} must default to false`);
}
const secretKeys = [
  "OWNER_ALERT_INGEST_TOKEN",
  "TELEGRAM_GUIDE_WEBHOOK_SECRET",
  "TELEGRAM_IDENTITY_HASH_SALT",
  "TELEGRAM_REMINDER_DISPATCH_TOKEN",
];
const placeholders = secretKeys.map((key) => envEntries.get(key));
assert.equal(new Set(placeholders).size, placeholders.length, "secret placeholders must be visibly distinct");
assert.doesNotMatch(envText, /\b\d{6,}:[A-Za-z0-9_-]{20,}\b/, "example contains a bot token");
assert.doesNotMatch(envText, /(?:^|=)-100\d{6,}/m, "example contains a channel ID");

for (const field of [
  "email_delivery_configured",
  "owner_alerts_enabled",
  "telegram_guide_enabled",
  "telegram_reminders_enabled",
]) assert.ok(main.includes(`\"${field}\"`), `health omits ${field}`);
for (const source of [ownerRoutes, telegramRoutes]) assert.match(source, /status_code=503/);

for (const phrase of [
  "same `deployment_id`",
  "catalog_ok",
  "Pages production acceptance is separate",
  "exact replacement Pages run",
  "set `OWNER_ALERTS_ENABLED=true`; deploy; verify `/healthz` reports `owner_alerts_enabled=true`",
  "expected `503`",
  "send one reviewed test event",
  "removing both `OWNER_ALERT_INGEST_URL` and `OWNER_ALERT_INGEST_TOKEN`",
  "set `TELEGRAM_GUIDE_ENABLED=true`; deploy; verify `/healthz` reports `telegram_guide_enabled=true`",
  "then call `setWebhook`",
  "create/list/cancel a real test reminder",
  "only then set `TELEGRAM_REMINDERS_EXPECTED_ENABLED=true`",
  "older than 36 hours as actionable catalogue staleness",
  "per-venue 30-minute threshold",
  "Identity-salt migration is a separate operation",
  "Rollback in this safe order",
  "delete its webhook without dropping pending updates",
  "no shared request ID with Telegram",
  "never dump rows",
  "FROM owner_alert_deliveries",
  "Do not manually resend `unknown` rows",
]) assert.ok(docs.includes(phrase), `missing operations contract: ${phrase}`);
assert.ok(docs.indexOf("TELEGRAM_REMINDERS_EXPECTED_ENABLED=false") < docs.indexOf("TELEGRAM_REMINDERS_ENABLED=false"));
assert.ok(docs.indexOf("TELEGRAM_REMINDERS_ENABLED=false") < docs.indexOf("TELEGRAM_GUIDE_ENABLED=false"));
assert.ok(docs.indexOf("TELEGRAM_GUIDE_ENABLED=false") < docs.indexOf("delete the webhook with"));

for (const workflow of [
  ".github/workflows/refresh-data.yml",
  ".github/workflows/refresh-global-dining.yml",
  ".github/workflows/refresh-love-dining.yml",
  ".github/workflows/refresh-table-for-two.yml",
]) {
  const source = read(workflow);
  assert.match(source, /OWNER_ALERT_INGEST_URL/);
  assert.match(source, /OWNER_ALERT_INGEST_TOKEN/);
  assert.match(source, /dispatch_owner_updates\.py/);
}
assert.match(dispatch, /if not url and not token:/);
for (const key of ["REMINDERS_API_BASE", "TELEGRAM_REMINDER_DISPATCH_TOKEN", "TELEGRAM_REMINDERS_EXPECTED_ENABLED"]) {
  assert.match(pages, new RegExp(key));
}
assert.match(pages, /Dispatch Telegram reminders from deployed snapshot/);
for (const event of [
  "confirmation_email_failed",
  "owner_alert_delivery",
  "telegram_guide_delivery",
  "telegram_reminder_run",
  "telegram_reminder_delivery",
]) assert.ok(`${routes}\n${ownerRoutes}\n${telegramRoutes}`.includes(event), `runtime event missing: ${event}`);
assert.match(projectVerifier, /verify-operations-docs\.mjs/);
for (const phrase of [
  "archives the exact bytes",
  "canonical hash-addressed manifest and transition paths",
  "rebuilds the bundled Telegram catalogue",
  "pending event is reconciled",
]) assert.ok(documentRunbook.includes(phrase), `document review runbook omits: ${phrase}`);

console.log("operations documentation verification passed");
