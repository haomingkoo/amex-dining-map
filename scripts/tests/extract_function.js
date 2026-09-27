// Shared by the web unit tests: slice one top-level function out of web/app.js.
const assert = require("node:assert/strict");

function extractFunction(source, name) {
  const plain = source.indexOf(`function ${name}(`);
  assert.ok(plain >= 0, `Missing ${name}`);
  const isAsync = source.slice(plain - "async ".length, plain) === "async ";
  const start = isAsync ? plain - "async ".length : plain;
  const bodyStart = source.indexOf("{", source.indexOf(")", plain));
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Unclosed ${name}`);
}

module.exports = { extractFunction };
