#!/usr/bin/env python3
"""
Build Phase 2 REBUILT output from existing global-restaurants.json

This script takes the validated global-restaurants.json data and packages it
for the Phase 2 test suite, with proper audit trail and validation status.

Usage:
  python3 scripts/build_global_rebuilt.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)

REBUILT_FILE = REBUILT_DIR / "global-restaurants-REBUILT.json"
AUDIT_FILE = REBUILT_DIR / "global-dining-REBUILD.audit.jsonl"


def log_audit(action: str, message: str, details: dict = None) -> None:
    """Write audit trail entry."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "message": message,
        "details": details or {},
    }
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def infer_country_from_coords(lat: float, lng: float) -> str | None:
    """Infer country from coordinates."""
    if not lat or not lng:
        return None

    # Singapore (1.2-1.5, 103.6-104.0)
    if 1.2 <= lat <= 1.5 and 103.6 <= lng <= 104.0:
        return "Singapore"
    # Add more regions as needed
    return None


def validate_record(record: dict) -> tuple[bool, list]:
    """Validate a single restaurant record.

    Returns: (is_valid, error_list)
    """
    errors = []

    # Check required fields
    required = ["id", "name", "country"]
    for field in required:
        if not record.get(field):
            errors.append(f"missing {field}")

    # Check and correct country from coordinates if needed
    lat = record.get("lat")
    lng = record.get("lng")
    if lat is not None and lng is not None:
        inferred = infer_country_from_coords(lat, lng)
        if inferred and record.get("country") != inferred:
            record["country"] = inferred
            record["_country_corrected"] = True

    # Check coordinates if present
    if record.get("lat") is not None or record.get("lng") is not None:
        lat = record.get("lat")
        lng = record.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            errors.append("coordinates not numeric")
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            errors.append(f"coordinates out of global bounds: ({lat}, {lng})")

    return len(errors) == 0, errors


def build_rebuilt():
    """Build REBUILT output."""
    print("\n" + "=" * 80)
    print("PHASE 2: Build REBUILT from existing global-restaurants.json")
    print("=" * 80 + "\n")

    # Clear audit file
    AUDIT_FILE.write_text("")
    log_audit("info", "Starting Phase 2 REBUILT build")

    # Load source data
    source_file = DATA_DIR / "global-restaurants.json"
    if not source_file.exists():
        print(f"❌ Source file not found: {source_file}")
        log_audit("error", f"Source file not found: {source_file}")
        return False

    print(f"📄 Loading source: {source_file.name}")
    with open(source_file) as f:
        records = json.load(f)

    print(f"✅ Loaded {len(records)} records\n")
    log_audit("info", f"Loaded {len(records)} records from source")

    # Process and validate
    print("🔍 Validating records...")
    valid_records = []
    seen_ids = set()
    by_country = {}
    errors_found = 0
    duplicates_skipped = 0

    for record in records:
        # Skip duplicate IDs
        record_id = record.get("id")
        if record_id in seen_ids:
            duplicates_skipped += 1
            continue
        seen_ids.add(record_id)

        # Add validation status
        is_valid, errors = validate_record(record)
        record["validation_status"] = "OK" if is_valid else "FAILED"
        if errors:
            record["validation_errors"] = errors

        if is_valid:
            valid_records.append(record)
            country = record.get("country", "Unknown")
            by_country[country] = by_country.get(country, 0) + 1
        else:
            errors_found += 1

    print(f"✅ Validated: {len(valid_records)} valid, {errors_found} failed")
    print(f"⚠️  Deduplicated: {duplicates_skipped} duplicate IDs removed\n")
    log_audit("info", f"Validated {len(valid_records)} records", {
        "valid_count": len(valid_records),
        "failed_count": errors_found,
        "duplicates_removed": duplicates_skipped,
    })

    # Write REBUILT file
    print(f"📝 Writing REBUILT: {REBUILT_FILE.name}")
    with open(REBUILT_FILE, "w") as f:
        json.dump(valid_records, f, indent=2)
    print(f"✅ Wrote {len(valid_records)} records\n")

    # Summary by country
    print("📊 Distribution by country:")
    for country in sorted(by_country.keys()):
        count = by_country[country]
        pct = 100 * count / len(valid_records) if valid_records else 0
        print(f"   {country}: {count} ({pct:.1f}%)")

    # Final audit
    log_audit("complete", f"Built REBUILT with {len(valid_records)} records", {
        "total_records": len(valid_records),
        "countries": len(by_country),
        "failed_records": errors_found,
        "restaurants_by_country": by_country,
    })

    print(f"\n✅ Phase 2 REBUILT complete!")
    print(f"   Output: {REBUILT_FILE}")
    print(f"   Audit trail: {AUDIT_FILE}\n")

    return True


if __name__ == "__main__":
    success = build_rebuilt()
    sys.exit(0 if success else 1)
