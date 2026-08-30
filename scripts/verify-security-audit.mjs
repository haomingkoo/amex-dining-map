#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const audit = read("SECURITY_AUDIT.md");
const routes = read("reminders/app/routes.py");
const database = read("reminders/app/db.py");
const emailer = read("reminders/app/emailer.py");
const security = read("reminders/app/security.py");
const frontend = read("web/app.js");
const workflows = fs.readdirSync(path.join(root, ".github/workflows"))
  .filter((name) => name.endsWith(".yml") || name.endsWith(".yaml"))
  .map((name) => read(`.github/workflows/${name}`))
  .join("\n");

for (const scope of [
  "public static explorer",
  "GitHub Actions",
  "FastAPI/SQLite reminder service",
  "dependencies",
  "Telegram ingress",
]) {
  assert.ok(audit.includes(scope), `Audit is missing scope: ${scope}`);
}
assert.ok(audit.includes("No secret was detected"));
assert.ok(!/unresolved critical/i.test(audit));

const shellInjection = /\beval\s+(?:python|bash|sh)|run:\s*[^\n]*\$\{\{\s*(?:inputs|github\.event\.inputs)\./;
assert.ok(shellInjection.test("run: eval python ${{ inputs.value }}"), "Injection control must detect a known bad fixture");
assert.ok(!shellInjection.test(workflows), "Workflow input still reaches an unsafe shell form");

const actionLines = workflows.split("\n").filter((line) => /uses:\s+actions\//.test(line));
assert.ok(actionLines.length > 0, "No GitHub-owned actions were inspected");
for (const line of actionLines) {
  assert.match(line, /uses:\s+actions\/[\w-]+@[0-9a-f]{40}(?:\s+#\s+v\d+)?\s*$/);
}

assert.ok(routes.includes("db.consume_rate_limits("));
assert.ok(routes.includes('@router.post("/api/confirm"'));
assert.ok(routes.includes('@router.post("/api/unsubscribe"'));
assert.ok(database.includes("pending_subscriber_changes"));
assert.ok(database.includes("status = 'active'"));
assert.ok(database.includes("os.chmod(path, 0o600)"));
assert.ok(emailer.includes("escape(name)"));
assert.ok(security.includes('headers["Cache-Control"] = "no-store"'));
assert.ok(security.includes("RequestBodyLimitMiddleware"));
assert.ok(frontend.includes("safeRenderedUrl"));
assert.ok(frontend.includes("javascript:alert(1)") === false);

console.log("security audit verification passed");
