#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const names = [
  "tableForTwoLiveSnapshotIsValid",
  "tableForTwoAvailabilityFromLiveVenue",
  "applyTableForTwoLiveSnapshot",
];
const context = {
  state: {
    tableForTwo: {
      venues: [
        { id: "tft-vue", name: "VUE", booking_project_status: "active" },
        { id: "tft-sarai", name: "Sarai", booking_project_status: "active" },
        { id: "tft-vineyard", name: "Vineyard", booking_project_status: "active" },
      ],
    },
  },
  tableForTwoSearchText: (record) => record.name,
  Map,
};
vm.runInNewContext(
  `${names.map(extractFunction).join("\n")}\nObject.assign(globalThis, { ${names.join(", ")} });`,
  context,
);

const generatedAt = new Date().toISOString();
const payload = {
  schema_version: 1,
  source_project: "AMEXPlatSG",
  generated_at: generatedAt,
  refresh_status: "partial",
  counts: { eligible: 3, succeeded: 2, failed: 1, retained: 0 },
  venues: [
    {
      id: "tft-vue",
      project: "AMEXPlatSG",
      status: "live_available",
      checked_at: generatedAt,
      attempted_at: generatedAt,
      result: "fresh",
      error_code: null,
      meals: [{ meal: "Dinner", status: "available", slots: [{ date: "2026-09-03", time: "19:00", max_seats: 2 }] }],
    },
    {
      id: "tft-sarai",
      project: "AMEXPlatSG",
      status: "unknown",
      checked_at: null,
      attempted_at: generatedAt,
      result: "error",
      error_code: "not_in_project",
      meals: [],
    },
    {
      id: "tft-vineyard",
      project: "AMEXPlatSG",
      status: "live_no_seats",
      checked_at: generatedAt,
      attempted_at: generatedAt,
      result: "fresh",
      error_code: null,
      meals: [],
    },
  ],
};

assert.equal(context.tableForTwoLiveSnapshotIsValid(payload), true);
assert.equal(context.applyTableForTwoLiveSnapshot(payload), true);
assert.equal(context.state.tableForTwo.venues[0].availability.status, "live_available");
assert.equal(context.state.tableForTwo.venues[0].availability.live_result, "fresh");
assert.equal(context.state.tableForTwo.venues[1].booking_project_status, "not_listed");
assert.equal(context.state.tableForTwo.venues[2].availability.status, "live_no_seats");
assert.equal(context.state.tableForTwo.availability_source.refresh_status, "partial");
assert.equal(context.tableForTwoLiveSnapshotIsValid({ ...payload, source_project: "other" }), false);
assert.equal(context.tableForTwoLiveSnapshotIsValid({ ...payload, venues: [payload.venues[0], payload.venues[0]] }), false);

console.log("Table for Two live overlay verification passed");
