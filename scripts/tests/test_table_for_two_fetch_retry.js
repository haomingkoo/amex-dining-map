#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/app.js", "utf8");
const start = source.indexOf("async function tableForTwoFetchWithRetry(");
const bodyStart = source.indexOf("{", start);
let depth = 0;
let end = -1;
for (let index = bodyStart; index < source.length; index += 1) {
  if (source[index] === "{") depth += 1;
  if (source[index] === "}") depth -= 1;
  if (depth === 0) {
    end = index + 1;
    break;
  }
}

let calls = 0;
const context = {
  AbortController,
  Promise,
  Set,
  TABLE_FOR_TWO_FETCH_RETRIES: 2,
  TABLE_FOR_TWO_FETCH_TIMEOUT_MS: 100,
  TABLE_FOR_TWO_RETRY_BASE_DELAY_MS: 0,
  fetch: async () => {
    calls += 1;
    return { status: calls === 1 ? 503 : 200 };
  },
  window: {
    setTimeout,
    clearTimeout,
  },
};

vm.runInNewContext(`${source.slice(start, end)}\nthis.retry = tableForTwoFetchWithRetry;`, context);

(async () => {
  const response = await context.retry("https://example.test", {});
  assert.strictEqual(response.status, 200);
  assert.strictEqual(calls, 2);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
