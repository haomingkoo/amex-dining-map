#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const root = process.cwd();
const guide = fs.readFileSync("reminders/app/tft_guide.py", "utf8");
const documents = fs.readFileSync("reminders/app/tft_documents.py", "utf8");

assert.match(guide, /len\(matches\) != 1/);
assert.match(guide, /project"\) != "AMEXPlatSG"/);
assert.match(guide, /def _trusted_amex_url/);
assert.doesNotMatch(guide, /\b(?:requests|httpx|urlopen)\b/);
assert.doesNotMatch(guide, /\b(?:eval|exec)\s*\(/);

// The guide module gained a network call on 2026-09-05 (the published-catalogue
// read) and slipped past the urlopen grep above, which left this gate green while
// the no-network property it asserted was already false. The property that actually
// matters is narrower and still true: the guide can never be induced to fetch a
// URL derived from a message. Assert that, so a future arbitrary fetch fails here.
const main = fs.readFileSync("reminders/app/main.py", "utf8");
assert.match(guide, /_opener = urllib\.request\.build_opener\(_NoRedirect\(\)\)\.open/,
  "the guide's only opener must refuse redirects");
assert.match(guide, /class _NoRedirect\(urllib\.request\.HTTPRedirectHandler\):/);
assert.match(main, /^PUBLISHED_CATALOG_URL = f"\{settings\.explorer_base_url\}\/data\//m,
  "the fetched URL must be built from configuration, never from a request");
assert.match(main, /run_catalog_refresh_loop\(\s*PUBLISHED_CATALOG_URL,/,
  "the refresh loop must be started with that constant and nothing else");
assert.equal((guide.match(/urllib\.request\.Request\(/g) || []).length, 1,
  "the guide must build exactly one request, the published-catalogue read");
assert.doesNotMatch(guide, /def .*\(.*\bmessage\b.*\).*:[\s\S]{0,400}?_fetch_published/,
  "no message-handling function may reach the fetcher");
assert.doesNotMatch(documents, /\b(?:requests|httpx|urlopen)\b/);
assert.doesNotMatch(documents, /\b(?:eval|exec)\s*\(/);

execFileSync("uv", [
  "run", "--python", "3.12",
  "--with-requirements", "reminders/requirements.txt",
  "--with-requirements", "reminders/requirements-dev.txt",
  "pytest",
  "reminders/tests/test_tft_guide_safety.py",
  "reminders/tests/test_tft_guide.py",
  "reminders/tests/test_tft_documents.py",
  "-q",
], { cwd: root, stdio: "pipe", env: { ...process.env, PYTHONPATH: root } });

console.log("Telegram safety verification passed");
