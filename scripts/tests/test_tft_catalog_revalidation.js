#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing ${name}`);
  // The parameter list destructures an options object, so skip past its parens
  // before looking for the body brace.
  let parens = 0;
  let cursor = source.indexOf("(", start);
  for (; cursor < source.length; cursor += 1) {
    if (source[cursor] === "(") parens += 1;
    if (source[cursor] === ")") parens -= 1;
    if (parens === 0) break;
  }
  const bodyStart = source.indexOf("{", cursor);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return `async ${source.slice(start, index + 1)}`;
  }
  throw new Error(`Unclosed ${name}`);
}

function harness({ catalog, slots = { venues: [] }, releaseHistory = { observations: [] } }) {
  const calls = { fetched: [], rendered: 0, liveRefreshed: 0, snapshots: [] };
  const context = {
    state: {
      dataLoaded: { tableForTwo: true },
      tableForTwo: { venues: [{ id: "tft-colony", name: "Colony" }] },
      tableForTwoReleaseHistory: { observations: ["stale"] },
      tableForTwoDataRevalidatedAt: null,
      tableForTwoDataRevalidateInFlight: false,
      tableForTwoLiveRefreshAt: 1,
    },
    TABLE_FOR_TWO_DATA_URL: "catalog",
    TABLE_FOR_TWO_DATA_FALLBACK_URL: "catalog-fallback",
    TABLE_FOR_TWO_STATIC_SNAPSHOT_URL: "slots",
    TABLE_FOR_TWO_RELEASE_HISTORY_URL: "release",
    TABLE_FOR_TWO_RELEASE_HISTORY_FALLBACK_URL: "release-fallback",
    TABLE_FOR_TWO_DATA_REVALIDATE_INTERVAL_MS: 5 * 60 * 1000,
    fetchJson: async (url) => {
      calls.fetched.push(url);
      if (url === "catalog") return catalog;
      if (url === "slots") return slots;
      if (url === "release") return releaseHistory;
      return null;
    },
    applyTableForTwoStaticSnapshot: (payload) => calls.snapshots.push(payload),
    tableForTwoVenues: () => context.state.tableForTwo.venues || [],
    tableForTwoSearchText: (record) => record.name,
    refreshTableForTwoCategoryOptions: () => {},
    isTableForTwoRoute: () => true,
    refreshTableForTwoDateOptions: () => {},
    filterTableForTwo: () => {
      calls.rendered += 1;
    },
    refreshTableForTwoLiveAvailability: async () => {
      calls.liveRefreshed += 1;
    },
    Date,
  };
  vm.runInNewContext(
    `${extractFunction("revalidateTableForTwoData")}\nglobalThis.revalidateTableForTwoData = revalidateTableForTwoData;`,
    context,
  );
  return { context, calls };
}

(async () => {
  // A tab left open must pick up a roster published after it loaded.
  const fresh = {
    venues: [
      { id: "tft-colony", name: "Colony", booking_project_status: "not_listed" },
      { id: "tft-park90", name: "Park90", booking_project_status: "active" },
    ],
    availability_last_checked_at: "2026-09-03T12:21:06Z",
  };
  const { context, calls } = harness({ catalog: fresh });

  await context.revalidateTableForTwoData();

  assert.equal(context.state.tableForTwo.availability_last_checked_at, "2026-09-03T12:21:06Z");
  assert.deepEqual(
    context.state.tableForTwo.venues.map((venue) => venue.id),
    ["tft-colony", "tft-park90"],
  );
  assert.equal(context.state.tableForTwo.venues[0].booking_project_status, "not_listed");
  assert.equal(context.state.tableForTwoReleaseHistory.observations.length, 0);
  assert.equal(calls.rendered, 1);
  assert.equal(calls.liveRefreshed, 1);
  assert.equal(context.state.tableForTwoLiveRefreshAt, null);
  assert.ok(context.state.tableForTwoDataRevalidatedAt);

  // A second call inside the interval must not refetch.
  const before = calls.fetched.length;
  await context.revalidateTableForTwoData();
  assert.equal(calls.fetched.length, before);

  // Forcing past the interval refetches.
  await context.revalidateTableForTwoData({ force: true });
  assert.ok(calls.fetched.length > before);

  // A failed catalog fetch keeps the roster already on screen.
  const failed = harness({ catalog: null });
  await failed.context.revalidateTableForTwoData();
  assert.deepEqual(
    failed.context.state.tableForTwo.venues.map((venue) => venue.id),
    ["tft-colony"],
  );
  assert.equal(failed.calls.rendered, 0);

  // Every refetched file must bypass the 600s browser cache, or revalidation is a no-op.
  const revalidated = source.slice(
    source.indexOf("const REVALIDATE_DATA_URLS"),
    source.indexOf("]);", source.indexOf("const REVALIDATE_DATA_URLS")),
  );
  for (const name of [
    "TABLE_FOR_TWO_DATA_URL",
    "TABLE_FOR_TWO_DATA_FALLBACK_URL",
    "TABLE_FOR_TWO_STATIC_SNAPSHOT_URL",
    "TABLE_FOR_TWO_RELEASE_HISTORY_URL",
    "TABLE_FOR_TWO_RELEASE_HISTORY_FALLBACK_URL",
  ]) {
    assert.ok(revalidated.includes(name), `${name} must revalidate`);
  }

  // The refresh must be wired to both the timer and returning to the tab.
  const wiring = source.slice(source.indexOf("function ensureTableForTwoLiveRefresh("));
  assert.ok(wiring.includes("visibilitychange"), "must refresh when the tab becomes visible");
  assert.ok(
    wiring.indexOf("revalidateTableForTwoData") < wiring.indexOf("TABLE_FOR_TWO_LIVE_REFRESH_INTERVAL_MS"),
    "must refresh on the live interval",
  );

  console.log("tft catalog revalidation ok");
})();
