#!/usr/bin/env python3
"""
TEST SUITE FOR PHASE 3: Plat Stay Extraction

Run immediately after extraction to validate quality.

Usage:
  python3 scripts/test_phase_3_plat_stay.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"


def test_file_exists() -> bool:
    """Test 1: Output file exists."""
    print("\n1️⃣  File exists...")
    rebuilt_file = REBUILT_DIR / "plat-stays-REBUILT.json"
    if not rebuilt_file.exists():
        print(f"  ❌ FAIL: {rebuilt_file} not found")
        return False
    print(f"  ✅ File exists")
    return True


def test_exact_count(records: list) -> bool:
    """Test 2: Exactly 69 properties (no variance allowed)."""
    print("\n2️⃣  Exact count (69 properties)...")
    if len(records) != 69:
        print(f"  ❌ FAIL: {len(records)} properties (expected exactly 69)")
        return False
    print(f"  ✅ Exactly 69 properties")
    return True


def test_required_fields(records: list) -> bool:
    """Test 3: All required fields present."""
    print("\n3️⃣  Required fields (id, name, country, city, address)...")
    required = {"id", "name", "country", "city", "address"}
    missing_records = []

    for i, rec in enumerate(records):
        missing = required - set(rec.keys())
        if missing:
            missing_records.append((i, rec.get("name"), missing))

    if missing_records:
        print(f"  ❌ FAIL: {len(missing_records)} records missing fields")
        for i, name, missing in missing_records[:3]:
            print(f"     {name}: missing {missing}")
        return False

    print(f"  ✅ All fields present")
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
        print(f"  ❌ FAIL: {len(duplicates)} duplicate IDs")
        return False

    print(f"  ✅ Zero duplicates")
    return True


def test_coordinates_100_percent(records: list) -> bool:
    """Test 5: 100% coordinate coverage (no missing coordinates)."""
    print("\n5️⃣  100% coordinate coverage...")
    missing = sum(1 for r in records if r.get("lat") is None or r.get("lng") is None)

    if missing > 0:
        print(f"  ❌ FAIL: {missing} records missing coordinates")
        return False

    print(f"  ✅ All 69 properties have coordinates")
    return True


def test_coordinates_valid(records: list) -> bool:
    """Test 6: All coordinates within bounds."""
    print("\n6️⃣  Coordinate bounds...")
    invalid = []

    for i, rec in enumerate(records):
        lat = rec.get("lat")
        lng = rec.get("lng")

        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            invalid.append((rec.get("name"), "non-numeric"))
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            invalid.append((rec.get("name"), f"out of bounds"))
        elif lat == 0 and lng == 0:
            invalid.append((rec.get("name"), "placeholder"))

    if invalid:
        print(f"  ❌ FAIL: {len(invalid)} invalid coordinates")
        for name, issue in invalid[:3]:
            print(f"     {name}: {issue}")
        return False

    print(f"  ✅ All coordinates valid")
    return True


def test_country_distribution(records: list) -> bool:
    """Test 7: Countries make sense (no country >10 properties)."""
    print("\n7️⃣  Country distribution...")
    by_country = defaultdict(int)
    for rec in records:
        by_country[rec.get("country", "UNKNOWN")] += 1

    anomalies = [(c, count) for c, count in by_country.items() if count > 10]
    if anomalies:
        print(f"  ⚠️  Countries with >10 properties (might be OK):")
        for country, count in sorted(anomalies, key=lambda x: -x[1]):
            print(f"     {country}: {count}")
        return True  # Warning, not fail

    print(f"  ✅ Distribution reasonable ({len(by_country)} countries)")
    return True


def test_address_not_empty(records: list) -> bool:
    """Test 8: All addresses have content."""
    print("\n8️⃣  Address field populated...")
    empty = [r.get("name") for r in records if not r.get("address") or not r.get("address").strip()]

    if empty:
        print(f"  ❌ FAIL: {len(empty)} records with empty address")
        for name in empty[:3]:
            print(f"     {name}")
        return False

    print(f"  ✅ All addresses populated")
    return True


def test_geocoding_confidence(records: list) -> bool:
    """Test 9: Geocoding confidence tracked."""
    print("\n9️⃣  Geocoding confidence...")
    without_confidence = [r for r in records if "coordinate_source" not in r]

    if len(without_confidence) > 5:
        print(f"  ⚠️  {len(without_confidence)} records missing confidence tracking")
        return True  # Warning, not fail

    print(f"  ✅ Geocoding confidence tracked")
    return True


def main() -> bool:
    """Run all tests."""
    print("\n" + "="*80)
    print("PHASE 3 TEST SUITE: Plat Stay Extraction")
    print("="*80)

    if not test_file_exists():
        return False

    rebuilt_file = REBUILT_DIR / "plat-stays-REBUILT.json"
    with open(rebuilt_file) as f:
        records = json.load(f)

    tests = [
        test_exact_count,
        test_required_fields,
        test_no_duplicate_ids,
        test_coordinates_100_percent,
        test_coordinates_valid,
        test_country_distribution,
        test_address_not_empty,
        test_geocoding_confidence,
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

    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Ready for Phase 4")
        return True
    else:
        print("\n❌ TESTS FAILED")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
