#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import fs from "node:fs";

const run = (command, args) => execFileSync(command, args, {
  cwd: process.cwd(),
  encoding: "utf8",
  stdio: "pipe",
});
const read = (path) => fs.readFileSync(path, "utf8");
const requireText = (condition, message) => {
  if (!condition) throw new Error(message);
};

run("python3", ["-m", "unittest", "scripts.tests.test_source_health"]);
run("node", ["scripts/tests/test_source_health_ui.js"]);
const temporaryHealth = `/tmp/amex-source-health-${process.pid}.json`;
const buildOutput = run("python3", [
  "scripts/build_source_health.py",
  "--no-events",
  "--output",
  temporaryHealth,
]);
fs.rmSync(temporaryHealth, { force: true });
requireText(
  /^SOURCE HEALTH OK sources=9 events=0\s*$/.test(buildOutput),
  "source-health diagnostics must remain aggregate and secret-safe",
);

const health = JSON.parse(read("data/source-health.json"));
const ids = new Set((health.sources || []).map((source) => source.id));
const expected = [
  "global-dining",
  "japan-dining",
  "plat-stay",
  "love-dining",
  "table-for-two-roster",
  "table-for-two-menus",
  "table-for-two-availability",
  "google-maps-ratings",
  "tabelog-ratings",
];
requireText(health.schema_version === 1, "source-health schema version must be 1");
requireText(expected.every((id) => ids.has(id)), "source-health must cover all nine sources");
requireText((health.sources || []).every((source) => source.source_url?.startsWith("https://")), "every source-health row needs an HTTPS source");

for (const path of [
  ".github/workflows/refresh-data.yml",
  ".github/workflows/refresh-global-dining.yml",
  ".github/workflows/refresh-love-dining.yml",
  ".github/workflows/refresh-ratings.yml",
  ".github/workflows/refresh-table-for-two.yml",
]) {
  const workflow = read(path);
  requireText(workflow.includes("group: source-ledger-refresh"), `${path} must serialize source ledger writes`);
  requireText(workflow.includes("Finalize source health"), `${path} must finalize source health`);
  requireText(workflow.includes("if: always()"), `${path} must record failure state on failed refreshes`);
  requireText(workflow.includes("data/source-health.json"), `${path} must commit source health`);
  requireText(workflow.includes("dispatch_owner_updates.py"), `${path} must dispatch health transitions`);
}

const availability = read(".github/workflows/table-for-two-alerts.yml");
requireText(
  availability.includes('cron: "2,17,32,47 * * * *"'),
  "availability refresh must run well inside its 30-minute freshness window",
);
requireText(
  availability.includes("group: table-for-two-availability-refresh"),
  "high-frequency availability refresh must not contend with daily source writers",
);
requireText(availability.includes("Finalize source health"), "availability refresh must finalize source health");
requireText(availability.includes("data/source-health.json"), "availability refresh must commit source health");
requireText(availability.includes("dispatch_owner_updates.py"), "availability refresh must dispatch health transitions");

const monitor = read(".github/workflows/monitor-source-health.yml");
requireText(monitor.includes("22,52 * * * *"), "health monitor must age sources independently of refresh success");
requireText(read(".github/workflows/deploy-pages.yml").includes("source-health.json"), "Pages must deploy source health");

console.log("source health verification passed");
