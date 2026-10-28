#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

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
const futureCapture = new Date(now + 6 * 60 * 1000).toISOString();

assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_no_seats", captured_at: freshCapture } }),
  "no_seats",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_no_seats", captured_at: staleCapture } }),
  "stale",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_no_seats", captured_at: futureCapture } }),
  "stale",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_available", captured_at: staleCapture } }),
  "stale",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_available", checked_at: freshCapture } }),
  "available",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_available", checked_at: staleCapture } }),
  "stale",
);
assert.strictEqual(
  context.tableForTwoRawAvailabilityKey({ availability: { status: "live_available" } }),
  "unknown",
);
