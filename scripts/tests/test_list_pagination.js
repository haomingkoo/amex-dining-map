#!/usr/bin/env node
// Long lists reveal in batches: a count line, one "Show N more" button, and focus on the first new item.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { extractFunction } = require("./extract_function");

const app = fs.readFileSync("web/app.js", "utf8");
const html = fs.readFileSync("web/index.html", "utf8");
const css = fs.readFileSync("web/styles.css", "utf8");

const context = { Math, Number, String };
vm.runInNewContext(
  `${["listRangeLabel", "listMoreLabel", "listShownCount"].map((name) => extractFunction(app, name)).join("\n")}
   Object.assign(globalThis, { listRangeLabel, listMoreLabel, listShownCount });`,
  context,
);
const restaurants = ["restaurant", "restaurants"];

// 1. The count says which slice is on screen and how many exist in total.
assert.equal(context.listRangeLabel(10, 30, restaurants), "Showing 1–10 of 30 restaurants");
assert.equal(context.listRangeLabel(30, 30, restaurants), "Showing all 30 restaurants");
assert.equal(context.listRangeLabel(10, 1, restaurants), "Showing 1 restaurant");
assert.equal(context.listRangeLabel(8, 1205, ["change", "changes"]), "Showing 1–8 of 1,205 changes");

// 2. The button names the next batch, never more than what remains.
assert.equal(context.listMoreLabel(20, 10), "Show 10 more");
assert.equal(context.listMoreLabel(3, 10), "Show 3 more");

// 3. A filter change starts again at one page; the same filters keep the reader's place.
assert.equal(context.listShownCount({ shown: 30, pageSize: 10, keyChanged: true, activeIndex: -1 }), 10);
assert.equal(context.listShownCount({ shown: 30, pageSize: 10, keyChanged: false, activeIndex: -1 }), 30);
assert.equal(context.listShownCount({ shown: 0, pageSize: 10, keyChanged: false, activeIndex: -1 }), 10);
// 4. A selected venue (map pin, deep link) is always on screen: its batch is revealed.
assert.equal(context.listShownCount({ shown: 10, pageSize: 10, keyChanged: false, activeIndex: 24 }), 30);
assert.equal(context.listShownCount({ shown: 10, pageSize: 10, keyChanged: true, activeIndex: 9 }), 10);
assert.equal(context.listShownCount({ shown: 10, pageSize: 10, keyChanged: true, activeIndex: 10 }), 20);

// 5. One footer helper renders the count and button for every batched list.
const footer = extractFunction(app, "renderListMore");
assert.match(footer, /listRangeLabel\(/);
assert.match(footer, /listMoreLabel\(/);
assert.match(footer, /aria-describedby/);
const focus = extractFunction(app, "focusRevealedItem");
// 6. Focus lands on the first newly revealed item, without smooth scrolling under reduced motion.
assert.match(focus, /preventScroll: true/);
assert.match(focus, /prefers-reduced-motion: reduce/);

// 7. Changes feed: 8 at a time, in both the main list and the corrections list.
assert.match(app, /const UPDATES_PAGE_SIZE = 8;/);
assert.match(html, /<div class="list-more" id="updates-more" hidden><\/div>/);
assert.match(html, /<div class="list-more" id="updates-secondary-more" hidden><\/div>/);
assert.match(extractFunction(app, "renderUpdatePage"), /renderListMore\(/);

// 8. Table for Two list: 10 at a time; filters and search still run on the full set before slicing.
assert.match(app, /const TABLE_FOR_TWO_PAGE_SIZE = 10;/);
const tftList = extractFunction(app, "renderTableForTwoList");
assert.match(tftList, /state\.tableForTwoFiltered\.slice\(0, shown\)/);
assert.match(tftList, /renderListMore\(/);
const tftFilter = extractFunction(app, "filterTableForTwo");
assert.match(tftFilter, /state\.tableForTwoListKey/);
// The map keeps every filtered pin; only the list is batched.
assert.doesNotMatch(extractFunction(app, "renderTableForTwoMarkers"), /tableForTwoShown/);

// 9. Love Dining and dining phone lists use the same footer.
assert.match(extractFunction(app, "renderLoveDiningMobileList"), /renderListMore\(/);
assert.match(extractFunction(app, "renderMobileCards"), /renderListMore\(/);

// 10. Styling: the button uses gold (teal means bookable only), meets the 44px target, and shows the shared focus ring.
const rule = (selector) => {
  const match = css.match(new RegExp(`(^|\\n)${selector.replace(/[.]/g, "\\.")} \\{([^}]*)\\}`));
  assert.ok(match, `Missing ${selector}`);
  return match[2];
};
assert.match(rule(".list-more-button"), /min-height: 44px/);
assert.doesNotMatch(rule(".list-more-button"), /teal/);
assert.match(css, /\.list-more-button:focus-visible \{[^}]*var\(--focus-color\)/);
assert.match(rule(".list-more-count"), /tabular-nums/);

// 11. No em dashes in the new copy.
for (const name of ["listRangeLabel", "listMoreLabel", "renderListMore"]) {
  assert.doesNotMatch(extractFunction(app, name), /—/);
}

console.log("list pagination verification passed");
