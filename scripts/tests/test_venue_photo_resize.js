#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("web/app.js", "utf8");
const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(app, name);


const constants = app.match(/const DININGCITY_IMAGE_HOST[\s\S]*?const TABLE_FOR_TWO_PHOTO_WIDTH_PX = \d+;/)[0];
const context = { URL };
vm.runInNewContext(`${constants}\n${extractFunction("resizedDiningCityImageUrl")}\nglobalThis.resize = resizedDiningCityImageUrl;`, context);

// DiningCity photos, with or without an empty query, get a resized WebP variant.
assert.equal(
  context.resize("https://static-assets.diningcity.asia/awmom16ev1ayqfgy895grzh01fz5?"),
  "https://static-assets.diningcity.asia/awmom16ev1ayqfgy895grzh01fz5?imageView2/2/w/720/format/webp",
);
assert.equal(
  context.resize("https://static-assets.diningcity.asia/restaurantpictures/2020/a.JPG"),
  "https://static-assets.diningcity.asia/restaurantpictures/2020/a.JPG?imageView2/2/w/720/format/webp",
);

// Other hosts, existing queries, and empty values pass through unchanged.
assert.equal(context.resize("https://example.com/a.jpg"), "https://example.com/a.jpg");
assert.equal(
  context.resize("https://static-assets.diningcity.asia/a.jpg?v=2"),
  "https://static-assets.diningcity.asia/a.jpg?v=2",
);
assert.equal(context.resize(""), "");

// The photo tag reserves its box and defers loading.
assert.match(app, /class="tft-venue-photo"[^>]*loading="lazy" decoding="async"/);

console.log("venue photo resize tests passed");
