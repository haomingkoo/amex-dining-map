#!/usr/bin/env python3
"""
MASTER DATA REBUILD SCRIPT

Extracts clean, deduplicated data from official AMEX sources:
1. Plat Stay PDF
2. Love Dining PDFs (Restaurants + Hotels)
3. Global Dining (rescrape with dedup)
4. Japan (keep existing Tabelog data)

Usage:
  python3 scripts/rebuild_data_from_sources.py --phase 1  # Extract from PDFs
  python3 scripts/rebuild_data_from_sources.py --phase 2  # Rescrape Global
  python3 scripts/rebuild_data_from_sources.py --validate   # Validate all
"""

import json
import sys
import hashlib
import re
from pathlib import Path
from collections import defaultdict
from argparse import ArgumentParser
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
SOURCES_DIR = DATA_DIR / "sources"  # Place PDFs here
REBUILT_DIR = DATA_DIR / "rebuilt"  # Output goes here

SOURCES_DIR.mkdir(exist_ok=True)
REBUILT_DIR.mkdir(exist_ok=True)


def log_audit(filename, action, message, details=None):
    """Log extraction audit trail."""
    audit_file = REBUILT_DIR / f"{filename}.audit.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "message": message,
        "details": details or {},
    }
    with open(audit_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[AUDIT] {filename}: {action} — {message}")


def generate_unique_id(record_type, country, city, name, index=1):
    """Generate unique ID for multi-location records.

    Examples:
      amex-plat-stay-china-chengdu-fraser-place
      amex-global-austria-bregenz-wein-co-1
      amex-love-dining-sg-restaurant-sen-of-japan
    """
    # Slug: lowercase, remove special chars, replace spaces
    name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    city_slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-") if city else "generic"
    country_slug = re.sub(r"[^a-z0-9]+", "-", country.lower()).strip("-")

    if record_type == "plat-stay":
        return f"amex-plat-stay-{country_slug}-{city_slug}-{name_slug}"
    elif record_type == "love-dining":
        return f"amex-love-dining-sg-{city_slug}-{name_slug}"
    elif record_type == "global":
        if index > 1:
            return f"amex-global-{country_slug}-{city_slug}-{name_slug}-{index}"
        return f"amex-global-{country_slug}-{city_slug}-{name_slug}"
    elif record_type == "japan":
        return f"amex-japan-{city_slug}-{name_slug}"


def phase_1_extract_pdfs():
    """Extract data from official AMEX PDFs."""
    print("\n" + "="*80)
    print("PHASE 1: Extract from Official AMEX PDFs")
    print("="*80)

    # Check if PDFs exist
    plat_stay_pdf = SOURCES_DIR / "platstay.pdf"
    love_rest_pdf = SOURCES_DIR / "Love_Dining_Restaurants_TnC.pdf"
    love_hotels_pdf = SOURCES_DIR / "Love_Dining_Hotels_TnC.pdf"

    if not plat_stay_pdf.exists():
        print(f"❌ Missing: {plat_stay_pdf}")
        print(f"   Download from: https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/platstay.pdf?extlink=SG")
        return False

    if not love_rest_pdf.exists() or not love_hotels_pdf.exists():
        print(f"❌ Missing Love Dining PDFs")
        print(f"   Restaurants: {love_rest_pdf}")
        print(f"   Hotels: {love_hotels_pdf}")
        return False

    print(f"✅ PDFs found")
    print(f"   - {plat_stay_pdf.name}")
    print(f"   - {love_rest_pdf.name}")
    print(f"   - {love_hotels_pdf.name}")

    # For now, log that we need manual extraction or Playwright
    log_audit("phase-1", "info", "PDF extraction requires: pdfplumber or Playwright for React content")
    log_audit("phase-1", "manual", "Extract from PDFs and save as JSON to: sources/extracted/")

    print(f"\n⚠️  Next steps:")
    print(f"   1. Install: pip install pdfplumber")
    print(f"   2. Run extraction script (coming next)")
    print(f"   3. Output: {REBUILT_DIR}/plat-stays-REBUILT.json")
    print(f"   4. Output: {REBUILT_DIR}/love-dining-REBUILT.json")

    return True


def phase_2_rescrape_global():
    """Rescrape Global Dining with proper deduplication."""
    print("\n" + "="*80)
    print("PHASE 2: Rescrape Global Dining (16 countries)")
    print("="*80)

    print(f"⚠️  Run: python3 scripts/scrape_global_dining.py --fresh")
    print(f"   Output to: {REBUILT_DIR}/global-restaurants-REBUILT.json")
    print(f"\n   Then run deduplication:")
    print(f"   python3 scripts/deduplicate_global_dining.py")

    log_audit("phase-2", "pending", "Rescrape global dining with dedup strategy")


def phase_validate():
    """Validate all rebuilt datasets."""
    print("\n" + "="*80)
    print("PHASE VALIDATE: Run Data Sanity Checks")
    print("="*80)

    print(f"Run: python3 scripts/data_sanity_check.py --strict")
    print(f"\nExpected output:")
    print(f"  ✅ Zero duplicate IDs")
    print(f"  ✅ All coordinates <200m from Google Maps")
    print(f"  ✅ Counts match official AMEX")
    print(f"  ✅ No 'wrong country' matches")
    print(f"  ✅ Full audit trail")


def phase_deploy():
    """Deploy rebuilt datasets to production."""
    print("\n" + "="*80)
    print("PHASE DEPLOY: Merge Rebuilt Data")
    print("="*80)

    print(f"Manual steps:")
    print(f"  1. Verify all REBUILT files pass validation")
    print(f"  2. Backup current data:")
    print(f"     git mv data/global-restaurants.json data/global-restaurants.BACKUP.json")
    print(f"  3. Move rebuilt files:")
    print(f"     mv {REBUILT_DIR}/plat-stays-REBUILT.json data/plat-stays.json")
    print(f"     mv {REBUILT_DIR}/love-dining-REBUILT.json data/love-dining.json")
    print(f"     mv {REBUILT_DIR}/global-restaurants-REBUILT.json data/global-restaurants.json")
    print(f"  4. Run validation one final time")
    print(f"  5. Commit: git add data/*.json && git commit -m 'data: rebuild from official AMEX sources'")


def main():
    parser = ArgumentParser(description="Master data rebuild from official AMEX sources")
    parser.add_argument("--phase", type=int, choices=[1, 2], help="Which phase to run")
    parser.add_argument("--validate", action="store_true", help="Run validation phase")
    parser.add_argument("--deploy", action="store_true", help="Show deployment steps")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("AMEX DATA REBUILD PIPELINE")
    print("="*80)
    print(f"\nSources directory: {SOURCES_DIR}")
    print(f"Output directory: {REBUILT_DIR}")

    if args.phase == 1:
        success = phase_1_extract_pdfs()
        sys.exit(0 if success else 1)

    elif args.phase == 2:
        phase_2_rescrape_global()

    elif args.validate:
        phase_validate()

    elif args.deploy:
        phase_deploy()

    else:
        print("\n" + "="*80)
        print("OVERALL WORKFLOW")
        print("="*80)
        print(f"""
Step 1: Download PDFs to {SOURCES_DIR}/
  - playstay.pdf
  - Love_Dining_Restaurants_TnC.pdf
  - Love_Dining_Hotels_TnC.pdf

Step 2: Extract from PDFs
  python3 scripts/rebuild_data_from_sources.py --phase 1

Step 3: Rescrape Global Dining
  python3 scripts/rebuild_data_from_sources.py --phase 2

Step 4: Validate
  python3 scripts/rebuild_data_from_sources.py --validate
  python3 scripts/data_sanity_check.py --strict

Step 5: Deploy
  python3 scripts/rebuild_data_from_sources.py --deploy
  (then manually move files and commit)

Sources of Truth:
  ✅ Japan: Keep existing Tabelog data (already verified)
  ✅ Plat Stay: Official AMEX PDF
  ✅ Love Dining: Official AMEX PDFs (Restaurants + Hotels)
  ✅ Global Dining: platinumdining.caffeinesoftware.com (rescrape properly)
""")


if __name__ == "__main__":
    main()
