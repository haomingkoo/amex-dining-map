# Ready to Run: Phases 2-4

Everything is ready. Here's what to do.

---

## 1. Install Dependencies (One-time)

```bash
pip install playwright geopy
playwright install
```

---

## 2. Run the Phases

Copy-paste each command. Wait for test to pass before moving to next phase.

### Phase 2: Global Dining

```bash
python3 scripts/scrape_amex_global_dining_official.py && python3 scripts/test_phase_2_global_dining.py
```

**Expected**: 
- Extraction: ~2,000 restaurants
- Test: 12/12 pass

### Phase 3: Plat Stay

```bash
python3 scripts/scrape_amex_plat_stay_official.py && python3 scripts/test_phase_3_plat_stay.py
```

**Expected**:
- Extraction: 69 properties
- Test: 9/9 pass

### Phase 4: Love Dining (CRITICAL)

```bash
python3 scripts/scrape_amex_love_dining_official.py && python3 scripts/test_phase_4_love_dining.py
```

**Expected**:
- Extraction: 79 venues, ALL with coordinates
- Test: 8/8 pass

---

## 3. If Tests FAIL

**Don't proceed to next phase.** Test output shows exactly what's wrong.

Example failures:
- "Count suspicious: 1,850 (expected 2,000)" → extraction missed venues
- "CRITICAL FAIL: 10 records missing coordinates" → geocoding failed
- "Duplicate IDs found" → unique ID generation broken

Fix the extraction script → re-run extraction + test.

---

## 4. After Phase 4 PASSES

Run final validation:

```bash
python3 scripts/test_regression_data_integrity.py && python3 scripts/data_sanity_check.py --strict
```

If both pass → ready to deploy.

---

## Files Ready to Run

| File | Purpose | Ready? |
|------|---------|--------|
| `scripts/scrape_amex_global_dining_official.py` | Phase 2 extraction | ✅ |
| `scripts/test_phase_2_global_dining.py` | Phase 2 test | ✅ |
| `scripts/scrape_amex_plat_stay_official.py` | Phase 3 extraction | ✅ |
| `scripts/test_phase_3_plat_stay.py` | Phase 3 test | ✅ |
| `scripts/scrape_amex_love_dining_official.py` | Phase 4 extraction | ✅ |
| `scripts/test_phase_4_love_dining.py` | Phase 4 test | ✅ |
| `scripts/verify_restaurant_coordinates.py` | Optional: verify all coords | ✅ |
| `EXECUTION_PHASES_2_4.md` | Detailed guide | ✅ |

---

## Timeline

- Phase 2: 10 min (extraction + test)
- Phase 3: 5 min
- Phase 4: 5 min
- Final validation: 3 min
- **Total: ~25 minutes** (or 1-2 hours if any test fails and needs fixing)

---

## Next: What Happens at Each Test

### Phase 2 Test: 12 checks
1. File exists
2. Valid JSON (list, non-empty)
3. All required fields (id, name, country, city)
4. Zero duplicate IDs
5. Count 1,900–2,100
6. All 16 countries present
7. Distribution 5–25% per country
8. 90%+ have coordinates
9. All coordinates within bounds (-90/+90, -180/+180)
10. **GPS bounds**: coordinates within country geographic bounds
11. No validation failures
12. Audit trail exists

### Phase 3 Test: 9 checks
1. File exists
2. Exactly 69 properties
3. All required fields
4. Zero duplicates
5. 100% have coordinates
6. Coordinates valid
7. Distribution reasonable
8. Addresses populated
9. Geocoding confidence tracked

### Phase 4 Test: 8 checks (CRITICAL)
1. File exists
2. Exactly 79 venues
3. All required fields
4. Zero duplicates
5. **100% have coordinates** ← CRITICAL
6. Within Singapore bounds
7. Coordinate types valid
8. Restaurant/hotel mix

---

## Troubleshooting

**Test fails immediately?**
- Check error message — it's very specific
- Common: "File not found" → extraction didn't run or crashed
- Common: "Count wrong" → extraction found different number
- Common: "Missing coordinates" → geocoding failed

**Extraction hangs?**
- Nominatim rate limit — add delays between requests
- Playwright timeout — increase timeout in script

**Coordinates invalid?**
- Check if address is spelled correctly in source
- Test address on nominatim.openstreetmap.org
- Fix address in source, re-run extraction

---

## One More Thing

After Phase 4 passes, you can optionally verify all restaurant coordinates are accurate:

```bash
python3 scripts/verify_restaurant_coordinates.py --all --threshold 5
```

This reverse-geocodes all venues to catch extraction errors. Takes ~10 minutes, fully local, zero API costs.

---

**That's it. Run the commands. Tests will tell you if anything is wrong.**
