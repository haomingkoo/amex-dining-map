#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = app.indexOf(`async function ${name}(`);
  assert.ok(start >= 0, `Missing ${name}`);
  const bodyStart = app.indexOf("{", app.indexOf(")", start));
  let depth = 0;
  for (let index = bodyStart; index < app.length; index += 1) {
    if (app[index] === "{") depth += 1;
    if (app[index] === "}") depth -= 1;
    if (depth === 0) return app.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

function buildContext(fetchImpl) {
  const warnings = [];
  const context = {
    state: { tableForTwo: { venues: [] }, tableForTwoLiveRefreshInFlight: false, tableForTwoLiveRefreshAt: null, tableForTwoLiveRefreshFailed: false },
    TABLE_FOR_TWO_LIVE_SNAPSHOT_URL: "https://example.test/api/tft/slots",
    TABLE_FOR_TWO_FETCH_TIMEOUT_MS: 1000,
    AbortSignal,
    Date,
    Error,
    fetch: fetchImpl,
    applyTableForTwoLiveSnapshot: () => true,
    isTableForTwoRoute: () => true,
    refreshTableForTwoDateOptions: () => {},
    rerenders: 0,
    console: { warn: (...args) => warnings.push(args.join(" ")) },
  };
  context.filterTableForTwo = () => { context.rerenders += 1; };
  vm.runInNewContext(`${extractFunction("refreshTableForTwoLiveAvailability")}\nglobalThis.refresh = refreshTableForTwoLiveAvailability;`, context);
  return { context, warnings };
}

(async () => {
  // A failed live check warns, flags the UI, and still rerenders on the published snapshot.
  const failed = buildContext(async () => ({ ok: false, status: 503 }));
  await failed.context.refresh({ force: true });
  assert.equal(failed.context.state.tableForTwoLiveRefreshFailed, true);
  assert.match(failed.warnings[0], /HTTP 503/);
  assert.equal(failed.context.rerenders, 1);
  assert.equal(failed.context.state.tableForTwoLiveRefreshInFlight, false);

  // A successful live check clears the failure flag.
  const ok = buildContext(async () => ({ ok: true, json: async () => ({}) }));
  ok.context.state.tableForTwoLiveRefreshFailed = true;
  await ok.context.refresh({ force: true });
  assert.equal(ok.context.state.tableForTwoLiveRefreshFailed, false);
  assert.equal(ok.warnings.length, 0);

  // The freshness panel tells readers when the live check failed.
  assert.match(app, /tableForTwoLiveRefreshFailed \? " Latest live check unavailable; showing the published snapshot\."/);

  console.log("tft live refresh failure tests passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
