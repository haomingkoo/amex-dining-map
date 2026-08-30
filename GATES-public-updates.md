# Gates: diner-focused public updates

OWNS: GATES-public-updates.md, docs/superpowers/plans/2026-08-31-public-updates.md, web/app.js, web/index.html, web/styles.css, reminders/tests/test_tft_guide.py, scripts/tests/test_public_updates_ui.js, scripts/tests/test_source_health_ui.js, scripts/tests/test_table_for_two_deep_link.js, scripts/tests/test_tft_slot_snapshot.py

Scope: Public visitors see confirmed restaurant and menu changes first, while source diagnostics remain available in plain language without taking over the primary update message.

- [x] G0: this scoped ledger has valid and reviewable acceptance oracles
  CHECK: node /Users/koohaoming/.codex/skills/unlazy/scripts/gate-lint.mjs GATES-public-updates.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=5c7117a7939095b2ccfb89182f9369e286aaf368de1c19b8eb308f32d23bae5b; output-bytes=438

- [x] G1: the public update trigger summarizes only confirmed diner-relevant changes and never promotes source lifecycle events
  CHECK: node scripts/tests/test_public_updates_ui.js
  EXPECT: Public updates UI verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=ff3af9e47c854cd5e22560d34a7cebc1461b913d0ee485487289065e63498e05; output-bytes=38

- [x] G2: menu change details hide hashes and version fingerprints while preserving reviewed before-and-after content and official links
  CHECK: node scripts/tests/test_public_updates_ui.js
  EXPECT: Public updates UI verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=ff3af9e47c854cd5e22560d34a7cebc1461b913d0ee485487289065e63498e05; output-bytes=38

- [x] G3: source status is progressively disclosed after confirmed changes and uses plain language for visitor-impacting uncertainty
  CHECK: node scripts/tests/test_public_updates_ui.js
  EXPECT: Public updates UI verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=ff3af9e47c854cd5e22560d34a7cebc1461b913d0ee485487289065e63498e05; output-bytes=38

- [x] G4: the complete project regression suite passes after the information-hierarchy change
  CHECK: node scripts/verify-project.mjs
  EXPECT: project verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=f5d0ddf1b39eea2ba15da76b8e6c2c5e4c2e9a576c3ac12ab6f7612d5567295c; output-bytes=28

- [x] G5: the deployed 390-pixel mobile journey leads with confirmed additions, removals, and menu changes, keeps data freshness collapsed by default, and has no horizontal overflow or application error
  EVIDENCE: 2026-08-31 Pages run 33326979634 deployed eb2a7b7. Production at 390x844 showed 8 restaurants added, 2 restaurants removed, and 2 menus changed across two visible headline lines; the 12 primary rows led with Tajimaya Yakiniku, 8 lower-priority corrections and Data freshness were collapsed, TANOKE retained reviewed semantic before-and-after menu details without hashes, document scroll width equalled the 390-pixel viewport, and the updates panel contained no application error state.
