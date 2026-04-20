#!/usr/bin/env python3
"""
Build Phase 3-4 REBUILT outputs:
- Phase 3: Plat Stay properties (69 records)
- Phase 4: Love Dining venues (79 records)

Usage:
  python3 scripts/build_all_rebuilt.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


def log_audit(audit_file: Path, action: str, message: str, details: dict = None) -> None:
    """Write audit trail entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "message": message,
        "details": details or {},
    }
    with open(audit_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def validate_plat_stay(record: dict) -> tuple[bool, list]:
    """Validate a plat stay property."""
    errors = []

    required = ["id", "name", "country"]
    for field in required:
        if not record.get(field):
            errors.append(f"missing {field}")

    # Check coordinates if present
    if record.get("lat") is not None or record.get("lng") is not None:
        lat = record.get("lat")
        lng = record.get("lng")
        if lat is not None and lng is not None:
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                errors.append("coordinates not numeric")
            elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
                errors.append(f"coordinates out of bounds: ({lat}, {lng})")

    return len(errors) == 0, errors


def validate_love_dining(record: dict) -> tuple[bool, list]:
    """Validate a love dining venue."""
    errors = []

    required = ["id", "name"]
    for field in required:
        if not record.get(field):
            errors.append(f"missing {field}")

    # Check coordinates if present
    if record.get("lat") is not None or record.get("lng") is not None:
        lat = record.get("lat")
        lng = record.get("lng")
        if lat is not None and lng is not None:
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                errors.append("coordinates not numeric")
            # Love Dining is Singapore-only, tight bounds
            elif not (1.2 <= lat <= 1.5 and 103.6 <= lng <= 104.0):
                errors.append(f"coordinates outside Singapore: ({lat}, {lng})")

    return len(errors) == 0, errors


def build_plat_stays():
    """Build Phase 3 REBUILT."""
    print("\n" + "="*80)
    print("PHASE 3: Build REBUILT from plat-stays.json")
    print("="*80 + "\n")

    AUDIT_FILE = REBUILT_DIR / "plat-stays-REBUILD.audit.jsonl"
    OUTPUT_FILE = REBUILT_DIR / "plat-stays-REBUILT.json"
    AUDIT_FILE.write_text("")

    log_audit(AUDIT_FILE, "info", "Starting Phase 3 Plat Stays REBUILT build")

    # Load source
    source_file = DATA_DIR / "plat-stays.json"
    if not source_file.exists():
        print(f"❌ Source file not found: {source_file}")
        return False

    print(f"📄 Loading: {source_file.name}")
    with open(source_file) as f:
        records = json.load(f)

    print(f"✅ Loaded {len(records)} properties\n")
    log_audit(AUDIT_FILE, "info", f"Loaded {len(records)} records from source")

    # Validate
    print("🔍 Validating...")
    valid_records = []
    seen_ids = set()
    errors_found = 0
    duplicates = 0

    for record in records:
        rec_id = record.get("id")
        if rec_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(rec_id)

        is_valid, errors = validate_plat_stay(record)
        record["validation_status"] = "OK" if is_valid else "FAILED"
        if errors:
            record["validation_errors"] = errors

        if is_valid:
            valid_records.append(record)
        else:
            errors_found += 1

    print(f"✅ Valid: {len(valid_records)}, Failed: {errors_found}, Duplicates: {duplicates}\n")

    # Write
    with open(OUTPUT_FILE, "w") as f:
        json.dump(valid_records, f, indent=2)

    print(f"📝 Output: {OUTPUT_FILE.name}")
    print(f"✅ Phase 3 complete: {len(valid_records)} properties\n")

    log_audit(AUDIT_FILE, "complete", f"Built REBUILT with {len(valid_records)} properties", {
        "total": len(valid_records),
        "failed": errors_found,
        "duplicates": duplicates,
    })

    return True


def build_love_dining():
    """Build Phase 4 REBUILT."""
    print("\n" + "="*80)
    print("PHASE 4: Build REBUILT from love-dining.json")
    print("="*80 + "\n")

    AUDIT_FILE = REBUILT_DIR / "love-dining-REBUILD.audit.jsonl"
    OUTPUT_FILE = REBUILT_DIR / "love-dining-REBUILT.json"
    AUDIT_FILE.write_text("")

    log_audit(AUDIT_FILE, "info", "Starting Phase 4 Love Dining REBUILT build")

    # Load source
    source_file = DATA_DIR / "love-dining.json"
    if not source_file.exists():
        print(f"❌ Source file not found: {source_file}")
        return False

    print(f"📄 Loading: {source_file.name}")
    with open(source_file) as f:
        records = json.load(f)

    print(f"✅ Loaded {len(records)} venues\n")
    log_audit(AUDIT_FILE, "info", f"Loaded {len(records)} records from source")

    # Count by type
    by_type = {}
    for r in records:
        t = r.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    print(f"📊 Breakdown:")
    for t in sorted(by_type.keys()):
        print(f"   {t}: {by_type[t]}")

    # Validate
    print(f"\n🔍 Validating...")
    valid_records = []
    seen_ids = set()
    errors_found = 0
    duplicates = 0

    for record in records:
        rec_id = record.get("id")
        if rec_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(rec_id)

        is_valid, errors = validate_love_dining(record)
        record["validation_status"] = "OK" if is_valid else "FAILED"
        if errors:
            record["validation_errors"] = errors

        if is_valid:
            valid_records.append(record)
        else:
            errors_found += 1

    print(f"✅ Valid: {len(valid_records)}, Failed: {errors_found}, Duplicates: {duplicates}\n")

    # Write
    with open(OUTPUT_FILE, "w") as f:
        json.dump(valid_records, f, indent=2)

    print(f"📝 Output: {OUTPUT_FILE.name}")
    print(f"✅ Phase 4 complete: {len(valid_records)} venues\n")

    log_audit(AUDIT_FILE, "complete", f"Built REBUILT with {len(valid_records)} venues", {
        "total": len(valid_records),
        "failed": errors_found,
        "duplicates": duplicates,
        "by_type": by_type,
    })

    return True


if __name__ == "__main__":
    success = (
        build_plat_stays() and
        build_love_dining()
    )

    if success:
        print("\n" + "="*80)
        print("✅ All REBUILT files ready for Phase 5 validation")
        print("="*80)

    sys.exit(0 if success else 1)
