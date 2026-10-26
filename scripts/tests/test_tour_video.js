#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");

const html = fs.readFileSync("web/index.html", "utf8");
const app = fs.readFileSync("web/app.js", "utf8");

// The CSP must allow same-origin video, or the tour player stays blank.
const csp = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)[1];
assert.match(csp, /media-src 'self'/);

// The player never autoplays and loads nothing until asked.
const dialog = html.match(/<dialog[^>]*id="tour-dialog"[\s\S]*?<\/dialog>/)[0];
assert.doesNotMatch(dialog, /autoplay/);
assert.match(dialog, /preload="none"/);
assert.match(dialog, /aria-label="Close tour"/);
assert.match(dialog, /Music: Sascha Ende, ende\.app \(CC BY 4\.0\)/);

// Every asset the player references ships with the site.
for (const [, src] of dialog.matchAll(/(?:src|poster)="\.\/(media\/[^"]+)"/g)) {
  assert.ok(fs.existsSync(`web/${src}`), `missing web/${src}`);
}

// The README tour link depends on the ?tour=1 deep link.
assert.match(app, /get\("tour"\) === "1"\) openTour\(\)/);

console.log("tour video checks passed");
