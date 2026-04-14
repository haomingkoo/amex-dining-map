#!/usr/bin/env python3
"""
Generate data audit report: count of records per program/country/city.

Use this to cross-check against official AMEX sources:
- Japan: https://www.americanexpress.com/ja/benefits/platinum/
- Global: platinumdining.caffeinesoftware.com
- Plat Stay: AMEX Platinum benefits
- Love Dining: AMEX Singapore

Provides counts you can manually verify.
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"


def audit_japan():
    """Japan dining via Pocket Concierge."""
    with open(DATA_DIR / "japan-restaurants.json") as f:
        records = json.load(f)

    print("\n" + "="*80)
    print("JAPAN DINING (Pocket Concierge)")
    print("="*80)
    print(f"Total restaurants: {len(records)}")

    # By city
    by_city = defaultdict(int)
    for rec in records:
        city = rec.get("city", "UNKNOWN")
        by_city[city] += 1

    print(f"\nTop cities ({len(by_city)} total):")
    for city, count in sorted(by_city.items(), key=lambda x: -x[1])[:20]:
        print(f"  {city:30} {count:3} restaurants")
    if len(by_city) > 20:
        print(f"  ... and {len(by_city) - 20} more cities")


def audit_global():
    """Global Dining Credit."""
    with open(DATA_DIR / "global-restaurants.json") as f:
        records = json.load(f)

    print("\n" + "="*80)
    print("GLOBAL DINING CREDIT (16 countries)")
    print("="*80)
    print(f"Total restaurants: {len(records)}")

    # By country
    by_country = defaultdict(int)
    for rec in records:
        country = rec.get("country", "UNKNOWN")
        by_country[country] += 1

    print(f"\nBy country ({len(by_country)} total):")
    for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
        print(f"  {country:30} {count:3} restaurants")


def audit_plat_stay():
    """Plat Stay properties."""
    with open(DATA_DIR / "plat-stays.json") as f:
        records = json.load(f)

    print("\n" + "="*80)
    print("PLAT STAY (Properties)")
    print("="*80)
    print(f"Total properties: {len(records)}")

    # By country
    by_country = defaultdict(int)
    for rec in records:
        country = rec.get("country", "UNKNOWN")
        by_country[country] += 1

    print(f"\nBy country ({len(by_country)} total):")
    for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
        print(f"  {country:30} {count:3} properties")


def audit_love_dining():
    """Love Dining Singapore."""
    with open(DATA_DIR / "love-dining.json") as f:
        records = json.load(f)

    print("\n" + "="*80)
    print("LOVE DINING (Singapore)")
    print("="*80)
    print(f"Total venues: {len(records)}")

    # By venue type
    venue_types = defaultdict(int)
    for rec in records:
        # Infer type from name/fields
        venue_types["Venue"] += 1

    print(f"\nVenues: {venue_types['Venue']}")


def main():
    print("\n" + "="*80)
    print("DATA AUDIT REPORT")
    print("Manual verification against official AMEX sources")
    print("="*80)

    audit_japan()
    audit_global()
    audit_plat_stay()
    audit_love_dining()

    print("\n" + "="*80)
    print("VERIFICATION CHECKLIST")
    print("="*80)
    print("""
To verify data integrity, cross-check against official AMEX sources:

Japan:
  - Visit AMEX Japan Platinum page
  - Count total Pocket Concierge restaurants
  - Compare with above

Global Dining:
  - Visit platinumdining.caffeinesoftware.com
  - Count restaurants per country
  - Compare with above counts

Plat Stay:
  - Check AMEX Platinum Plat Stay benefits page
  - Count properties per country
  - Compare with above

Love Dining:
  - Check AMEX Singapore Love Dining benefits
  - Count restaurants/hotels
  - Compare with above

IF COUNTS DON'T MATCH:
  - We have data corruption (extra/missing records)
  - Run data_sanity_check.py to find issues
  - Check for duplicates, invalid records, wrong programs
""")


if __name__ == "__main__":
    main()
