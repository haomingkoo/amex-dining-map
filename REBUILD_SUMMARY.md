# Data Rebuild Summary — Comprehensive Plan with Built-In Validation

**Date**: 2026-04-15  
**Status**: Ready to execute Phases 2-5 (Phase 1 ✅ complete)  
**Approach**: Validation-first extraction with three-layer validation framework

---

## The Problem We're Solving

Previous data state:
- ❌ 10 duplicate IDs (Wein & Co: 14 locations with same ID)
- ❌ 10 wrong-country matches (SEN in Singapore instead of Kyoto, 5,000km off)
- ❌ 79 Love Dining records with NO coordinates
- ❌ 262 records 10-50m off from Google Maps
- ❌ No validation layer when data was extracted
- ❌ Post-processing fixes accumulated errors instead of fixing source

## Our Solution: Validation-First Extraction

### Three-Layer Validation Strategy

**Layer 1: Field-Level (During Extraction)**
- Validate EVERY record immediately after extraction
- Type checks: strings, numbers, coordinate bounds
- Required fields: id, name, country, city
- No placeholder values (0,0 coordinates)
- Confidence score attached to each record

**Layer 2: Dataset-Level (After Extraction)**
- Duplicate ID detection (unique per {country-city-name-idx})
- Coordinate coverage percentage
- Count variance check (expected ±5%)
- Per-country distribution validation
- FAIL if >1% invalid records, duplicates found, or count mismatch

**Layer 3: Deployment (Before Production)**
- Run `data_sanity_check.py --strict` (7 comprehensive checks)
- Manual spot-checks: 15-50 venues per country
- Re-scrape Google Maps coordinates for validation
- Flag any variance >50m for manual review
- Only merge to production if ALL checks pass

### Built-In Validation, Not Post-Processing Fixes

**Key Philosophy**: Catch errors at extraction time, not afterward.

```
Old approach: Extract → Spot errors → Fix data → Extract again → Fix again...
New approach: Extract with validation → Fail if validation fails → Fix extraction source
```

When validation fails during extraction:
1. Error recorded in audit trail (visible, not hidden)
2. Record marked as "FAILED" with specific reason
3. Human reviews and fixes extraction logic
4. Re-run extraction (not the data)
5. Validation passes on next attempt

---

## Complete Rebuild Plan (Phases 1-5)

### ✅ Phase 1: Lock Japan Data (COMPLETE)

**Status**: Verified and frozen

**Validation Results**:
- 843 restaurants from Pocket Concierge
- 97% Tabelog match coverage (818/843 with quality signals)
- All coordinates valid (no out-of-bounds, no 0,0)
- No duplicate IDs
- 93 cities represented

**Output**: `JAPAN_VERIFICATION_REPORT.md` (committed)

**Next**: Keep Japan data unchanged during rebuild of other datasets.

---

### Phase 2: Global Dining Credit (2,000 restaurants across 16 countries)

**Source**: Official AMEX page  
https://www.americanexpress.com/en-sg/benefits/platinum/dining/

**User has provided**: Official page HTML samples (Hong Kong, Japan, New Zealand, Thailand) showing consistent structure.

**Extraction Strategy**:
1. Use Playwright to navigate through Country dropdown
2. Extract all restaurants with address, cuisine, city, map link
3. Handle multi-location chains properly:
   - Detect "X Locations" buttons
   - Click to expand and extract each location
   - Assign unique IDs: `amex-global-{country}-{city}-{name}-{idx}`

**Built-In Validation**:
- Validate each restaurant during extraction (required fields, coordinate bounds)
- Check for duplicate IDs
- Dataset-level: count variance, distribution stats
- Deployment: manual spot-checks (50 venues), Google Maps coordinate verification

**Expected Results**:
- 2,000 restaurants ±5%
- 16 countries
- Zero duplicate IDs
- All coordinates within country bounds

**Files Created**:
- `scripts/scrape_amex_global_dining_official.py` — Playwright scraper with validation hooks
- `scripts/parse_amex_html_samples.py` — HTML parser for testing extraction logic

**Next**: Run scraper, validate, manual spot-checks, then proceed to Phase 3.

---

### Phase 3: Plat Stay (69 properties worldwide)

**Source**: Official AMEX PDF  
https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/playstay.pdf

**Extraction Strategy**:
1. Download PDF to `data/sources/platstay.pdf`
2. Use pdfplumber to extract property name, city, country, address
3. Geocode via Nominatim (free, OpenStreetMap):
   - Validate coordinates within city bounds (±0.1° latitude)
   - Attach confidence level: "nominatim" or "manual"
4. Resolve issue: Generate unique IDs for properties with same name in different cities

**Built-In Validation**:
- Validate each property during extraction
- Geocoding confidence tracking
- Dataset-level: exact count (69), per-country distribution
- Deployment: manual spot-checks (15 properties) on Google Maps

**Expected Results**:
- 69 properties (exact, no variance)
- 100% geocoded (no missing coordinates)
- Reasonable per-country distribution
- All addresses and coordinates verified

**Next**: Extract from PDF, geocode, validate, manual spot-checks.

---

### Phase 4: Love Dining (79 Singapore venues)

**Source**: Official AMEX PDFs  
- Love_Dining_Restaurants_TnC.pdf  
- Love_Dining_Hotels_TnC.pdf  

**Extraction Strategy**:
1. Download PDFs to `data/sources/`
2. Use pdfplumber to extract venue name, type (restaurant/hotel), address
3. Geocode via Nominatim with Singapore filter:
   - Validate ALL coordinates within Singapore bounds (1.2-1.5°N, 103.6-104.1°E)
   - **Current issue**: 79 records have NO coordinates — MUST resolve here
4. Type-aware ID generation: `amex-love-dining-sg-{city}-{name}`

**Built-In Validation**:
- Validate each venue during extraction
- Required: all 79 must have coordinates after geocoding
- Coordinate coverage: 100% (non-negotiable)
- Dataset-level: exact count (79), type distribution
- Deployment: manual spot-checks (20 venues) on Google Maps

**Expected Results**:
- 79 venues (exact)
- 100% with valid coordinates
- 100% within Singapore bounds
- Mix of restaurants and hotels

**Next**: Extract from PDFs, geocode, resolve coordinate gaps, validate.

---

### Phase 5: Deployment Validation (Multi-Layer Pre-Deployment Checks)

**Validation Framework**: `data_sanity_check.py --strict`

**Seven Comprehensive Checks**:

1. **Required Fields**: All records have id, name, country, city
2. **Duplicate IDs**: Zero duplicate IDs across all datasets
3. **Coordinate Bounds**: All lat/lng within -90/+90, -180/+180
4. **No Placeholders**: No 0,0 coordinates, no empty addresses
5. **Data Types**: Strings are strings, numbers are numbers
6. **Coordinate Consistency**: Coordinates <10m from Google Maps (or marked manual)
7. **Orphaned Ratings**: No ratings without corresponding records

**Deployment Steps**:

1. **Automated Validation**:
   ```bash
   python3 scripts/data_sanity_check.py --strict
   ```
   - Fails if ANY error found
   - MUST pass before deployment

2. **Manual Spot-Checks** (50 random venues across all countries):
   - Verify on official AMEX page
   - Verify on Google Maps
   - Confirm address, cuisine, location correct
   - Check no country mismatches

3. **Coordinate Verification** (50 random restaurants):
   - Re-scrape Google Maps coordinates
   - Check distance from extracted coordinates
   - Flag if >50m, investigate if >100m
   - Confirm <10m precision achieved

4. **Count Verification**:
   - Japan: 843 restaurants ✅
   - Global: 2,000 ±5%
   - Plat Stay: 69 properties (exact)
   - Love Dining: 79 venues (exact)

5. **Production Merge** (only if all checks pass):
   ```bash
   # Backup current data
   git mv data/global-restaurants.json data/global-restaurants.BACKUP.json
   
   # Move REBUILT files
   mv data/rebuilt/global-restaurants-REBUILT.json data/global-restaurants.json
   mv data/rebuilt/plat-stays-REBUILT.json data/plat-stays.json
   mv data/rebuilt/love-dining-REBUILT.json data/love-dining.json
   
   # Commit and push to main
   git commit -m "data: rebuild from official AMEX sources (validation passed)"
   git push origin main  # Auto-deploys to production
   ```

---

## Audit Trail & Transparency

Every extraction phase generates a full audit trail:

```json
{
  "timestamp": "2026-04-15T10:30:00Z",
  "dataset": "global-restaurants",
  "phase": "extraction",
  "status": "passed",
  "records_total": 2000,
  "records_valid": 1998,
  "records_invalid": 2,
  "invalid_reasons": {
    "missing_coordinates": 1,
    "address_incomplete": 1
  },
  "duplicate_ids": {},
  "coordinate_coverage_percent": 99.9,
  "distribution_by_country": {...},
  "multi_location_chains_detected": 12,
  "multi_location_chains_split_correctly": 12,
  "validation_passed": true
}
```

Saved to: `data/rebuilt/{dataset}-REBUILD.audit.jsonl`

**Key Point**: If validation fails, audit trail shows WHY (specific field errors, count mismatches, duplicate IDs) so we can fix the EXTRACTION, not the data.

---

## Files Created

### Validation Framework
- `DATA_VALIDATION_STRATEGY.md` — Complete three-layer validation philosophy + code examples
- `scripts/validate_phase_1_japan.py` — Phase 1 Japan validation (✅ already passed)

### Extraction Tools
- `scripts/scrape_amex_global_dining_official.py` — Playwright scraper with validation hooks
- `scripts/parse_amex_html_samples.py` — HTML parser for testing extraction logic
- `scripts/rebuild_data_from_sources.py` — Master pipeline coordinator (existing)

### Documentation
- `DATA_REBUILD_PLAN.md` — High-level strategy
- `DATA_REBUILD_IMPLEMENTATION.md` — Step-by-step execution guide
- `REBUILD_SUMMARY.md` — This document

### Validation
- `scripts/data_sanity_check.py` — 7-check pre-deployment validation (existing)
- `data_sanity_check.py --strict` — Deployment-gating strict mode

---

## Success Criteria (Before Deployment)

✅ **Zero Post-Processing Fixes** — extraction correct on first pass  
✅ **No Duplicate IDs** — unique per {country-city-name-idx}  
✅ **100% Coordinate Coverage** — no missing lat/lng  
✅ **<10m Precision** — coordinates match Google Maps  
✅ **No Wrong-Country Matches** — venue location matches country  
✅ **Exact Counts Match**:
- Global: 2,000 ±5%
- Plat Stay: 69 (exact)
- Love Dining: 79 (exact)
- Japan: 843 (locked, no changes)

✅ **Full Audit Trail** — extraction history visible and verifiable  
✅ **Manual Spot-Checks Pass** — 50-100 random venues manually verified  
✅ **Strict Validation Passes** — `data_sanity_check.py --strict`  

---

## Timeline

Assuming Playwright + pdfplumber available and AMEX pages stable:

| Phase | Task | Est. Time | Status |
|-------|------|-----------|--------|
| 1 | Japan validation | 15 min | ✅ Complete |
| 2 | Global Dining scrape + validate | 2-3 hours | Ready |
| 2 | Manual spot-checks (50 venues) | 30 min | Ready |
| 3 | Plat Stay extraction + geocoding | 1 hour | Ready |
| 3 | Manual spot-checks (15 properties) | 20 min | Ready |
| 4 | Love Dining extraction + geocoding | 1 hour | Ready |
| 4 | Manual spot-checks (20 venues) | 20 min | Ready |
| 5 | Deployment validation + merge | 1 hour | Ready |
| **Total** | **All phases** | **~6-7 hours** | **Ready** |

Once setup complete, execution is straightforward (no complex post-processing fixes).

---

## What We're NOT Doing

❌ **No post-processing coordinate fixes** — if a venue is misaligned, we fix the EXTRACTION, not the data  
❌ **No silent failures** — every validation error visible in audit trail  
❌ **No data deletion** — invalid records marked "FAILED" with reasons, not removed  
❌ **No manual data edits** — fix comes from source (PDF, official AMEX page), not by hand  

---

## Summary

We've built a **comprehensive, validation-first approach** to rebuilding the AMEX dining data:

1. **Three-layer validation** catches errors at extraction (not after)
2. **Built-in checks** on every record, every dataset, every deployment
3. **Full audit trail** shows what was extracted, when, from where, confidence
4. **Manual spot-checks** confirm accuracy before production
5. **Strict pre-deployment validation** prevents bad data from reaching users

**Result**: Data you can trust, sourced from official AMEX, validated at every step, fully auditable.

---

## Next Steps

1. **Phase 2**: Run `scripts/scrape_amex_global_dining_official.py` (Playwright required)
2. **Phase 3**: Extract Plat Stay from official PDF (pdfplumber required)
3. **Phase 4**: Extract Love Dining from official PDFs
4. **Phase 5**: Run strict validation and deploy to production

All groundwork complete. Ready to execute.
