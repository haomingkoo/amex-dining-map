#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

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

// The intro gate is a section chooser. A deep link already names its section, so
// arriving on one must land on the venue rather than the gold overlay.
// Derived, not pinned: this key has been bumped v1 -> v2 -> v3 already, and pinning
// the current value would fail this test on the next bump while nothing is wrong.
const INTRO_KEY = (app.match(/const INTRO_STORAGE_KEY = "([^"]+)";/) || [])[1];
assert.ok(INTRO_KEY, "web/app.js no longer declares INTRO_STORAGE_KEY");
assert.match(
  html,
  /id="intro-gate"[^>]*\shidden[\s>]/,
  "intro gate must start hidden in markup so skipping the gate leaves it closed",
);

function span(startNeedle, endNeedle, keepEnd = false) {
  const start = app.indexOf(startNeedle);
  assert.ok(start >= 0, `web/app.js no longer contains ${startNeedle}`);
  const end = app.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(end > start, `web/app.js no longer terminates ${startNeedle}`);
  return app.slice(start, keepEnd ? end + endNeedle.length : end);
}

// The ROUTES literal references module constants that have nothing to do with routing,
// so rebuild the lookup table from its real route keys instead of evaluating it.
const routeKeys = span("const ROUTES = {", "\n};").match(/^ {2}("?)[\w/-]+\1: \{$/gm) || [];
const routeIds = routeKeys.map((line) => line.trim().replace(/:\s*\{$/, "").replace(/^"|"$/g, ""));
for (const expected of ["dining/world", "stays", "love-dining", "table-for-two", "alerts"]) {
  assert.ok(routeIds.includes(expected), `route table no longer declares ${expected}`);
}

// The real init, gate and route resolver, run against stubs for the DOM and storage.
const harness = [
  span('const INTRO_STORAGE_KEY = "', "\n"),
  span("const PROGRAMS = {", "\n};", true),
  `const ROUTES = Object.fromEntries(${JSON.stringify(routeIds)}.map((id) => [id, { id }]));`,
  span("function normalizeRouteHash(", "\nfunction "),
  span("function resolveRouteFromHash(", "\nfunction "),
  span("function hashNamesSpecificRoute(", "\nfunction "),
  span("function showIntroGate(", "\nfunction "),
  span("async function init() {", "\n}\n", true),
  "this.init = init;",
].join("\n");

async function runInitialLoad({ hash, stored = null }) {
  const store = new Map(stored === null ? [] : [[INTRO_KEY, stored]]);
  const introGate = { hidden: true };
  const bodyClasses = new Set();
  const location = { hash };
  const routedTo = [];

  const context = {
    introGate,
    initTheme() {},
    loadUpdates: () => Promise.resolve(),
    loadSourceHealth: () => Promise.resolve(),
    staysCheckinInput: { min: "" },
    staysCheckoutInput: { min: "" },
    pocketDateFilter: { min: "" },
    pocketDateEndFilter: { min: "" },
    setToolbarOpen() {},
    setTableOpen() {},
    setStayToolbarOpen() {},
    setLoveToolbarOpen() {},
    handleHashRoute() {
      routedTo.push(location.hash);
    },
    document: {
      body: {
        classList: {
          add: (name) => bodyClasses.add(name),
          remove: (name) => bodyClasses.delete(name),
        },
      },
    },
    window: {
      location,
      history: {
        replaceState: (_state, _title, url) => {
          location.hash = url;
        },
      },
      localStorage: {
        getItem: (key) => (store.has(key) ? store.get(key) : null),
        setItem: (key, value) => store.set(key, value),
      },
    },
  };

  try {
    vm.runInNewContext(harness, context);
    await context.init();
  } catch (error) {
    // The error comes from the vm realm, so instanceof would not recognise it.
    if (error?.name !== "ReferenceError") throw error;
    throw new Error(
      `init() now depends on something this harness does not stub (${error.message}). `
      + "Add a stub for it to the context in runInitialLoad, then re-run.",
    );
  }

  return {
    gateVisible: introGate.hidden === false,
    scrollLocked: bodyClasses.has("intro-active"),
    storedIntro: store.has(INTRO_KEY) ? store.get(INTRO_KEY) : null,
    routedTo,
  };
}

async function main() {
  const deepLink = await runInitialLoad({ hash: "#/table-for-two?venue=tft-vue" });

  assert.equal(deepLink.gateVisible, false, "a deep link must not land on the section chooser");
  assert.equal(deepLink.scrollLocked, false, "skipping the gate must not leave the page scroll-locked");
  assert.deepEqual(
    deepLink.routedTo,
    ["#/table-for-two?venue=tft-vue"],
    "a deep link must route to the hash it named, parameters intact",
  );
  assert.equal(
    deepLink.storedIntro,
    null,
    "a skipped gate must not be recorded as seen, or the bare site would never offer the chooser",
  );

  const bareLoad = await runInitialLoad({ hash: "" });

  assert.equal(bareLoad.gateVisible, true, "a bare first load must still show the section chooser");
  assert.equal(bareLoad.scrollLocked, true, "the gate must still lock the page behind it");
  assert.deepEqual(bareLoad.routedTo, ["#/dining/world"], "a bare load must still land on the default route");

  const returningVisitor = await runInitialLoad({ hash: "", stored: "seen" });

  assert.equal(returningVisitor.gateVisible, false, "a returning visitor must not see the chooser again");
  assert.equal(returningVisitor.scrollLocked, false, "a returning visitor must not be scroll-locked");
  assert.equal(returningVisitor.storedIntro, "seen", "a returning visitor's stored state must be untouched");

  const returningDeepLink = await runInitialLoad({ hash: "#/stays", stored: "seen" });

  assert.equal(returningDeepLink.gateVisible, false, "a returning visitor's deep link must not show the chooser");
  assert.equal(returningDeepLink.storedIntro, "seen", "a deep link must not rewrite stored intro state");

  // Naming the default landing route, or naming nothing recognisable, is not a deep link:
  // both land on the same view the chooser sits in front of.
  for (const hash of ["#/dining/world", "#/", "#/dining", "#/not-a-real-route"]) {
    const landing = await runInitialLoad({ hash });
    assert.equal(landing.gateVisible, true, `${hash} resolves to the default view and must still show the chooser`);
  }

  for (const hash of ["#/stays", "#/love-dining", "#/dining/japan", "#/alerts", "#/tft"]) {
    const named = await runInitialLoad({ hash });
    assert.equal(named.gateVisible, false, `${hash} names a section and must skip the chooser`);
  }

  console.log("Initial load-path verification passed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
