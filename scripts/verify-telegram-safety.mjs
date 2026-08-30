#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const guide = fs.readFileSync("reminders/app/tft_guide.py", "utf8");

assert.match(guide, /len\(matches\) != 1/);
assert.match(guide, /project"\) != "AMEXPlatSG"/);
assert.match(guide, /def _trusted_amex_url/);
assert.doesNotMatch(guide, /\b(?:requests|httpx|urlopen)\b/);
assert.doesNotMatch(guide, /\b(?:eval|exec)\s*\(/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "reminders/tests/test_tft_guide_safety.py",
  "reminders/tests/test_tft_guide.py",
  "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram safety verification passed");
