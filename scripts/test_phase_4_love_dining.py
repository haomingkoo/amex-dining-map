#!/usr/bin/env python3
"""
TEST SUITE FOR PHASE 4: Love Dining Extraction

CRITICAL: All 79 records must have coordinates (current state = 0 coordinates).

Usage:
  python3 scripts/test_phase_4_love_dining.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"

# Singapore bounds: roughly 1.2-1.5N, 103.6-104.1E
SG_LAT_MIN, SG_LAT_MAX = 1.0, 1.6
SG_LNG_MIN, SG_LNG_MAX = 103.5, 104.2


def test_file_exists() -> bool:
    """Test 1: Output file exists."""
    print("\n1️⃣  File exists...")
    rebuilt_file = REBUILT_DIR / "love-dining-REBUILT.json"
    if not rebuilt_file.exists():
        print(f"  ❌ FAIL: {rebuilt_file} not found")
        return False
    print(f"  ✅ File exists")
    return True


def test_exact_count(records: list) -> bool:
    """Test 2: Exactly 79 venues (no variance)."""
    print("\n2️⃣  Exact count (79 venues)...")
    if len(records) != 79:
        print(f"  ❌ FAIL: {len(records)} venues (expected exactly 79)")
        return False
    print(f"  ✅ Exactly 79 venues")
    return True


def test_required_fields(records: list) -> bool:
    """Test 3: All required fields present."""
    print("\n3️⃣  Required fields (id, name, city, address, type)...")
    required = {"id", "name", "city", "address", "type"}
    missing_records = []

    for i, rec in enumerate(records):
        missing = required - set(rec.keys())
        if missing:
            missing_records.append((i, rec.get("name"), missing))

    if missing_records:
        print(f"  ❌ FAIL: {len(missing_records)} missing fields")
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


def test_coordinates_100_percent() -> bool:
    """Test 5: **CRITICAL** 100% coordinate coverage (THIS WAS BROKEN BEFORE)."""
    print("\n5️⃣  **CRITICAL** 100% coordinate coverage...")
    rebuilt_file = REBUILT_DIR / "love-dining-REBUILT.json"
    with open(rebuilt_file) as f:
        records = json.load(f)

    missing = []
    for i, rec in enumerate(records):
        if rec.get("lat") is None or rec.get("lng") is None:
            missing.append(rec.get("name"))

    if missing:
        print(f"  ❌ CRITICAL FAIL: {len(missing)} records with NO coordinates")
        print(f"     This was the original problem - 79/79 venues had no coordinates")
        for name in missing[:5]:
            print(f"     - {name}")
        return False

    print(f"  ✅ ALL 79 VENUES HAVE COORDINATES (FIXED)")
    return True


def test_coordinates_within_singapore_bounds(records: list) -> bool:
    """Test 6: All coordinates within Singapore bounds."""
    print("\n6️⃣  Within Singapore bounds...")
    out_of_bounds = []

    for rec in records:
        lat = rec.get("lat")
        lng = rec.get("lng")

        if lat is None or lng is None:
            continue

        if not (SG_LAT_MIN <= lat <= SG_LAT_MAX and SG_LNG_MIN <= lng <= SG_LNG_MAX):
            out_of_bounds.append((rec.get("name"), f"({lat}, {lng})"))

    if out_of_bounds:
        print(f"  ❌ FAIL: {len(out_of_bounds)} coordinates outside Singapore")
        for name, coords in out_of_bounds[:3]:
            print(f"     {name}: {coords}")
        return False

    print(f"  ✅ All coordinates within Singapore bounds")
    return True


def test_coordinates_valid_types(records: list) -> bool:
    """Test 7: Coordinates are numeric."""
    print("\n7️⃣  Coordinate types valid...")
    invalid = []

    for rec in records:
        lat = rec.get("lat")
        lng = rec.get("lng")

        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            invalid.append(rec.get("name"))

    if invalid:
        print(f"  ❌ FAIL: {len(invalid)} with non-numeric coordinates")
        return False

    print(f"  ✅ All coordinates numeric")
    return True


def test_type_distribution(records: list) -> bool:
    """Test 8: Mix of restaurants and hotels."""
    print("\n8️⃣  Type distribution (restaurants + hotels)...")
    types = defaultdict(int)
    for rec in records:
        types[rec.get("type", "UNKNOWN")] += 1

    if "restaurant" not in types or "hotel" not in types:
        print(f"  ⚠️  Missing restaurant or hotel type: {dict(types)}")
        return True  # Warning

    print(f"  ✅ Mixed: {types['restaurant']} restaurants, {types['hotel']} hotels")
    return True


def test_address_not_empty(records: list) -> bool:
    """Test 9: All addresses populated."""
    print("\n9️⃣  Address field populated...")
    empty = [r.get("name") for r in records if not r.get("address") or not r.get("address").strip()]

    if empty:
        print(f"  ❌ FAIL: {len(empty)} with empty address")
        return False

    print(f"  ✅ All addresses populated")
    return True


def main() -> bool:
    """Run all tests."""
    print("\n" + "="*80)
    print("PHASE 4 TEST SUITE: Love Dining Extraction")
    print("="*80)
    print("⚠️  CRITICAL TEST: All 79 venues must have coordinates")
    print("   (Current production state: 0/79 have coordinates)")

    if not test_file_exists():
        return False

    rebuilt_file = REBUILT_DIR / "love-dining-REBUILT.json"
    with open(rebuilt_file) as f:
        records = json.load(f)

    tests = [
        ("exact_count", test_exact_count(records)),
        ("required_fields", test_required_fields(records)),
        ("no_duplicate_ids", test_no_duplicate_ids(records)),
        ("coordinates_100_percent", test_coordinates_100_percent()),
        ("coordinates_within_sg_bounds", test_coordinates_within_singapore_bounds(records)),
        ("coordinates_valid_types", test_coordinates_valid_types(records)),
        ("type_distribution", test_type_distribution(records)),
        ("address_not_empty", test_address_not_empty(records)),
    ]

    results = [(name, result) for name, result in tests]

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED")
        print("   ✅ Love Dining data is now complete and correct")
        print("   ✅ All 79 venues have coordinates (FIXED)")
        print("   Ready for Phase 5 validation")
        return True
    else:
        print("\n❌ TESTS FAILED")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
