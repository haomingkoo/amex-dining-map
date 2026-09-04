#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");
const styles = fs.readFileSync("web/styles.css", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", source.indexOf(")", start));
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

const AVAILABLE = "#5fb9a6";
const context = {
  TFT_PIN_AVAILABLE: AVAILABLE,
  L: { divIcon: (opts) => opts },
};
vm.runInNewContext(
  `${extractFunction("clusterHasBookableVenue")}\n${extractFunction("createMarkerClusterIcon")}\n` +
    `globalThis.clusterHasBookableVenue = clusterHasBookableVenue;` +
    `globalThis.createMarkerClusterIcon = createMarkerClusterIcon;`,
  context,
);

const cluster = (colors) => ({
  getChildCount: () => colors.length,
  getAllChildMarkers: () => colors.map((pinColor) => ({ options: { pinColor } })),
});

// A cluster over bookable venues must not wear the "not bookable" colour.
assert.match(
  context.createMarkerClusterIcon(cluster([AVAILABLE, "#d6a44c", "#d6a44c"])).html,
  /benefit-cluster-available/,
  "a cluster containing a bookable venue must read as bookable",
);

// Nothing bookable inside, so the gold default is honest.
assert.doesNotMatch(
  context.createMarkerClusterIcon(cluster(["#d6a44c", "#c9a55a"])).html,
  /benefit-cluster-available/,
  "a cluster with no bookable venue keeps the default colour",
);

// Other programs' markers carry no pinColor, so their clusters are unchanged.
assert.doesNotMatch(
  context.createMarkerClusterIcon({
    getChildCount: () => 4,
    getAllChildMarkers: () => [{ options: {} }, { options: {} }],
  }).html,
  /benefit-cluster-available/,
  "markers without a pin colour must not change the cluster",
);

// Marker-cluster versions without getAllChildMarkers must not throw.
assert.doesNotMatch(
  context.createMarkerClusterIcon({ getChildCount: () => 2 }).html,
  /benefit-cluster-available/,
);

// The count still has to be rendered.
assert.match(context.createMarkerClusterIcon(cluster([AVAILABLE])).html, /<span>1<\/span>/);

// The bookable tone must resolve to the same token the legend calls "Bookable".
assert.match(
  styles,
  /\.marker-cluster\.benefit-marker-cluster \.benefit-cluster-inner\.benefit-cluster-available\s*\{[^}]*background:\s*var\(--teal\)/,
  "the bookable cluster must use the legend's available colour",
);
assert.match(
  styles,
  /\.legend-tft-available\s*\{\s*background:\s*var\(--teal\)/,
  "the legend's available swatch must stay var(--teal)",
);

console.log("cluster availability colour ok");
