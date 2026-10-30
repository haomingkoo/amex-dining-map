#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

const context = { URL };
vm.runInNewContext(
  `${extractFunction("safeRenderedUrl")}\nObject.assign(globalThis, { safeRenderedUrl });`,
  context,
);

const base = "https://amex-explorer.kooexperience.com/#/table-for-two";
assert.strictEqual(context.safeRenderedUrl("javascript:alert(1)", base), "");
assert.strictEqual(context.safeRenderedUrl("data:text/html,boom", base), "");
assert.strictEqual(context.safeRenderedUrl("//evil.example/x", base), "https://evil.example/x");
assert.strictEqual(context.safeRenderedUrl("#/table-for-two", base), "#/table-for-two");
assert.strictEqual(
  context.safeRenderedUrl("/data/table-for-two.json", base),
  "https://amex-explorer.kooexperience.com/data/table-for-two.json",
);
// Images load inside the page, so plain http would be mixed content.
assert.strictEqual(context.safeRenderedUrl("http://evil.example/a.jpg", base), "");
// Links open the restaurant's own site; many Japan and Global venues only serve http.
assert.strictEqual(
  context.safeRenderedUrl("http://french-kitamura.jp/", base, { allowHttp: true }),
  "http://french-kitamura.jp/",
);
assert.strictEqual(context.safeRenderedUrl("javascript:alert(1)", base, { allowHttp: true }), "");
assert.match(source, /safeRenderedUrl\(value, window\.location\.href, \{\s*allowHttp: element instanceof HTMLAnchorElement/);
assert.strictEqual(
  context.safeRenderedUrl("http://localhost:8000/healthz", base),
  "http://localhost:8000/healthz",
);

console.log("safe rendered URL verification passed");
