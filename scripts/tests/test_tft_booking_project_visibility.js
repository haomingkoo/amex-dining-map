#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");

const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

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

assert.match(source, /Restaurants you can book in the Amex app come first\. Not in the app right now:/);
assert.match(source, /new booking-app venue/);
assert.match(source, /Earlier listing/);
assert.match(source, /Booking, alerts and reminders are off/);

console.log("TFT booking-project visibility verification passed");
