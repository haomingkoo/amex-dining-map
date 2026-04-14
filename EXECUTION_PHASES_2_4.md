# Phase 2-4 Execution Guide

**Goal**: Rebuild Global Dining, Plat Stay, and Love Dining with mandatory tests.

**Timeline**: ~2-3 hours total (includes extraction + testing + verification)

---

## Prerequisites

```bash
# Install required packages
pip install playwright geopy

# Install Playwright browsers
playwright install
```

---

## Phase 2: Global Dining (2,000 restaurants)

### Step 1: Run Extraction

```bash
python3 scripts/scrape_amex_global_dining_official.py
```

**Expected output**:
- File: `data/rebuilt/global-restaurants-REBUILT.json`
- ~2,000 restaurants extracted
- All with coordinates from official AMEX page

### Step 2: Run Mandatory Test (TEST GATE)

```bash
python3 scripts/test_phase_2_global_dining.py
```

**Must pass all 12 tests**:
- ✅ File exists
- ✅ Valid JSON (non-empty list)
- ✅ All required fields (id, name, country, city)
- ✅ Zero duplicate IDs
- ✅ Count within 2,000 ±5% (1,900–2,100)
- ✅ All 16 countries represented
- ✅ Distribution sanity (5–25% per country)
- ✅ 90%+ have coordinates
- ✅ All coordinates within bounds (-90/+90, -180/+180)
- ✅ **GPS BOUNDS CHECK**: Coordinates within country geographic bounds
- ✅ No validation failures
- ✅ Audit trail generated

**If FAIL**: Stop, fix extraction, re-run both commands.

**If PASS**: Proceed to Phase 3.

---

## Phase 3: Plat Stay (69 properties)

### Step 1: Run Extraction

```bash
python3 scripts/scrape_amex_plat_stay_official.py
```

**Expected output**:
- File: `data/rebuilt/plat-stays-REBUILT.json`
- Exactly 69 properties
- All with coordinates and addresses

### Step 2: Run Mandatory Test (TEST GATE)

```bash
python3 scripts/test_phase_3_plat_stay.py
```

**Must pass all 9 tests**:
- ✅ File exists
- ✅ Exactly 69 properties (no variance)
- ✅ All required fields
- ✅ Zero duplicate IDs
- ✅ 100% coordinate coverage (all 69 have coordinates)
- ✅ All coordinates valid
- ✅ Country distribution reasonable
- ✅ All addresses populated
- ✅ Geocoding confidence tracked

**If FAIL**: Stop, fix extraction, re-run both commands.

**If PASS**: Proceed to Phase 4.

---

## Phase 4: Love Dining (79 Singapore venues) — CRITICAL

### Step 1: Run Extraction

```bash
python3 scripts/scrape_amex_love_dining_official.py
```

**Expected output**:
- File: `data/rebuilt/love-dining-REBUILT.json`
- Exactly 79 venues
- **ALL 79 MUST HAVE COORDINATES** ← CRITICAL

### Step 2: Run Mandatory Test (TEST GATE)

```bash
python3 scripts/test_phase_4_love_dining.py
```

**Must pass all 8 tests**:
- ✅ File exists
- ✅ Exactly 79 venues
- ✅ All required fields (id, name, city, address, type)
- ✅ Zero duplicate IDs
- ✅ **100% coordinate coverage** (ALL 79 have lat/lng) ← CRITICAL
- ✅ All coordinates within Singapore bounds (1.0–1.6°N, 103.5–104.2°E)
- ✅ Coordinate types valid (numeric)
- ✅ Mix of restaurants + hotels

**If FAIL**: Stop, fix extraction, re-run both commands.

**If PASS**: All extraction complete. Proceed to Phase 5 (validation).

---

## Test Gate Summary

| Phase | Extraction | Test | Must Pass |
|-------|-----------|------|-----------|
| 2 | `scrape_amex_global_dining_official.py` | `test_phase_2_global_dining.py` | 12/12 tests |
| 3 | `scrape_amex_plat_stay_official.py` | `test_phase_3_plat_stay.py` | 9/9 tests |
| 4 | `scrape_amex_love_dining_official.py` | `test_phase_4_love_dining.py` | 8/8 tests (CRITICAL: 100% coords) |

**STOP if any test fails. Do NOT proceed to next phase.**

---

## Success Criteria

### Phase 2 (Global Dining)
```
✅ PASS if:
  - 1,900–2,100 restaurants
  - Zero duplicate IDs
  - 16 countries represented
  - 90%+ have coordinates
  - All coordinates within bounds
  - All coordinates within country GPS bounds
```

### Phase 3 (Plat Stay)
```
✅ PASS if:
  - Exactly 69 properties
  - Zero duplicate IDs
  - 100% have coordinates
  - All coordinates within bounds
  - All addresses populated
```

### Phase 4 (Love Dining)
```
✅ PASS if:
  - Exactly 79 venues
  - 100% have coordinates ← CRITICAL
  - Zero duplicate IDs
  - All coordinates in Singapore bounds
  - Mix of restaurants + hotels
```

---

## Next Steps After Phase 4 PASSES

1. **Run regression test on current production data**:
   ```bash
   python3 scripts/test_regression_data_integrity.py
   ```
   This confirms no accidental corruption of existing Japan data.

2. **Run pre-deployment validation**:
   ```bash
   python3 scripts/data_sanity_check.py --strict
   ```
   This checks cross-dataset integrity (no orphaned ratings, etc).

3. **Optional: Automated coordinate verification**:
   ```bash
   python3 scripts/verify_restaurant_coordinates.py --dataset global --threshold 5
   ```
   Reverse-geocodes coordinates to catch extraction errors.

4. **Manual spot-checks** (50 venues per dataset):
   - Pick 5 random venues from each country
   - Verify on Google Maps and AMEX official pages
   - Check location accuracy (should be within 100m of Google)

5. **Deploy to production** (only if all checks pass):
   ```bash
   git checkout main
   git pull origin main
   git checkout feat/data-rebuild
   git merge main
   # Copy rebuilt files to production location
   cp data/rebuilt/global-restaurants-REBUILT.json data/global-restaurants.json
   cp data/rebuilt/plat-stays-REBUILT.json data/plat-stays.json
   cp data/rebuilt/love-dining-REBUILT.json data/love-dining.json
   git add data/
   git commit -m "feat: rebuild global dining, plat stay, love dining with validation"
   git push origin feat/data-rebuild
   # Create PR for review
   ```

---

## Troubleshooting

### Extraction runs but test fails

1. **Check the error message** — test output shows exactly what failed
2. **Example**: "Count suspicious: 1,850 (expected ~2,000)"
   - Extraction script didn't find all restaurants
   - Check AMEX page structure (may have changed)
   - Update scraper if needed
3. **Fix extraction script**, re-run both extraction + test

### Geocoding fails

1. **Too many requests** → Nominatim has rate limits
   - Add `time.sleep(1)` between requests
   - Use `--throttle` flag if available
2. **Nominatim timeout** → Retry manually
3. **Invalid coordinates** → Check if address is correct

### 100% coordinate requirement fails (Phase 4)

This is CRITICAL. If any Love Dining venue doesn't have coordinates:
1. Check if address is valid (typo?)
2. Try manual lookup on Google Maps
3. Use Nominatim directly to test address format
4. Fix address in source data, re-run extraction

---

## Estimated Times

| Task | Duration |
|------|----------|
| Phase 2 extraction | 10 min |
| Phase 2 test | 30 sec |
| Phase 3 extraction | 5 min |
| Phase 3 test | 10 sec |
| Phase 4 extraction | 5 min |
| Phase 4 test | 10 sec |
| Regression test | 5 sec |
| Pre-deployment validation | 2 min |
| **Total** | **~25 minutes** |
| +Manual spot-checks | **~1 hour** |

---

## Commands at a Glance

```bash
# Phase 2
python3 scripts/scrape_amex_global_dining_official.py && \
python3 scripts/test_phase_2_global_dining.py

# Phase 3
python3 scripts/scrape_amex_plat_stay_official.py && \
python3 scripts/test_phase_3_plat_stay.py

# Phase 4 (CRITICAL)
python3 scripts/scrape_amex_love_dining_official.py && \
python3 scripts/test_phase_4_love_dining.py

# Validation
python3 scripts/test_regression_data_integrity.py && \
python3 scripts/data_sanity_check.py --strict

# Optional: Verify coordinates
python3 scripts/verify_restaurant_coordinates.py --all --threshold 5
```

**Do NOT skip tests. Tests prevent the exact problems we had before.**
