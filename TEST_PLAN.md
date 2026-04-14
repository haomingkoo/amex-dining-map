# Test Plan — Prevent Data Drift and Integrity Issues

**Goal**: Catch any data problems immediately, not months later.

**Approach**: Automated tests run during extraction to validate quality.

---

## Three Types of Tests

### 1️⃣ Phase-Specific Tests (Run After Each Phase)

**Phase 2: Global Dining**
```bash
python3 scripts/test_phase_2_global_dining.py
```
Tests:
- ✅ 2,000 ±5% restaurants (not 2,470)
- ✅ Zero duplicate IDs
- ✅ 16 countries represented
- ✅ 90%+ have coordinates
- ✅ No coordinates at 0,0
- ✅ Reasonable per-country distribution (5-25%)

**When to run**: Immediately after `scrape_amex_global_dining_official.py` completes

**What it catches**: Wrong country, duplicates, missing geocoding

---

**Phase 3: Plat Stay**
```bash
python3 scripts/test_phase_3_plat_stay.py
```
Tests:
- ✅ Exactly 69 properties (no variance)
- ✅ Zero duplicate IDs
- ✅ 100% have coordinates (no missing)
- ✅ All coordinates within bounds
- ✅ All addresses populated

**When to run**: Immediately after extraction + geocoding

**What it catches**: Missing coordinates, wrong boundaries, empty addresses

---

**Phase 4: Love Dining** ⚠️ **CRITICAL TEST**
```bash
python3 scripts/test_phase_4_love_dining.py
```
Tests:
- ✅ Exactly 79 venues (no variance)
- ✅ **ALL 79 HAVE COORDINATES** (THIS WAS BROKEN)
- ✅ Zero duplicate IDs
- ✅ All coordinates within Singapore bounds (1.0-1.6°N, 103.5-104.2°E)
- ✅ All addresses populated
- ✅ Mix of restaurants and hotels

**When to run**: Immediately after extraction + geocoding

**What it catches**: Missing geocoding (the original critical issue)

---

### 2️⃣ Regression Test (Run Anytime)

```bash
python3 scripts/test_regression_data_integrity.py
```

Tests current **production data** (not REBUILT) to detect drift.

Checks:
- **Japan**: 843 restaurants, no changes (locked)
- **Global**: ~2,000-2,470 restaurants, no duplicates
- **Plat Stay**: ~69 properties, all with coordinates
- **Love Dining**: 79 venues, **all with coordinates**
- **Ratings**: Coverage statistics

**When to run**:
- Before each deployment
- Weekly/monthly to detect corruption
- Anytime you suspect data drift

**What it catches**: Accidental data modifications, corruption, context drift

---

### 3️⃣ Pre-Deployment Validation (Phase 5)

```bash
python3 scripts/data_sanity_check.py --strict
```

Seven comprehensive checks:
1. Required fields present
2. No duplicate IDs (cross-dataset)
3. Coordinates within bounds
4. No placeholder coordinates (0,0)
5. Data types correct
6. Coordinate consistency (vs Google Maps)
7. No orphaned ratings

**When to run**: After all Phases 2-4 complete, before merge to main

**What it catches**: Systemic issues, cross-dataset problems, precision errors

---

## Test Workflow

### During Extraction (Phases 2-4)

```
1. Run extraction script
   python3 scripts/scrape_amex_global_dining_official.py
   
2. IMMEDIATELY run phase-specific test
   python3 scripts/test_phase_2_global_dining.py
   
   If PASS → proceed to next phase
   If FAIL → fix extraction script, re-run
```

### Before Deployment (Phase 5)

```
1. Run regression test on current production data
   python3 scripts/test_regression_data_integrity.py
   
   If any FAIL → investigate before proceeding
   
2. Run strict pre-deployment validation
   python3 scripts/data_sanity_check.py --strict
   
   If any FAIL → fix data, re-validate
   
3. Manual spot-checks (50+ venues)
   - Verify on Google Maps
   - Verify on AMEX official page
   
4. Only if all pass → deploy
   git push origin main
```

### Ongoing (Detect Drift)

```
# Run weekly or before any changes
python3 scripts/test_regression_data_integrity.py

# Should always pass
# If fails → data was corrupted somewhere
```

---

## What Each Test Catches

| Issue | Test That Catches It |
|-------|---------------------|
| Duplicate IDs | Phase 2/3/4 tests + Regression |
| Wrong country venue | Phase 2 test |
| Missing coordinates | Phase 3/4 tests |
| Out-of-bounds coordinates | Phase 3/4 tests |
| Empty addresses | Phase 3/4 tests |
| Count mismatch | Phase 2/3/4 tests |
| Data type errors | Pre-deployment validation |
| Coordinates >200m off Google | Pre-deployment validation |
| Accidental data modification | Regression test |
| Context drift | Regression test |

---

## Test Success Criteria

### Phase 2 (Global Dining)
```
✅ PASS if:
  - 1,900-2,100 restaurants
  - Zero duplicate IDs
  - 16 countries represented
  - 90%+ have coordinates
  - All coordinates valid
```

### Phase 3 (Plat Stay)
```
✅ PASS if:
  - Exactly 69 properties
  - Zero duplicate IDs
  - 100% have coordinates
  - All coordinates within bounds
  - All addresses non-empty
```

### Phase 4 (Love Dining) ⚠️ **CRITICAL**
```
✅ PASS if:
  - Exactly 79 venues
  - **100% have coordinates** (was 0% before)
  - Zero duplicate IDs
  - All coordinates in Singapore bounds
  - Mix of restaurants + hotels
```

### Pre-Deployment (Phase 5)
```
✅ PASS if:
  - Data sanity check --strict passes
  - Manual spot-checks pass
  - Google Maps verification <50m variance
```

### Regression (Anytime)
```
✅ PASS if:
  - Japan: 843 restaurants, all valid
  - Global: no duplicates, coordinates present
  - Plat Stay: all with coordinates
  - Love Dining: 100% with coordinates
  - No accidental modifications
```

---

## Test Execution Time

| Test | Time | When |
|------|------|------|
| Phase 2 test | 30 sec | After Global extraction |
| Phase 3 test | 10 sec | After Plat Stay extraction |
| Phase 4 test | 10 sec | After Love Dining extraction |
| Pre-deployment validation | 2 min | Before Phase 5 |
| Regression test | 5 sec | Weekly/before deploy |

**Total overhead**: ~3 minutes for full rebuild validation

---

## Preventing Context Drift

Tests are designed to **prevent exactly the problems we had before**:

### Old Problems → Test That Prevents It

| Problem | What Happened | Test Prevention |
|---------|---------------|-----------------|
| 10 duplicate IDs | Wein & Co: 14 locations, 1 ID | Phase 2 test checks duplicates |
| Wrong countries | SEN in Singapore, 5,000km off | Phase 2 test checks 16 countries |
| No coordinates | Love Dining: 79 venues, 0 coords | Phase 4 test: 100% coverage required |
| Silent failures | Errors masked by post-processing | Tests fail immediately if any error |
| Accidental drift | Data modified unknowingly | Regression test catches changes |

---

## How to Interpret Test Output

### GREEN ✅ (Test Passed)
```
✅ All 16 countries represented: {'Australia', 'Austria', ...}
```
→ Keep going, no issues

### RED ❌ (Test Failed)
```
❌ FAIL: {len(duplicates)} duplicate IDs found:
   Wein & Co: 14 instances
```
→ STOP. Fix extraction. Re-run extraction + test.

### YELLOW ⚠️ (Warning)
```
⚠️ Countries with >10 properties (might be OK):
   Thailand: 180
```
→ OK to continue (expected variation), but monitor

---

## Test Maintenance

### If Tests Fail

1. **Don't modify the test** — test is correct
2. **Fix the extraction** — source data or script
3. **Re-run extraction** — from scratch
4. **Re-run test** — confirm fix
5. **Only then proceed** — to next phase

### If Tests Are Too Strict

1. Update expected values if AMEX official source changes
2. Document why (e.g., "country count increased to 17")
3. Update tests in git with explanation
4. Never relax validation to hide problems

---

## Summary

**Tests prevent the exact problems we had**:
- ✅ Duplicates caught (Phase 2 test)
- ✅ Missing coordinates caught (Phase 4 test)
- ✅ Wrong countries caught (Phase 2 test)
- ✅ Data drift caught (Regression test)
- ✅ Silent failures prevented (Fast fail approach)

**Run tests after every extraction, before every deployment.**

**All tests are fast (<1 min per phase), so no excuse to skip them.**
