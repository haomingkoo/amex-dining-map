# Gates: TFT active booking-project visibility

OWNS: scripts/verify-source-health.mjs, scripts/scrape_table_for_two.py, scripts/build_tft_slot_snapshot.py, scripts/build_tft_guide_catalog.py, scripts/tests/test_table_for_two_retry.py, scripts/tests/test_tft_booking_project_visibility.js, scripts/tests/test_tft_slot_snapshot.py, reminders/tests/test_tft_guide.py, scripts/verify-telegram-guide.mjs, web/app.js, data/table-for-two.json, data/table-for-two-slots.json, reminders/app/tft_guide_catalog.json

Scope: Keep non-current TFT booking-project venues out of active, alert, slot, and bot surfaces while retaining source-bounded historical evidence.

- [x] G1: missing booking-project members receive a non-operational booking status without being called permanently closed unless an official source says so
  CHECK: python3 -m pytest -q scripts/tests/test_table_for_two_retry.py && node scripts/tests/test_tft_booking_project_visibility.js && echo "TFT membership semantics passed"
  EXPECT: TFT membership semantics passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=ceda58bd231926cc3f58283db74865d052889b57974a09cfc7cc88421577bde7; output-bytes=181

- [x] G2: inactive venues are absent from public slot and Telegram guide projections
  CHECK: python3 scripts/build_tft_slot_snapshot.py --check && python3 scripts/build_tft_guide_catalog.py --check && python3 -m pytest -q scripts/tests/test_tft_slot_snapshot.py reminders/tests/test_tft_guide.py && echo "TFT active projections passed"
  EXPECT: TFT active projections passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=3708e4c7324db5b932521dba535cc3664f4843c62964f27d03fbdf97c3cdd8c4; output-bytes=189

- [x] G3: the complete project verification suite passes after the cross-surface change
  CHECK: node scripts/verify-project.mjs
  EXPECT: project verification passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/koohaoming/dev/amex-dining-map; path=db7d51c629d2/23 entries; EXPECT=matched; output-sha256=f5d0ddf1b39eea2ba15da76b8e6c2c5e4c2e9a576c3ac12ab6f7612d5567295c; output-bytes=28

- [x] G4: production shows no stale availability cards for venues outside the current booking project and active venue checks are fresh
  EVIDENCE: 2026-09-01 production Chrome verification after Pages run 33415818885 showed 21 active cards, zero stale labels, no active Osteria or Capitol card, no console errors, an evidence-only Capitol page with official permanent-closure wording, and an evidence-only Osteria page that does not call the restaurant closed; both historical pages disable alerts and reminders.
