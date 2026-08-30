#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");

const init = app.slice(app.indexOf("async function init()"), app.indexOf("searchInput.addEventListener"));
assert.match(init, /void Promise\.all\(\[loadUpdates\(\), loadSourceHealth\(\)\]\);/);
assert.doesNotMatch(init, /await Promise\.all\(\[loadUpdates\(\), loadSourceHealth\(\)\]\)/);

const appPreload = html.indexOf('<link rel="preload" as="script" href="./app.js?v=dev"');
const appExecution = html.lastIndexOf('<script src="./app.js?v=dev"');
assert.ok(appPreload >= 0 && appPreload < appExecution, "app bundle must be preloaded before execution");
assert.match(html, /rel="preconnect" href="https:\/\/unpkg\.com"/);
assert.match(html, /rel="preload"[\s\S]*leaflet@1\.9\.4\/dist\/leaflet\.js/);
assert.match(html, /rel="preload"[\s\S]*leaflet\.markercluster@1\.5\.3/);

console.log("Initial load-path verification passed");
