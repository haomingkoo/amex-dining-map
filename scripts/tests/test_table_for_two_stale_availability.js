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

const functionNames = [
  "tableForTwoAvailabilityIsStale",
  "tableForTwoRawAvailabilityKey",
];
const context = {
  TABLE_FOR_TWO_AVAILABILITY_STALE_MINUTES: 30,
};

vm.runInNewContext(
  `${functionNames.map(extractFunction).join("\n")}\nObject.assign(globalThis, { ${functionNames.join(", ")} });`,
  context,
);

const now = Date.now();
const freshCapture = new Date(now - 29 * 60 * 1000).toISOString();
const staleCapture = new Date(now - 31 * 60 * 1000).toISOString();

assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_no_seats", captured_at: freshCapture } }),
  "no_seats",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_no_seats", captured_at: staleCapture } }),
  "unknown",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_available", captured_at: staleCapture } }),
  "available",
);
