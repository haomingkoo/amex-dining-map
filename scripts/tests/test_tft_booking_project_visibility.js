#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const context = {
  state: {
    tableForTwo: {
      venues: [
        { id: "active", name: "Sarai", booking_project_status: "active" },
        { id: "not-listed", name: "Osteria Mozza", booking_project_status: "not_listed" },
        { id: "legacy", name: "Legacy Venue" },
      ],
    },
  },
};

vm.runInNewContext(
  `${extractFunction("tableForTwoPayload")}\n${extractFunction("tableForTwoVenues")}\n${extractFunction("tableForTwoNotListedVenues")}\n${extractFunction("tableForTwoAlertVenueNames")}\nObject.assign(globalThis, { tableForTwoPayload, tableForTwoVenues, tableForTwoNotListedVenues, tableForTwoAlertVenueNames });`,
  context,
);

assert.deepEqual(
  Array.from(context.tableForTwoVenues(), (record) => record.id),
  ["active", "legacy"],
);
assert.deepEqual(
  Array.from(context.tableForTwoNotListedVenues(), (record) => record.id),
  ["not-listed"],
);
assert.deepEqual(Array.from(context.tableForTwoAlertVenueNames()), ["Legacy Venue", "Sarai"]);

assert.match(source, /Active booking-app restaurants first\. Not currently shown:/);
assert.match(source, /new booking-app venue/);
assert.match(source, /Historical roster record/);
assert.match(source, /Booking, availability alerts, and reminders are disabled/);

console.log("TFT booking-project visibility verification passed");
