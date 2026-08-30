#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const source = fs.readFileSync("web/app.js", "utf8");
const focusHelper = source.match(
  /function focusClusteredMarkerOnMap[\s\S]*?\n}\n\nfunction addThemedTileLayer/
)?.[0];

assert.ok(focusHelper, "clustered marker focus helper should exist");
assert.ok(
  !focusHelper.includes("zoomToShowLayer"),
  "marker focus must not start a second marker-cluster zoom transaction"
);
assert.ok(focusHelper.includes("smartZoomToMarker"));
assert.ok(focusHelper.includes("openMarkerPopupAfterMove"));

console.log("marker cluster focus regression test passed");
