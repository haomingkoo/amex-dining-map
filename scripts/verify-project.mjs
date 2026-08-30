#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const run = (command, args, options = {}) => execFileSync(command, args, {
  cwd: root,
  encoding: "utf8",
  stdio: "pipe",
  ...options,
});

run("node", ["--check", "web/app.js"]);
for (const name of fs.readdirSync(path.join(root, "scripts/tests")).filter((item) => item.endsWith(".js")).sort()) {
  run("node", [`scripts/tests/${name}`]);
}
run("uv", [
  "run",
  "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest", "reminders/tests", "scripts/tests", "-q",
], { env: { ...process.env, PYTHONPATH: root } });
run("python3", ["-m", "compileall", "-q", "reminders/app", "scripts"]);
run("node", ["scripts/verify-operations-docs.mjs"]);
run("node", ["scripts/verify-source-health.mjs"]);

console.log("project verification passed");
