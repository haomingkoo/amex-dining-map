#!/usr/bin/env python3
"""
REGRESSION TEST: Data Integrity Checks

Run this ANYTIME to detect data corruption or drift.
Checks current production data against expected state.

Usage:
  python3 scripts/test_regression_data_integrity.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"

# Geographic bounds for all 16 countries
COUNTRY_BOUNDS = {
    "Australia": {"lat_min": -45, "lat_max": -10, "lng_min": 113, "lng_max": 154},
    "Austria": {"lat_min": 46.4, "lat_max": 49.0, "lng_min": 9.5, "lng_max": 17.2},
    "Belgium": {"lat_min": 49.5, "lat_max": 51.5, "lng_min": 2.4, "lng_max": 6.4},
    "Canada": {"lat_min": 42, "lat_max": 84, "lng_min": -141, "lng_max": -52},
    "France": {"lat_min": 42, "lat_max": 51, "lng_min": -5, "lng_max": 8},
    "Germany": {"lat_min": 47.3, "lat_max": 55.9, "lng_min": 5.9, "lng_max": 15.0},
    "Hong Kong": {"lat_min": 22.2, "lat_max": 22.6, "lng_min": 113.8, "lng_max": 114.4},
    "Japan": {"lat_min": 24, "lat_max": 46, "lng_min": 123, "lng_max": 146},
    "Mexico": {"lat_min": 14, "lat_max": 33, "lng_min": -118, "lng_max": -86},
    "Netherlands": {"lat_min": 50.8, "lat_max": 53.5, "lng_min": 3.4, "lng_max": 7.2},
    "New Zealand": {"lat_min": -47, "lat_max": -34, "lng_min": 166, "lng_max": 179},
    "Spain": {"lat_min": 36, "lat_max": 43, "lng_min": -9, "lng_max": 4},
    "Switzerland": {"lat_min": 45.8, "lat_max": 47.8, "lng_min": 5.9, "lng_max": 10.5},
    "Taiwan": {"lat_min": 21.9, "lat_max": 25.3, "lng_min": 120.0, "lng_max": 121.9},
    "Thailand": {"lat_min": 5.6, "lat_max": 20.5, "lng_min": 97.3, "lng_max": 105.6},
    "United Kingdom": {"lat_min": 50, "lat_max": 59, "lng_min": -2, "lng_max": 2},
}


def load_dataset(name: str) -> tuple[bool, list]:
    """Load dataset, return (success, records)."""
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        print(f"  ⚠️  Not found: {name}.json")
        return False, []
    with open(path) as f:
        return True, json.load(f)


def test_japan() -> bool:
    """Test Japan data (should be locked and unchanged)."""
    print("\n📍 JAPAN DINING")
    print("─" * 60)

    success, records = load_dataset("japan-restaurants")
    if not success:
        return False

    expected_count = 843
    expected_tabelog_coverage = 0.97  # 97%

    # Test 1: Exact count
    if len(records) != expected_count:
        print(f"  ❌ Count mismatch: {len(records)} (expected {expected_count})")
        return False

    # Test 2: No duplicates
    ids = set()
    for rec in records:
        if rec.get("id") in ids:
            print(f"  ❌ Duplicate ID: {rec.get('id')}")
            return False
        ids.add(rec.get("id"))

    # Test 3: All coordinates valid
    missing_coords = sum(1 for r in records if r.get("lat") is None or r.get("lng") is None)
    if missing_coords > 0:
        print(f"  ❌ {missing_coords} records missing coordinates")
        return False

    # Test 4: Load quality signals for coverage check
    signals_path = DATA_DIR / "restaurant-quality-signals.json"
    if signals_path.exists():
        with open(signals_path) as f:
            signals = json.load(f)
        with_signals = sum(1 for r in records if r.get("id") in signals)
        coverage = with_signals / len(records) if records else 0
        if coverage < expected_tabelog_coverage - 0.01:  # Allow 1% drift
            print(f"  ⚠️  Tabelog coverage dropped: {coverage:.1%} (expected >{expected_tabelog_coverage:.0%})")

    print(f"  ✅ Japan data OK ({len(records)} restaurants, locked)")
    return True


def test_global() -> bool:
    """Test Global Dining data."""
    print("\n🌍 GLOBAL DINING")
    print("─" * 60)

    success, records = load_dataset("global-restaurants")
    if not success:
        return False

    # Test 1: Reasonable count (2,000 ±10%, since current has 2,470)
    if len(records) < 1800 or len(records) > 2700:
        print(f"  ⚠️  Count suspicious: {len(records)} (expected ~2,000-2,470)")

    # Test 2: Check for known duplicate IDs
    id_count = defaultdict(int)
    for rec in records:
        id_count[rec.get("id")] += 1

    duplicates = [k for k, v in id_count.items() if v > 1]
    if duplicates:
        print(f"  ❌ Duplicate IDs found: {len(duplicates)}")
        for dup_id in duplicates[:3]:
            print(f"     {dup_id}")
        return False

    # Test 3: Coordinates present
    with_coords = sum(1 for r in records if r.get("lat") is not None)
    coverage = 100 * with_coords / len(records) if records else 0
    if coverage < 90:
        print(f"  ❌ Low coordinate coverage: {coverage:.1f}% (expected >90%)")
        return False

    # Test 4: All 16 countries present
    countries = set(r.get("country") for r in records if r.get("country"))
    expected_countries = {
        "Australia", "Austria", "Belgium", "Canada", "France",
        "Germany", "Hong Kong", "Japan", "Mexico", "Netherlands",
        "New Zealand", "Spain", "Switzerland", "Taiwan", "Thailand",
        "United Kingdom"
    }
    if len(countries) < 15:
        print(f"  ❌ Missing countries: only {len(countries)} found")
        return False

    # Test 5: GPS bounds check - coordinates within country bounds
    out_of_bounds = 0
    for rec in records:
        country = rec.get("country")
        lat = rec.get("lat")
        lng = rec.get("lng")

        if not country or lat is None or lng is None:
            continue

        bounds = COUNTRY_BOUNDS.get(country)
        if bounds:
            lat_ok = bounds["lat_min"] <= lat <= bounds["lat_max"]
            lng_ok = bounds["lng_min"] <= lng <= bounds["lng_max"]
            if not (lat_ok and lng_ok):
                out_of_bounds += 1

    if out_of_bounds > 0:
        print(f"  ❌ {out_of_bounds} venues outside country GPS bounds (wrong country matches)")
        return False

    print(f"  ✅ Global data OK ({len(records)} restaurants, GPS validated)")
    return True


def test_plat_stay() -> bool:
    """Test Plat Stay data."""
    print("\n🏨 PLAT STAY")
    print("─" * 60)

    success, records = load_dataset("plat-stays")
    if not success:
        return False

    expected_count = 69

    # Test 1: Count reasonable (69±10%)
    if len(records) < 62 or len(records) > 76:
        print(f"  ⚠️  Count off: {len(records)} (expected {expected_count})")

    # Test 2: No duplicates
    ids = set()
    for rec in records:
        if rec.get("id") in ids:
            print(f"  ❌ Duplicate ID: {rec.get('id')}")
            return False
        ids.add(rec.get("id"))

    # Test 3: Coordinates present
    missing_coords = sum(1 for r in records if r.get("lat") is None or r.get("lng") is None)
    if missing_coords > 5:  # Allow 5 without coords
        print(f"  ⚠️  {missing_coords} records missing coordinates")

    # Test 4: Coordinates valid
    invalid = 0
    for rec in records:
        lat, lng = rec.get("lat"), rec.get("lng")
        if lat is not None and lng is not None:
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                invalid += 1

    if invalid > 0:
        print(f"  ❌ {invalid} invalid coordinates")
        return False

    print(f"  ✅ Plat Stay OK ({len(records)} properties)")
    return True


def test_love_dining() -> bool:
    """Test Love Dining data (CRITICAL)."""
    print("\n❤️  LOVE DINING (Singapore)")
    print("─" * 60)

    success, records = load_dataset("love-dining")
    if not success:
        return False

    expected_count = 79

    # Test 1: Exact count
    if len(records) != expected_count:
        print(f"  ⚠️  Count off: {len(records)} (expected {expected_count})")

    # Test 2: **CRITICAL** All must have coordinates
    missing_coords = sum(1 for r in records if r.get("lat") is None or r.get("lng") is None)
    if missing_coords > 0:
        print(f"  ❌ CRITICAL: {missing_coords} records missing coordinates")
        print(f"     (This is the original problem that needs fixing)")
        return False

    # Test 3: No duplicates
    ids = set()
    for rec in records:
        if rec.get("id") in ids:
            print(f"  ❌ Duplicate ID: {rec.get('id')}")
            return False
        ids.add(rec.get("id"))

    # Test 4: All in Singapore bounds (roughly 1.2-1.5N, 103.6-104.1E)
    out_of_bounds = 0
    for rec in records:
        lat, lng = rec.get("lat"), rec.get("lng")
        if lat is not None and lng is not None:
            if not (1.0 <= lat <= 1.6 and 103.5 <= lng <= 104.2):
                out_of_bounds += 1

    if out_of_bounds > 0:
        print(f"  ❌ {out_of_bounds} records outside Singapore bounds")
        return False

    print(f"  ✅ Love Dining OK ({len(records)} venues with coordinates)")
    return True


def test_ratings() -> bool:
    """Test Google Maps ratings coverage."""
    print("\n⭐ GOOGLE MAPS RATINGS")
    print("─" * 60)

    ratings_path = DATA_DIR / "google-maps-ratings.json"
    if not ratings_path.exists():
        print(f"  ⚠️  Not found: google-maps-ratings.json")
        return True

    with open(ratings_path) as f:
        ratings = json.load(f)

    # Load all records to calculate coverage
    total_records = 0
    total_with_ratings = 0

    for dataset_name in ["japan-restaurants", "global-restaurants", "plat-stays", "love-dining"]:
        success, records = load_dataset(dataset_name)
        if not success:
            continue

        total_records += len(records)
        for rec in records:
            if rec.get("id") in ratings:
                total_with_ratings += 1

    coverage = 100 * total_with_ratings / total_records if total_records else 0
    if coverage < 50:
        print(f"  ⚠️  Low coverage: {coverage:.1f}% ({total_with_ratings}/{total_records})")
    else:
        print(f"  ✅ Ratings coverage: {coverage:.1f}% ({total_with_ratings}/{total_records})")

    return True


def main() -> bool:
    """Run all regression tests."""
    print("\n" + "="*80)
    print("REGRESSION TEST: Data Integrity Check")
    print("="*80)
    print(f"Run: {datetime.now().isoformat()}")

    tests = [
        test_japan,
        test_global,
        test_plat_stay,
        test_love_dining,
        test_ratings,
    ]

    results = []
    for test in tests:
        try:
            passed = test()
            results.append(passed)
        except Exception as e:
            print(f"  ❌ ERROR: {str(e)}")
            results.append(False)

    # Summary
    print("\n" + "="*80)
    print("REGRESSION TEST SUMMARY")
    print("="*80)
    passed = sum(results)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")

    if passed == total:
        print("\n✅ All regression tests passed - data integrity OK")
        return True
    else:
        print("\n❌ Some tests failed - data integrity issues detected")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
