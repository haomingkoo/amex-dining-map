#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const app = fs.readFileSync("web/app.js", "utf8");
const venues = [
  { name: "Park90", availability: { meals: [{ meal: "Dinner" }] } },
  { name: "Kee's", availability: { meals: [{ meal: "Lunch" }, { meal: "Afternoon Tea" }] } },
  { name: "New Venue", availability: { meals: [] } },
];
const context = { tableForTwoVenues: () => venues, Set, Array };
vm.runInNewContext(`${extractFunction(app, "tableForTwoOfferedMeals")}\nglobalThis.offered = tableForTwoOfferedMeals;`, context);

assert.deepEqual([...context.offered(["Park90"])], ["Dinner"]);
assert.deepEqual([...context.offered(["Park90", "Kee's"])].sort(), ["Afternoon Tea", "Dinner", "Lunch"]);
// Any venue, or a venue without known meals, must not restrict the choice.
assert.equal(context.offered([]), null);
assert.equal(context.offered(["Park90", "New Venue"]), null);
assert.equal(context.offered(["Gone Venue"]), null);

console.log("alert form offered meals tests passed");
