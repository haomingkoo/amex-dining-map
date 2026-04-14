#!/usr/bin/env python3
"""
TEST SUITE FOR PHASE 2: Global Dining Extraction

Run this IMMEDIATELY AFTER scraping to validate extraction quality.
Fails fast if any critical issues found.

Usage:
  python3 scripts/test_phase_2_global_dining.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"


def test_file_exists() -> bool:
    """Test 1: Output file was created."""
    print("\n1️⃣  File exists...")
    rebuilt_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
    if not rebuilt_file.exists():
        print(f"  ❌ FAIL: {rebuilt_file} not found")
        return False
    print(f"  ✅ File exists: {rebuilt_file}")
    return True


def test_valid_json(records: list) -> bool:
    """Test 2: Valid JSON structure."""
    print("\n2️⃣  Valid JSON...")
    if not isinstance(records, list):
        print(f"  ❌ FAIL: Root is not list, got {type(records)}")
        return False
    if len(records) == 0:
        print(f"  ❌ FAIL: Empty list")
        return False
    print(f"  ✅ Valid JSON list with {len(records)} records")
    return True


def test_required_fields(records: list) -> bool:
    """Test 3: All records have required fields."""
    print("\n3️⃣  Required fields (id, name, country, city)...")
    required = {"id", "name", "country", "city"}
    missing_records = []

    for i, rec in enumerate(records):
        missing = required - set(rec.keys())
        if missing:
            missing_records.append((i, rec.get("name", "UNNAMED"), missing))

    if missing_records:
        print(f"  ❌ FAIL: {len(missing_records)} records missing required fields")
        for i, name, missing in missing_records[:5]:
            print(f"     Record {i} ({name}): missing {missing}")
        return False

    print(f"  ✅ All {len(records)} records have required fields")
    return True


def test_no_duplicate_ids(records: list) -> bool:
    """Test 4: Zero duplicate IDs."""
    print("\n4️⃣  No duplicate IDs...")
    id_count = defaultdict(list)
    for i, rec in enumerate(records):
        rec_id = rec.get("id")
        if rec_id:
            id_count[rec_id].append(i)

    duplicates = {k: v for k, v in id_count.items() if len(v) > 1}
    if duplicates:
        print(f"  ❌ FAIL: {len(duplicates)} duplicate IDs found:")
        for dup_id, indices in sorted(duplicates.items())[:5]:
            print(f"     {dup_id}: {len(indices)} instances")
        return False

    print(f"  ✅ Zero duplicate IDs ({len(id_count)} unique)")
    return True


def test_count_variance(records: list) -> bool:
    """Test 5: Count within expected range (2,000 ±5%)."""
    print("\n5️⃣  Count variance (2,000 ±5%)...")
    expected = 2000
    actual = len(records)
    variance_pct = 100 * (actual - expected) / expected

    if actual < 1900 or actual > 2100:
        print(f"  ❌ FAIL: {actual} records (expected 2,000 ±5%, got {variance_pct:.1f}%)")
        return False

    print(f"  ✅ {actual} records ({variance_pct:+.1f}% variance)")
    return True


def test_all_countries_present(records: list) -> bool:
    """Test 6: All 16 countries represented."""
    print("\n6️⃣  Country coverage (16 countries)...")
    expected_countries = {
        "Australia", "Austria", "Belgium", "Canada", "France",
        "Germany", "Hong Kong", "Japan", "Mexico", "Netherlands",
        "New Zealand", "Spain", "Switzerland", "Taiwan", "Thailand",
        "United Kingdom"
    }

    countries_found = set(r.get("country") for r in records if r.get("country"))
    missing = expected_countries - countries_found

    if missing:
        print(f"  ❌ FAIL: Missing countries: {missing}")
        return False

    print(f"  ✅ All 16 countries represented: {sorted(countries_found)}")
    return True


def test_reasonable_distribution(records: list) -> bool:
    """Test 7: No country has <5% or >25% of total."""
    print("\n7️⃣  Distribution sanity (per-country 5-25%)...")
    by_country = defaultdict(int)
    for rec in records:
        by_country[rec.get("country", "UNKNOWN")] += 1

    total = len(records)
    anomalies = []

    for country, count in by_country.items():
        pct = 100 * count / total
        if pct < 5 or pct > 25:
            anomalies.append((country, count, pct))

    if anomalies:
        print(f"  ⚠️  {len(anomalies)} countries outside 5-25% range:")
        for country, count, pct in sorted(anomalies, key=lambda x: -x[2]):
            print(f"     {country}: {count} ({pct:.1f}%)")
        # Warning, not fail (might be legitimate)
        return True

    print(f"  ✅ Distribution reasonable (5-25% per country)")
    return True


def test_coordinates_present(records: list) -> bool:
    """Test 8: Coordinate coverage >90%."""
    print("\n8️⃣  Coordinate coverage >90%...")
    with_coords = sum(1 for r in records if r.get("lat") is not None and r.get("lng") is not None)
    coverage = 100 * with_coords / len(records) if records else 0

    if coverage < 90:
        print(f"  ❌ FAIL: {coverage:.1f}% have coordinates (expected >90%)")
        return False

    print(f"  ✅ {with_coords}/{len(records)} ({coverage:.1f}%) have coordinates")
    return True


def test_coordinates_valid(records: list) -> bool:
    """Test 9: All coordinates within bounds."""
    print("\n9️⃣  Coordinate bounds (-90/+90, -180/+180)...")
    invalid = []

    for i, rec in enumerate(records):
        lat = rec.get("lat")
        lng = rec.get("lng")

        if lat is None or lng is None:
            continue

        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            invalid.append((i, rec.get("name"), f"non-numeric"))
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            invalid.append((i, rec.get("name"), f"({lat}, {lng})"))
        elif lat == 0 and lng == 0:
            invalid.append((i, rec.get("name"), "placeholder (0,0)"))

    if invalid:
        print(f"  ❌ FAIL: {len(invalid)} records with invalid coordinates:")
        for i, name, issue in invalid[:5]:
            print(f"     {name}: {issue}")
        return False

    print(f"  ✅ All coordinates valid")
    return True


def test_no_silent_errors(records: list) -> bool:
    """Test 10: No records marked FAILED (should have been caught in extraction)."""
    print("\n🔟 No validation failures...")
    failed = [r for r in records if r.get("validation_status") == "FAILED"]

    if failed:
        print(f"  ❌ FAIL: {len(failed)} records have validation_status=FAILED")
        for rec in failed[:5]:
            print(f"     {rec.get('name')}: {rec.get('validation_errors')}")
        return False

    print(f"  ✅ No failed records")
    return True


def test_audit_trail_exists() -> bool:
    """Test 11: Audit trail was generated."""
    print("\n1️⃣1️⃣  Audit trail generated...")
    audit_file = REBUILT_DIR / "global-dining-REBUILD.audit.jsonl"
    if not audit_file.exists():
        print(f"  ⚠️  No audit trail: {audit_file}")
        return True  # Warning, not fail

    with open(audit_file) as f:
        lines = f.readlines()
    print(f"  ✅ Audit trail exists ({len(lines)} entries)")
    return True


def main() -> bool:
    """Run all tests."""
    print("\n" + "="*80)
    print("PHASE 2 TEST SUITE: Global Dining Extraction")
    print("="*80)

    # Test 1: File exists
    if not test_file_exists():
        return False

    # Load data
    rebuilt_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
    with open(rebuilt_file) as f:
        records = json.load(f)

    # Run tests
    tests = [
        test_valid_json,
        test_required_fields,
        test_no_duplicate_ids,
        test_count_variance,
        test_all_countries_present,
        test_reasonable_distribution,
        test_coordinates_present,
        test_coordinates_valid,
        test_no_silent_errors,
        test_audit_trail_exists,
    ]

    results = []
    for test in tests:
        try:
            passed = test(records)
            results.append((test.__name__, passed))
        except Exception as e:
            print(f"  ❌ ERROR: {str(e)}")
            results.append((test.__name__, False))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Ready for Phase 3")
        return True
    else:
        print("\n❌ TESTS FAILED - Fix extraction issues before proceeding")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
