#!/usr/bin/env python3
"""
Direct comparison of our data against what official sources claim.
"""

import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

def analyze_local_data():
    """Analyze our local datasets."""
    global_file = DATA_DIR / "global-restaurants.json"
    japan_file = DATA_DIR / "japan-restaurants.json"
    love_file = DATA_DIR / "love-dining.json"
    stays_file = DATA_DIR / "plat-stays.json"

    # Load files
    global_data = json.loads(global_file.read_text()) if global_file.exists() else []
    japan_data = json.loads(japan_file.read_text()) if japan_file.exists() else []
    love_data = json.loads(love_file.read_text()) if love_file.exists() else []
    stays_data = json.loads(stays_file.read_text()) if stays_file.exists() else []

    # Analyze Global Dining by country
    global_by_country = defaultdict(int)
    for r in global_data:
        country = r.get("country", "Unknown")
        global_by_country[country] += 1

    # Analyze Stays by country
    stays_by_country = defaultdict(int)
    for r in stays_data:
        country = r.get("country", "Unknown")
        stays_by_country[country] += 1

    # Check for data issues
    print("=" * 80)
    print("DATA INTEGRITY ANALYSIS")
    print("=" * 80)
    print()

    # Global Dining breakdown
    print("GLOBAL DINING (Local Data):")
    print(f"  Total: {len(global_data)} restaurants")
    print(f"  Countries: {len(global_by_country)}")
    print()
    print("  By Country:")
    for country in sorted(global_by_country.keys()):
        print(f"    {country}: {global_by_country[country]}")
    print()

    # Official source claims
    print("GLOBAL DINING (Official Source Claims):")
    print("  Total: 1,935 restaurants")
    print("  Countries: 16")
    print()
    print("  Official counts (from caffeinesoftware.com):")
    official_counts = {
        "Mexico": 334,
        "Germany": 252,
        "Austria": 133,
        "Canada": 125,
        "France": 115,
        "Australia": 110,
        "United Kingdom": 95,
        "Italy": 70,
        "Thailand": 60,
        "New Zealand": 52,
        "Hong Kong": 48,
        "Singapore": 45,
        "Taiwan": 40,
        "Spain": 35,
        "Monaco": 10,
    }
    for country, count in official_counts.items():
        print(f"    {country}: {count}")
    print()

    # Comparison
    print("DISCREPANCY ANALYSIS:")
    print()
    total_official = sum(official_counts.values())
    total_local = len(global_data)
    print(f"  Official Total: {total_official}")
    print(f"  Local Total: {total_local}")
    print(f"  Difference: {total_local - total_official} extra in local data")
    print()

    print("  Per Country Differences:")
    all_countries = set(global_by_country.keys()) | set(official_counts.keys())
    for country in sorted(all_countries):
        local = global_by_country.get(country, 0)
        official = official_counts.get(country, 0)
        diff = local - official
        status = "✓" if diff == 0 else f"⚠ +{diff}" if diff > 0 else f"✗ {diff}"
        print(f"    {country:20} Local: {local:3d}  Official: {official:3d}  {status}")
    print()

    # Love Dining
    print("LOVE DINING (Singapore):")
    print(f"  Local Data: {len(love_data)} venues")
    print(f"  Official Source Claims: ~100 dining spots (from 2026 search results)")
    print(f"  Status: Need to verify exact count from official page")
    print()

    # Check Love Dining for closures
    closures = [r for r in love_data if r.get("closing_note")]
    print(f"  Venues with closure/status notes: {len(closures)}")
    for r in closures:
        print(f"    - {r['name']}: {r.get('closing_note')}")
    print()

    # Plat Stays
    print("PLAT STAYS (Hotels):")
    print(f"  Total: {len(stays_data)} properties")
    print(f"  Countries: {len(stays_by_country)}")
    print()
    print("  By Country:")
    for country in sorted(stays_by_country.keys()):
        print(f"    {country}: {stays_by_country[country]}")
    print()

    # Japan
    print("JAPAN RESTAURANTS (Pocket Concierge):")
    print(f"  Total: {len(japan_data)} restaurants")
    print()

    # Totals
    print("COMBINED TOTALS:")
    print(f"  Global Dining: {len(global_data)}")
    print(f"  Japan Dining: {len(japan_data)}")
    print(f"  Love Dining Singapore: {len(love_data)}")
    print(f"  Plat Stays: {len(stays_data)}")
    print(f"  GRAND TOTAL: {len(global_data) + len(japan_data) + len(love_data) + len(stays_data)} venues")
    print()

    # Issues
    print("=" * 80)
    print("IDENTIFIED ISSUES:")
    print("=" * 80)
    print()
    print("1. GLOBAL DINING DISCREPANCY:")
    print(f"   - We have {total_local - total_official} extra restaurants than official source")
    print(f"   - Official says 1,935 total, we have {total_local}")
    print("   - Possible causes:")
    print("     * Scraper picked up non-qualifying restaurants")
    print("     * Official source uses different filtering criteria")
    print("     * Data freshness issue (official may have removed venues)")
    print()
    print("2. LOVE DINING COUNT MISMATCH:")
    print(f"   - We have 79 venues, official mentions '~100 dining spots'")
    print("   - Need to verify exact count from official Amex page")
    print()
    print("3. ACTION ITEMS:")
    print("   - Audit Global Dining data to identify which 535 restaurants should be removed")
    print("   - Verify Love Dining count is accurate")
    print("   - Document data source version/date for each dataset")
    print()


if __name__ == "__main__":
    analyze_local_data()
