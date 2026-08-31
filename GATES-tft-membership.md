# Gates: TFT active booking-project visibility

OWNS: scripts/verify-source-health.mjs, scripts/scrape_table_for_two.py, scripts/build_tft_slot_snapshot.py, scripts/build_tft_guide_catalog.py, scripts/tests/test_table_for_two_retry.py, scripts/tests/test_tft_booking_project_visibility.js, scripts/tests/test_tft_slot_snapshot.py, reminders/tests/test_tft_guide.py, scripts/verify-telegram-guide.mjs, web/app.js, data/table-for-two.json, data/table-for-two-slots.json, reminders/app/tft_guide_catalog.json

Scope: Keep non-current TFT booking-project venues out of active, alert, slot, and bot surfaces while retaining source-bounded historical evidence.

- [x] G1: missing booking-project members receive a non-operational booking status without being called permanently closed unless an official source says so
  CHECK: python3 -m pytest -q scripts/tests/test_table_for_two_retry.py && node scripts/tests/test_tft_booking_project_visibility.js && echo "TFT membership semantics passed"
  EXPECT: TFT membership semantics passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=16ff64417fe44df37cffbcfc5debcc6543eabbd3ebf064b6a17fa5f14583dd65; output-bytes=181

- [x] G2: inactive venues are absent from public slot and Telegram guide projections
  CHECK: python3 scripts/build_tft_slot_snapshot.py --check && python3 scripts/build_tft_guide_catalog.py --check && python3 -m pytest -q scripts/tests/test_tft_slot_snapshot.py reminders/tests/test_tft_guide.py && echo "TFT active projections passed"
  EXPECT: TFT active projections passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=52ad56b5bbb4d28aa7d446b03be5b3bdebc90ae2412140b82bc507f50960e9e0; output-bytes=189

- [x] G3: the complete project verification suite passes after the cross-surface change
  CHECK: node scripts/verify-project.mjs
  EXPECT: project verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=f5d0ddf1b39eea2ba15da76b8e6c2c5e4c2e9a576c3ac12ab6f7612d5567295c; output-bytes=28

- [ ] G4: production shows no stale availability cards for venues outside the current booking project and active venue checks are fresh
  EVIDENCE: pending
