#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const context = {
  normalizeInlineText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  },
  formatSourceDate(value) {
    return value;
  },
};
vm.runInNewContext(
  `${extractFunction("singaporeTodayKey")}\n${extractFunction("loveDiningEligibilityState")}\n${extractFunction("stayNameProfile")}\nObject.assign(globalThis, { loveDiningEligibilityState, stayNameProfile });`,
  context,
);

assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "eligible", eligibility_effective_from: "2026-07-15" },
    "2026-08-30",
  ).key,
  "eligible",
);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "ineligible", eligibility_effective_from: "2026-09-01" },
    "2026-08-30",
  ).key,
  "future_change",
);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "ineligible", eligibility_effective_from: "2026-09-01" },
    "2026-09-01",
  ).key,
  "ineligible",
);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { notes: "Temporarily closed for renovation" },
    "2026-08-30",
  ).key,
  "review_required",
);
assert.strictEqual(
  context.stayNameProfile({ name: "Fraser Suites (From 8 May 2026)" }).eligibilityNote,
  "Eligible since 2026-05-08",
);
assert.strictEqual(
  context.stayNameProfile({ name: "W Hotel (From 1 June 2026)" }).eligibilityNote,
  "Eligible since 2026-06-01",
);
