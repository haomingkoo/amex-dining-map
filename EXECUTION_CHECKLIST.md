# Execution Checklist — Phase 1-5 with Test Gates

**Status**: Ready to execute with comprehensive test coverage

**Token cost**: Zero (all local execution)

**Timeline**: ~5-6 hours including tests

---

## Pre-Execution Setup

- [ ] Install Playwright: `pip install playwright && playwright install`
- [ ] Install pdfplumber: `pip install pdfplumber`
- [ ] Install geopy: `pip install geopy`
- [ ] Download Plat Stay PDF to `data/sources/platstay.pdf`
- [ ] Download Love Dining PDFs to `data/sources/`

---

## Phase 1: Japan Data (✅ ALREADY COMPLETE)

- [x] Run validation: `python3 scripts/validate_phase_1_japan.py`
- [x] Result: ✅ PASSED (843 restaurants, 97% Tabelog coverage)
- [x] Status: LOCKED, NO CHANGES

---

## Phase 2: Global Dining Extraction

### Step 1: Extract
```bash
python3 scripts/scrape_amex_global_dining_official.py
```
**Expected output**: `data/rebuilt/global-restaurants-REBUILT.json`

### Step 2: MANDATORY TEST (Fail Fast)
```bash
python3 scripts/test_phase_2_global_dining.py
```

**What it checks** (11 tests):
- ✅ File exists
- ✅ Valid JSON
- ✅ All required fields
- ✅ Zero duplicates
- ✅ Count 2,000 ±5%
- ✅ All 16 countries present
- ✅ Distribution reasonable (5-25% per country)
- ✅ 90%+ have coordinates
- ✅ Coordinates within bounds
- ✅ No validation failures
- ✅ Audit trail exists

**If PASS** → Continue to Phase 3  
**If FAIL** → Fix extraction, re-run extraction + test

### Step 3: Manual Spot-Checks (50 venues)
```bash
# Randomly pick 50 restaurants and verify on:
# 1. https://www.americanexpress.com/en-sg/benefits/platinum/dining/
# 2. Google Maps
# Expected: names, addresses, cuisines match official sources
```

---

## Phase 3: Plat Stay Extraction

### Step 1: Create Extraction Script
Use pattern from `DATA_REBUILD_IMPLEMENTATION.md`:
- Extract name, city, country, address from PDF
- Geocode each address via Nominatim
- Generate unique IDs: `amex-plat-stay-{country}-{city}-{name}`

```bash
# python3 scripts/extract_plat_stay.py
```
**Expected output**: `data/rebuilt/plat-stays-REBUILT.json` (69 properties)

### Step 2: MANDATORY TEST (Fail Fast)
```bash
python3 scripts/test_phase_3_plat_stay.py
```

**What it checks** (9 tests):
- ✅ File exists
- ✅ Exactly 69 properties (no variance)
- ✅ All required fields
- ✅ Zero duplicates
- ✅ **100% have coordinates** (no missing)
- ✅ Coordinates within bounds
- ✅ Country distribution reasonable
- ✅ All addresses populated
- ✅ Geocoding confidence tracked

**If PASS** → Continue to Phase 4  
**If FAIL** → Fix extraction, re-run extraction + test

### Step 3: Manual Spot-Checks (15 properties)
```bash
# Randomly pick 15 properties and verify on Google Maps:
# - Name visible
# - Address correct
# - Location in correct city/country
# - Building/hotel visible
```

---

## Phase 4: Love Dining Extraction ⚠️ **CRITICAL PHASE**

### Step 1: Create Extraction Script
Use pattern from `DATA_REBUILD_IMPLEMENTATION.md`:
- Extract name, type (restaurant/hotel), address from PDFs
- Geocode EVERY venue via Nominatim with Singapore filter
- **ALL 79 MUST HAVE COORDINATES** (current: 0/79)
- Generate IDs: `amex-love-dining-sg-{city}-{name}`

```bash
# python3 scripts/extract_love_dining.py
```
**Expected output**: `data/rebuilt/love-dining-REBUILT.json` (79 with 100% coordinates)

### Step 2: MANDATORY TEST (Fail Fast) ⚠️ **CRITICAL**
```bash
python3 scripts/test_phase_4_love_dining.py
```

**What it checks** (8 tests, CRITICAL on coordinates):
- ✅ File exists
- ✅ Exactly 79 venues
- ✅ All required fields
- ✅ Zero duplicates
- ✅ **🔴 ALL 79 HAVE COORDINATES** ← THIS WAS BROKEN
- ✅ All within Singapore bounds
- ✅ Coordinate types valid
- ✅ Mix of restaurants + hotels

**If PASS** → Continue to Phase 5  
**If FAIL** → **CRITICAL ISSUE** Fix geocoding, re-run extraction + test

### Step 3: Manual Spot-Checks (20 venues)
```bash
# Randomly pick 20 venues and verify on Google Maps:
# - Venue name visible
# - Address correct
# - Location in Singapore
# - Type (restaurant/hotel) correct
```

---

## Phase 5: Pre-Deployment Validation

### Step 1: Regression Test
```bash
python3 scripts/test_regression_data_integrity.py
```

**What it checks**:
- Japan: 843 restaurants, locked, valid
- Global: ~2,000-2,470, no duplicates
- Plat Stay: ~69, all with coordinates
- Love Dining: 79, ALL with coordinates ← VERIFY FIXED
- Ratings: coverage stats

**If FAIL**: STOP, investigate before proceeding

### Step 2: Strict Pre-Deployment Validation
```bash
python3 scripts/data_sanity_check.py --strict
```

**What it checks** (7 comprehensive checks):
- ✅ All required fields present
- ✅ Zero duplicate IDs (cross-dataset)
- ✅ Coordinate bounds valid
- ✅ No placeholder coordinates (0,0)
- ✅ Data types correct
- ✅ Coordinate consistency vs Google Maps
- ✅ No orphaned ratings

**Expected**: ALL 7 CHECKS PASS  
**If FAIL**: Fix data, re-validate

### Step 3: Final Manual Verification
```bash
# Sample 50 random venues across ALL programs:
# - Japan: 15 venues
# - Global: 20 venues
# - Plat Stay: 10 venues
# - Love Dining: 5 venues

# For each, verify on Google Maps / official AMEX page:
# - Name matches
# - Address correct
# - No country mismatches
# - Coordinates reasonable
```

### Step 4: Deployment (Only if ALL above pass)
```bash
# Backup current data
git mv data/global-restaurants.json data/global-restaurants.BACKUP.json
git mv data/plat-stays.json data/plat-stays.BACKUP.json
git mv data/love-dining.json data/love-dining.BACKUP.json

# Move rebuilt files
mv data/rebuilt/global-restaurants-REBUILT.json data/global-restaurants.json
mv data/rebuilt/plat-stays-REBUILT.json data/plat-stays.json
mv data/rebuilt/love-dining-REBUILT.json data/love-dining.json

# Commit and deploy
git add data/*.json
git commit -m "data: rebuild from official AMEX sources (validation passed)"
git push origin main  # Auto-deploys to production
```

---

## Post-Deployment Verification

- [ ] Check production deployed successfully
- [ ] Manual verification: open app, check 5-10 random venues
- [ ] Confirm all 4 programs load (Japan 843, Global ~2000, Plat Stay 69, Love Dining 79)
- [ ] Confirm Love Dining venues now have coordinates (FIXED)

---

## Ongoing Data Integrity (Weekly)

```bash
# Run to detect any drift or corruption
python3 scripts/test_regression_data_integrity.py

# Should always PASS
# If fails: investigate and fix immediately
```

---

## Test Gates Summary

| Phase | Extract | Test | Pass Criteria | Manual Check |
|-------|---------|------|---------------|--------------|
| 1 | ✅ Done | ✅ Pass | 843, 97% coverage | ✅ Complete |
| 2 | → Run | → Run | 1,900-2,100, 0 dups, 16 countries | → 50 venues |
| 3 | → Run | → Run | 69 exact, 0 dups, 100% coords | → 15 properties |
| 4 | → Run | → Run | 79 exact, 0 dups, 100% coords | → 20 venues |
| 5 | - | → Run | All 7 checks pass | → 50 random venues |

**CRITICAL GATES**:
- Phase 4 test MUST pass (100% Love Dining coordinates)
- Pre-deployment validation MUST pass (all 7 checks)
- Manual verification MUST pass (no wrong countries, no 500m+ offsets)

---

## If Any Test Fails

1. **Don't modify the test** — test is correct
2. **Identify the problem**:
   - Check audit trail: `data/rebuilt/*audit.jsonl`
   - Look at specific failing record
3. **Fix extraction**:
   - Not the data
   - Fix the extraction script
4. **Re-run extraction** from scratch
5. **Re-run test** to confirm fix
6. **Only then proceed** to next phase

---

## Token Cost Breakdown

- Execution: `python3 scripts/*.py` = **0 tokens** (local)
- Manual verification: your eyes on Google Maps = **0 tokens**
- Debugging via chat (if needed): only if test fails = **varies**

**Expected**: 0 tokens if everything works  
**Worst case**: <100 tokens if you need help debugging

---

## Timeline Estimate

| Phase | Extract | Test | Manual | Total |
|-------|---------|------|--------|-------|
| 1 | ✅ 15m | ✅ 2m | ✅ 10m | ✅ 27m |
| 2 | 1-2h | 1m | 20m | ~2h |
| 3 | 45m | 30s | 10m | ~1h |
| 4 | 45m | 30s | 10m | ~1h |
| 5 | - | 3m | 20m | ~25m |
| **TOTAL** | **~3.5h** | **~5m** | **~70m** | **~5-6h** |

---

## Success Criteria (Deployment Ready)

- ✅ Phase 1: Japan verified and locked
- ✅ Phase 2: Global Dining extracted, tested, manual verified
- ✅ Phase 3: Plat Stay extracted, tested, manual verified
- ✅ Phase 4: **Love Dining extracted with 100% coordinates, tested, manual verified**
- ✅ Phase 5: All validations pass, manual spot-checks pass
- ✅ Production deployed and verified

---

## Ready to Go?

```bash
# Check current status
git log --oneline -5

# Should see framework commits:
# - comprehensive test suite
# - validation framework
# - Phase 1 complete

# Then start Phase 2:
python3 scripts/scrape_amex_global_dining_official.py
python3 scripts/test_phase_2_global_dining.py
```

**All framework in place. Tests prevent data drift. Zero tokens. Ready to execute.**
