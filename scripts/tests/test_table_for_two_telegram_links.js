#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/app.js", "utf8");
const start = source.indexOf("function tableForTwoTelegramDeepLink(");
const end = source.indexOf("\nfunction ", start + 10);
assert.ok(start >= 0 && end > start, "Telegram deep-link helper not found");

const context = {
  state: {
    telegramGuideConfig: {
      schema_version: 1,
      enabled: true,
      bot_username: "KooTftGuideBot",
    },
  },
};
vm.runInNewContext(
  `${source.slice(start, end)}\nthis.deepLink = tableForTwoTelegramDeepLink;`,
  context,
);

assert.equal(
  context.deepLink("venue", { id: "tft-vue" }),
  "https://t.me/KooTftGuideBot?start=venue_tft-vue",
);
assert.equal(
  context.deepLink("remind", { id: "tft-vue" }),
  "https://t.me/KooTftGuideBot?start=remind_tft-vue",
);
assert.equal(context.deepLink("owner", { id: "tft-vue" }), "");
assert.equal(context.deepLink("venue", { id: "../../etc/passwd" }), "");
context.state.telegramGuideConfig.bot_username = "https://attacker.example";
assert.equal(context.deepLink("venue", { id: "tft-vue" }), "");
context.state.telegramGuideConfig = { schema_version: 1, enabled: false, bot_username: "KooTftGuideBot" };
assert.equal(context.deepLink("venue", { id: "tft-vue" }), "");

assert.match(source, />Ask on Telegram<\/a>/);
assert.match(source, />Set Telegram reminder<\/a>/);
console.log("Table for Two Telegram link verification passed");
