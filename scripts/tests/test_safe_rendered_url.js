#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`Missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

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
assert.strictEqual(context.safeRenderedUrl("http://evil.example", base), "");
assert.strictEqual(
  context.safeRenderedUrl("http://localhost:8000/healthz", base),
  "http://localhost:8000/healthz",
);

console.log("safe rendered URL verification passed");
