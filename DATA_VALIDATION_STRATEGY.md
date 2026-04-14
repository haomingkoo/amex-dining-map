# Data Validation Strategy — Built-In Tests, Not Post-Processing Fixes

**Philosophy**: Catch errors at extraction time, not after. Every dataset output must pass validation before being written to disk.

---

## Why This Matters

Previous approach: scrape → validate → fix → scrape again → validate...

**Problem**: This cycle is inefficient and accumulates errors (SEN in Singapore instead of Japan, Plat Stay hotels 5,000m off, Love Dining with no coordinates).

**New approach**: Extract with validation built in. If validation fails during extraction, the record is marked as requiring review — not silently corrupted.

---

## Three Validation Layers

### Layer 1: Field-Level Validation (During Extraction)

For each extracted record, validate immediately:

```python
def validate_record_fields(record: dict, dataset_type: str) -> tuple[bool, list[str]]:
    """Validate individual record fields. Return (is_valid, errors)."""
    errors = []

    # Required fields
    required = {"id", "name", "country", "city"}
    missing = required - set(record.keys())
    if missing:
        errors.append(f"Missing required fields: {missing}")
        return False, errors

    # Type checks
    if not isinstance(record["name"], str) or not record["name"].strip():
        errors.append("Name must be non-empty string")

    if not isinstance(record["country"], str):
        errors.append(f"Country must be string, got {type(record['country'])}")

    # Coordinate validation (if present)
    if "lat" in record and "lng" in record:
        lat, lng = record.get("lat"), record.get("lng")

        if lat is None or lng is None:
            errors.append("Incomplete coordinates (one is None)")
            return False, errors

        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            errors.append(f"Coordinates not numeric: ({type(lat)}, {type(lng)})")
            return False, errors

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            errors.append(f"Coordinates out of bounds: ({lat}, {lng})")
            return False, errors

        if lat == 0 and lng == 0:
            errors.append("Coordinates at 0,0 (placeholder)")
            return False, errors

    return len(errors) == 0, errors
```

### Layer 2: Dataset-Level Validation (After Extraction, Before Output)

After extracting all records from a source:

```python
def validate_dataset(records: list, dataset_type: str, expected_count: int = None) -> dict:
    """Validate full dataset. Returns detailed report."""
    report = {
        "dataset": dataset_type,
        "total_records": len(records),
        "valid_records": 0,
        "invalid_records": 0,
        "errors_by_type": defaultdict(list),
        "field_coverage": {},
        "coordinate_precision": {},
    }

    # 1. Validate each record
    for i, rec in enumerate(records):
        is_valid, errors = validate_record_fields(rec, dataset_type)
        if is_valid:
            report["valid_records"] += 1
        else:
            report["invalid_records"] += 1
            for err in errors:
                report["errors_by_type"][err].append(i)

    # 2. Check for duplicate IDs
    seen_ids = set()
    duplicates = defaultdict(list)
    for i, rec in enumerate(records):
        rec_id = rec.get("id")
        if rec_id in seen_ids:
            duplicates[rec_id].append(i)
        seen_ids.add(rec_id)

    if duplicates:
        report["duplicate_ids"] = dict(duplicates)

    # 3. Check coordinate coverage
    with_coords = sum(1 for r in records if r.get("lat") is not None)
    report["coordinate_coverage"] = {
        "with_coordinates": with_coords,
        "without_coordinates": len(records) - with_coords,
        "coverage_percent": 100 * with_coords / len(records) if records else 0,
    }

    # 4. If expected_count provided, flag mismatch
    if expected_count:
        report["expected_count"] = expected_count
        report["count_match"] = len(records) == expected_count
        if len(records) != expected_count:
            report["count_variance"] = len(records) - expected_count
            report["count_variance_percent"] = 100 * (len(records) - expected_count) / expected_count

    # 5. Distribution stats
    by_country = defaultdict(int)
    by_city = defaultdict(int)
    for rec in records:
        by_country[rec.get("country", "UNKNOWN")] += 1
        by_city[rec.get("city", "UNKNOWN")] += 1

    report["distribution"] = {
        "countries": len(by_country),
        "cities": len(by_city),
        "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1])),
    }

    return report
```

### Layer 3: Deployment Validation (Before Merging to Production)

Before moving REBUILT files to production, run comprehensive pre-deployment checks:

```bash
# Only passes if ALL checks succeed
python3 scripts/data_sanity_check.py --strict
```

Checks performed:
- ✅ Zero duplicate IDs (across all datasets)
- ✅ All coordinates <10m from Google Maps (or marked as "manual")
- ✅ Official counts match AMEX sources
- ✅ No "wrong country" venues
- ✅ Coordinate distribution reasonable (no clustering)
- ✅ Google ratings coverage >95%

---

## Per-Dataset Validation Rules

### Global Dining (2,000 restaurants across 16 countries)

**Extraction Validation**:
1. Extract from official AMEX page (https://www.americanexpress.com/en-sg/benefits/platinum/dining/)
2. For each country:
   - Verify at least 1 restaurant extracted
   - Check no duplicate names within city (flags multi-location chains for special handling)
   - Validate address contains street indicator (St., Rd., Ave., etc.) or floor number
   - Extract Google Maps link and validate URL format

3. For multi-location chains (e.g., "Chefman: 2 Locations"):
   - Click "View locations" button
   - Extract each location separately with unique ID: `amex-global-{country}-{city}-{name}-{idx}`
   - Validate: if source says "2 Locations", verify exactly 2 extracted

**Dataset Validation**:
- Total count: 2,000 ± 5% (allow 1,900-2,100)
- Per country: verify against AMEX official counts
- No duplicate IDs (unique per {country-city-name-idx} combination)
- All coordinates within country geographic bounds
- All addresses contain at least street name + city

**Deployment Checks**:
- Re-scrape 50 random restaurants' Google Maps coordinates
- Verify < 50m distance between extracted coords and Google Maps
- If any variance > 100m, flag for manual review before deployment

### Plat Stay (69 properties)

**Extraction Validation**:
1. PDF extraction:
   - Each page yields 1-3 properties
   - Validate: property name, city, country, address present
   - No blank/placeholder addresses

2. Geocoding:
   - Use Google Places API or Nominatim
   - Validate: coordinates within city bounds (±0.1° latitude)
   - Confidence level: "official_api" (Google) > "nominatim" (OSM) > "manual"
   - Store confidence in record: `{"coordinate_source": "official_api", "coordinate_confidence": 0.95}`

**Dataset Validation**:
- Total count: 69 (exact, no variance)
- Distribution check: verify counts per country match AMEX Platinum benefits page
- All coordinates within country bounds
- No coordinates at 0,0 or placeholder values

**Deployment Checks**:
- Manually verify 10-15 random properties on Google Maps
- Check: property name matches, address visible, building location correct
- If any mismatch, re-geocode that property

### Love Dining (79 Singapore venues)

**Extraction Validation**:
1. PDF extraction (Restaurants + Hotels):
   - Validate: venue name, type (restaurant/hotel), address
   - All in Singapore

2. Geocoding:
   - All venues are in Singapore — use Nominatim with "Singapore" filter
   - Validate: coordinates within Singapore bounds (1.2°-1.5° N, 103.6°-104.1° E)
   - Current issue: 79 records have NO coordinates — must resolve during extraction

**Dataset Validation**:
- Total count: 79 (exact)
- Coordinate coverage: 100% (no record without lat/lng)
- Type distribution: split between restaurants and hotels
- All addresses in Singapore

**Deployment Checks**:
- Verify 20 random venues on Google Maps
- Check: venue name, address, location visible
- Confirm: Love Dining venues actually exist and are operating

---

## Implementation Pattern: Extract with Built-In Validation

```python
def extract_and_validate(source: str, dataset_type: str, expected_count: int) -> tuple[list, dict]:
    """Extract records and validate immediately. Fail fast if validation fails."""

    records = []
    extraction_errors = []

    # 1. Extract
    try:
        raw_records = extract_from_source(source, dataset_type)
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        sys.exit(1)

    # 2. Validate and clean during extraction
    for i, raw_rec in enumerate(raw_records):
        is_valid, errors = validate_record_fields(raw_rec, dataset_type)

        if not is_valid:
            # Don't silently drop — flag for manual review
            raw_rec["validation_status"] = "FAILED"
            raw_rec["validation_errors"] = errors
            extraction_errors.append((i, errors))
            # STILL ADD TO RECORDS — so we can see what failed
            records.append(raw_rec)
        else:
            raw_rec["validation_status"] = "VALID"
            records.append(raw_rec)

    # 3. Dataset-level validation
    report = validate_dataset(records, dataset_type, expected_count)

    # 4. FAIL if critical issues
    if report["invalid_records"] > len(records) * 0.01:  # >1% invalid = fail
        print(f"❌ Dataset validation failed: {report['invalid_records']}/{len(records)} invalid")
        print(json.dumps(report, indent=2))
        sys.exit(1)

    if "duplicate_ids" in report:
        print(f"❌ Duplicate IDs found: {report['duplicate_ids']}")
        sys.exit(1)

    if expected_count and not report.get("count_match"):
        variance = report.get("count_variance_percent", 0)
        if abs(variance) > 5:  # >5% variance = fail
            print(f"❌ Count mismatch: expected {expected_count}, got {len(records)} ({variance:.1f}%)")
            sys.exit(1)

    # 5. Output records only if validation passes
    return records, report
```

---

## Test Suite: Confidence Before Deployment

Before committing REBUILT files to production:

```bash
# 1. Extract + validate each dataset
python3 scripts/scrape_amex_global_dining_official.py
python3 scripts/extract_plat_stay.py
python3 scripts/extract_love_dining.py

# 2. Run strict pre-deployment validation
python3 scripts/data_sanity_check.py --strict

# 3. Manual spot-checks (20-30 per country)
python3 scripts/manual_verification_guide.py

# 4. Only if all pass: merge to production
python3 scripts/merge_rebuilt_to_production.py
```

---

## Success Criteria

✅ **No post-processing fixes** — extraction is correct on first pass  
✅ **No silent failures** — every validation error visible in audit trail  
✅ **100% transparency** — confidence scores and source attribution on every record  
✅ **Testable** — validation rules can be re-run any time  
✅ **Auditable** — full extraction + validation logs archived  
✅ **Deployment-safe** — pre-deployment checks prevent bad data from reaching production

---

## Audit Trail Example

```json
{
  "timestamp": "2026-04-15T10:30:00Z",
  "dataset": "global-restaurants",
  "phase": "extraction",
  "status": "passed",
  "records": {
    "total": 2000,
    "valid": 1998,
    "invalid": 2,
    "invalid_reasons": {
      "missing_coordinates": 1,
      "address_incomplete": 1
    }
  },
  "distribution": {
    "countries": 16,
    "cities": 342,
    "average_per_country": 125,
    "variance": "Austria: 45 (low), Thailand: 180 (high)"
  },
  "multi_location_chains": {
    "detected": 12,
    "properly_split": 12
  },
  "coordinate_precision": {
    "with_coordinates": 1998,
    "average_decimal_places": 6
  },
  "validation_passed": true,
  "next_step": "Deploy to production with pre-deployment checks"
}
```

---

## Summary

This strategy ensures:

1. **Errors caught at source** — not accumulated through post-processing
2. **Validation transparency** — every validation rule visible and testable
3. **Confidence scoring** — every record has source and confidence metadata
4. **Audit trail** — full extraction history preserved
5. **Safe deployment** — multi-layer validation before production merge

**Result**: Data you can trust.
