#!/usr/bin/env python3
"""
PRE-DEPLOYMENT DATA SANITY CHECK

Run this before ANY deployment to catch data corruption, duplicates,
invalid coordinates, and structural issues.

Usage:
  python3 scripts/data_sanity_check.py
  python3 scripts/data_sanity_check.py --strict  (fails on any warning)
"""

import json
import math
import sys
from pathlib import Path
from collections import defaultdict
from argparse import ArgumentParser

DATA_DIR = Path(__file__).parent.parent / "data"
ISSUES = {"errors": [], "warnings": [], "info": []}


def log_error(msg):
    ISSUES["errors"].append(msg)
    print(f"  ❌ {msg}")


def log_warn(msg):
    ISSUES["warnings"].append(msg)
    print(f"  ⚠️  {msg}")


def log_info(msg):
    ISSUES["info"].append(msg)
    print(f"  ℹ️  {msg}")


# ============================================================================
# VALIDATION RULES
# ============================================================================

def check_required_fields(records, dataset_name):
    """All records must have id and name."""
    print(f"\n1️⃣  Required fields...")
    required = ["id", "name"]
    for i, rec in enumerate(records):
        for field in required:
            if not rec.get(field):
                log_error(f"{dataset_name}[{i}]: missing '{field}'")


def check_duplicate_ids(records, dataset_name):
    """No duplicate IDs allowed."""
    print(f"2️⃣  Duplicate IDs...")
    id_count = defaultdict(list)
    for i, rec in enumerate(records):
        rec_id = rec.get("id")
        if rec_id:
            id_count[rec_id].append(i)

    duplicates = {k: v for k, v in id_count.items() if len(v) > 1}
    if duplicates:
        log_error(f"{dataset_name}: {len(duplicates)} duplicate IDs found:")
        for dup_id, indices in sorted(duplicates.items()):
            names = [records[i].get("name") for i in indices]
            log_error(f"  ID '{dup_id}': {len(indices)} records {names}")
    else:
        log_info(f"{dataset_name}: no duplicates")


def check_coordinates(records, dataset_name):
    """Validate coordinate format and bounds."""
    print(f"3️⃣  Coordinates...")
    invalid = 0
    missing = 0
    suspicious = 0

    for i, rec in enumerate(records):
        lat = rec.get("lat")
        lng = rec.get("lng")
        name = rec.get("name", "UNNAMED")

        # Missing coords
        if lat is None or lng is None:
            missing += 1
            continue

        # Type check
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            log_error(f"{dataset_name}[{i}] {name}: coords not numeric")
            invalid += 1
            continue

        # Range check
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            log_error(f"{dataset_name}[{i}] {name}: out of bounds ({lat}, {lng})")
            invalid += 1
            continue

        # Exact 0,0 is suspicious
        if lat == 0 and lng == 0:
            log_error(f"{dataset_name}[{i}] {name}: coordinates at 0,0")
            suspicious += 1

    total = len(records)
    valid = total - missing - invalid
    pct = 100 * valid / total if total > 0 else 0
    log_info(f"{dataset_name}: {valid}/{total} valid ({pct:.1f}%)")
    if missing > 0:
        log_warn(f"{dataset_name}: {missing} records missing coordinates")


def check_google_ratings_coverage(records, dataset_name, ratings):
    """Check that most records have Google ratings."""
    print(f"4️⃣  Google ratings coverage...")
    total = len(records)
    with_ratings = sum(1 for r in records if r.get("id") in ratings)
    missing = total - with_ratings
    pct = 100 * with_ratings / total if total > 0 else 0

    log_info(f"{dataset_name}: {with_ratings}/{total} have ratings ({pct:.1f}%)")
    if missing > 0 and missing / total > 0.05:  # More than 5% missing
        log_warn(f"{dataset_name}: {missing} records ({100*missing/total:.1f}%) missing ratings")


def check_orphaned_ratings(ratings, all_record_ids):
    """Check for ratings without corresponding records."""
    print(f"5️⃣  Orphaned ratings...")
    orphaned = [rid for rid in ratings.keys() if rid not in all_record_ids]
    if orphaned:
        log_warn(f"{len(orphaned)} ratings have no corresponding record: {orphaned[:5]}")
    else:
        log_info("No orphaned ratings")


def check_data_types(records, dataset_name):
    """Validate data types."""
    print(f"6️⃣  Data types...")
    for i, rec in enumerate(records):
        # Strings
        for str_field in ["id", "name", "country", "city"]:
            val = rec.get(str_field)
            if val is not None and not isinstance(val, str):
                log_error(f"{dataset_name}[{i}]: {str_field} is not string: {type(val)}")

        # Numbers
        for num_field in ["lat", "lng"]:
            val = rec.get(num_field)
            if val is not None and not isinstance(val, (int, float)):
                log_error(f"{dataset_name}[{i}]: {num_field} is not number: {type(val)}")

        # Arrays
        for arr_field in ["cuisines"]:
            val = rec.get(arr_field)
            if val is not None and not isinstance(val, list):
                log_error(f"{dataset_name}[{i}]: {arr_field} is not array: {type(val)}")


def check_coordinate_consistency(records, ratings, dataset_name):
    """Warn if stored coords differ significantly from Google Maps."""
    print(f"7️⃣  Coordinate consistency (vs Google Maps)...")

    def extract_coords(url):
        import re
        m = re.search(r'/@([-\d.]+),([-\d.]+),', url)
        return (float(m.group(1)), float(m.group(2))) if m else None

    def haversine_m(lat1, lng1, lat2, lng2):
        R = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lng2 - lng1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    large_diffs = 0
    for rec in records:
        lat = rec.get("lat")
        lng = rec.get("lng")
        if lat is None or lng is None:
            continue

        rating = ratings.get(rec.get("id"), {})
        url = rating.get("maps_url", "")
        if not url:
            continue

        gmaps_coords = extract_coords(url)
        if not gmaps_coords:
            continue

        dist = haversine_m(lat, lng, gmaps_coords[0], gmaps_coords[1])
        if dist > 500:  # 500m is very far
            log_warn(f"{dataset_name}: {rec.get('name')} is {dist:.0f}m off from Google Maps")
            large_diffs += 1

    if large_diffs == 0:
        log_info(f"{dataset_name}: coordinate consistency OK (all <500m)")


# ============================================================================
# MAIN VALIDATION
# ============================================================================

def main(strict=False):
    print("\n" + "="*80)
    print("DATA SANITY CHECK")
    print("="*80)

    # Load data
    datasets = {}
    for name in ["japan-restaurants.json", "global-restaurants.json",
                 "plat-stays.json", "love-dining.json"]:
        path = DATA_DIR / name
        if path.exists():
            with open(path) as f:
                datasets[name] = json.load(f)

    with open(DATA_DIR / "google-maps-ratings.json") as f:
        ratings = json.load(f)

    # Collect all record IDs
    all_record_ids = set()
    for records in datasets.values():
        all_record_ids.update(r.get("id") for r in records if r.get("id"))

    # Run checks per dataset
    for dataset_name, records in datasets.items():
        print(f"\n{'─'*80}")
        print(f"📦 {dataset_name}")
        print(f"{'─'*80}")
        check_required_fields(records, dataset_name)
        check_duplicate_ids(records, dataset_name)
        check_coordinates(records, dataset_name)
        check_google_ratings_coverage(records, dataset_name, ratings)
        check_data_types(records, dataset_name)
        check_coordinate_consistency(records, ratings, dataset_name)

    # Global checks
    print(f"\n{'─'*80}")
    print(f"🌍 Global checks")
    print(f"{'─'*80}")
    check_orphaned_ratings(ratings, all_record_ids)

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Info:     {len(ISSUES['info'])} items")
    print(f"⚠️  Warnings: {len(ISSUES['warnings'])} items")
    print(f"❌ Errors:   {len(ISSUES['errors'])} items")

    if ISSUES["errors"]:
        print(f"\n🚫 VALIDATION FAILED - {len(ISSUES['errors'])} errors found")
        return False
    elif ISSUES["warnings"]:
        if strict:
            print(f"\n🚫 VALIDATION FAILED (strict mode) - {len(ISSUES['warnings'])} warnings")
            return False
        else:
            print(f"\n⚠️  VALIDATION PASSED with {len(ISSUES['warnings'])} warnings")
            print("   (Run with --strict to fail on warnings)")
            return True
    else:
        print(f"\n✅ VALIDATION PASSED - all checks OK")
        return True


if __name__ == "__main__":
    parser = ArgumentParser(description="Data sanity check before deployment")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings")
    args = parser.parse_args()

    success = main(strict=args.strict)
    sys.exit(0 if success else 1)
