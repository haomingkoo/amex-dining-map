#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

const context = {};
vm.runInNewContext(
  `${extractFunction("pocketConciergeUrl")}\nObject.assign(globalThis, { pocketConciergeUrl });`,
  context,
);

assert.strictEqual(
  context.pocketConciergeUrl({
    id: "pocket-244500",
    source_url: "https://pocket-concierge.jp/en/restaurants/244500/",
  }),
  "https://pocket-concierge.jp/en/restaurants/244500/",
);
assert.strictEqual(
  context.pocketConciergeUrl({ id: "pocket-244500" }),
  "https://pocket-concierge.jp/en/restaurants/244500/",
);
assert.strictEqual(context.pocketConciergeUrl({ id: "amex-global-singapore-vue" }), "");
assert.strictEqual(
  context.pocketConciergeUrl({
    id: "love-the-cliff",
    source_url: "https://www.americanexpress.com/sg/benefits/love-dining/love-restaurants.html",
  }),
  "",
);
