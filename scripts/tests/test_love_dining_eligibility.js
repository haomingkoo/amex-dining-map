#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");

const { extractFunction: extractFrom } = require("./extract_function");
const extractFunction = (name) => extractFrom(source, name);

const context = {
  state: { loveDiningSourceMeta: {
    manual_review_required: true,
    records_reviewed_at: "2026-08-30T05:35:00Z",
    terms_reviewed_at: "2026-05-07T12:37:20Z",
  } },
  normalizeInlineText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  },
  formatSourceDate(value) {
    return value;
  },
  loveDiningTermsUrl() {
    return "https://www.americanexpress.com/terms.pdf";
  },
  loveDiningSourceUrl() {
    return "https://www.americanexpress.com/listing";
  },
};
vm.runInNewContext(
  `${extractFunction("singaporeTodayKey")}\n${extractFunction("loveDiningEligibilityState")}\n${extractFunction("loveDiningOrderProfile")}\n${extractFunction("loveDiningBenefitProfile")}\n${extractFunction("loveDiningBookingKeys")}\n${extractFunction("loveDiningBookingLabel")}\n${extractFunction("loveDiningReviewSummary")}\n${extractFunction("stayNameProfile")}\nObject.assign(globalThis, { loveDiningEligibilityState, loveDiningBenefitProfile, loveDiningBookingLabel, loveDiningReviewSummary, stayNameProfile });`,
  context,
);

assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "eligible", eligibility_effective_from: "2026-07-15" },
    "2026-08-30",
  ).key,
  "eligible",
);
const chifa = {
  id: "love-resorts-world-sentosa-chifa",
  name: "CHIFA!",
  type: "hotel",
  eligibility_status: "ineligible",
  eligibility_effective_from: "2026-08-01",
  notes: "Effective from 1 August 2026, CHIFA! will be permanently closed and will not be eligible for Love Dining privileges. Advanced reservations are required.",
  opening_hours: "12PM - 10PM",
};
const chifaBenefit = context.loveDiningBenefitProfile(chifa);
assert.strictEqual(chifaBenefit.maxSavingsPct, 0);
assert.strictEqual(
  chifaBenefit.savingsLabel,
  "Permanently closed · Not eligible since 2026-08-01",
);
assert.match(chifaBenefit.ladder, /No current Love Dining benefit/);
assert.strictEqual(context.loveDiningBookingLabel(chifa), "Not eligible");
assert.match(source, /record\.notes && !isUnavailable/);
assert.match(source, /record\.phone && !isUnavailable/);
assert.match(source, /record\.opening_hours && !isUnavailable/);
assert.match(source, /isUnavailable \? null : googleRating\(record\)/);
assert.match(source, /googleMapsUrl = isUnavailable/);
assert.strictEqual(
  context.loveDiningReviewSummary(),
  "venue list reviewed 2026-08-30T05:35:00Z · benefit terms reviewed 2026-05-07T12:37:20Z",
);
assert.match(source, /const markerLabel = isUnavailable \? "×" : ""/);
assert.match(source, /const markerTitle = isUnavailable \? "Unavailable venue" : record\.name/);
assert.match(source, /loveResultsText\.textContent = `\$\{n\} venue\$\{n === 1 \? "" : "s"\} shown · \$\{reviewedBaseline\}`/);

const crossroadsBenefit = context.loveDiningBenefitProfile({
  id: "love-paradox-singapore-crossroads-bar",
  name: "Crossroads Bar",
  type: "hotel",
  fixed_discount_percent: 20,
});
assert.strictEqual(crossroadsBenefit.maxSavingsPct, 20);
assert.strictEqual(crossroadsBenefit.savingsKey, "fixed");
assert.strictEqual(crossroadsBenefit.savingsLabel, "Last reviewed: 20% fixed rate");
const huaTingBenefit = context.loveDiningBenefitProfile({
  id: "love-orchard-hotel-singapore-hua-ting-restaurant",
  name: "Hua Ting Restaurant",
  type: "hotel",
  fixed_discount_percent: 35,
});
assert.strictEqual(huaTingBenefit.maxSavingsPct, 35);
assert.match(huaTingBenefit.savingsDetail, /fixed 35% /);
const ladderBenefit = context.loveDiningBenefitProfile({ id: "love-x-prego", name: "Prego", type: "hotel" });
assert.strictEqual(ladderBenefit.maxSavingsPct, 50);
assert.strictEqual(ladderBenefit.savingsKey, "fifty");
assert.doesNotMatch(source, /LOVE_DINING_FIXED_20_IDS/);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "ineligible", eligibility_effective_from: "2026-09-01" },
    "2026-08-30",
  ).key,
  "future_change",
);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { eligibility_status: "ineligible", eligibility_effective_from: "2026-09-01" },
    "2026-09-01",
  ).key,
  "ineligible",
);
assert.strictEqual(
  context.loveDiningEligibilityState(
    { notes: "Temporarily closed for renovation" },
    "2026-08-30",
  ).key,
  "review_required",
);
assert.strictEqual(
  context.stayNameProfile({ name: "Fraser Suites (From 8 May 2026)" }).eligibilityNote,
  "Eligible since 2026-05-08",
);
assert.strictEqual(
  context.stayNameProfile({ name: "W Hotel (From 1 June 2026)" }).eligibilityNote,
  "Eligible since 2026-06-01",
);
