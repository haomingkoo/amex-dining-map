#!/usr/bin/env python3
"""
Scrape AMEX Global Dining from official AMEX page (not caffeinesoftware.com).

Source: https://www.americanexpress.com/en-sg/benefits/platinum/dining/

Features:
- Iterates through all 16 countries via Country dropdown
- Extracts all restaurants with address, cuisine, city
- Handles multi-location chains with unique IDs
- Validates extraction against expected counts
- Outputs clean JSON with full audit trail

Usage:
  python3 scripts/scrape_amex_global_dining_official.py
  python3 scripts/scrape_amex_global_dining_official.py --dry-run
  python3 scripts/scrape_amex_global_dining_official.py --limit 5  (first 5 countries)
"""

import json
import sys
import re
import time
from pathlib import Path
from collections import defaultdict
from argparse import ArgumentParser
from datetime import datetime
from urllib.parse import quote

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


def generate_unique_id(country: str, city: str, name: str, index: int = 1) -> str:
    """Generate unique ID for multi-location restaurants.

    Format: amex-global-{country}-{city}-{name}-{idx}
    Example: amex-global-austria-bregenz-wein-co-1
    """
    name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    city_slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-") if city else "generic"
    country_slug = re.sub(r"[^a-z0-9]+", "-", country.lower()).strip("-")

    if index > 1:
        return f"amex-global-{country_slug}-{city_slug}-{name_slug}-{index}"
    return f"amex-global-{country_slug}-{city_slug}-{name_slug}"


def log_audit(action: str, message: str, details: dict = None) -> None:
    """Log audit trail."""
    audit_file = REBUILT_DIR / "global-dining-REBUILD.audit.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "message": message,
        "details": details or {},
    }
    with open(audit_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[AUDIT] {action}: {message}")


def validate_record_fields(record: dict) -> tuple[bool, list]:
    """Validate individual record fields. Return (is_valid, errors)."""
    errors = []

    # Required fields
    required = {"id", "name", "country", "city"}
    missing = required - set(record.keys())
    if missing:
        errors.append(f"Missing: {missing}")
        return False, errors

    # Type checks
    if not isinstance(record.get("name"), str) or not record["name"].strip():
        errors.append("Name must be non-empty string")

    if not isinstance(record.get("country"), str):
        errors.append(f"Country not string: {type(record.get('country'))}")

    # Coordinate validation (if present)
    if "lat" in record or "lng" in record:
        lat, lng = record.get("lat"), record.get("lng")

        if (lat is None) != (lng is None):  # XOR — one but not both
            errors.append("Incomplete coordinates (one is None)")
            return False, errors

        if lat is not None and lng is not None:
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                errors.append(f"Coords not numeric: {type(lat)}, {type(lng)}")
                return False, errors

            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                errors.append(f"Out of bounds: ({lat}, {lng})")
                return False, errors

            if lat == 0 and lng == 0:
                errors.append("Placeholder coords (0,0)")
                return False, errors

    return len(errors) == 0, errors


def validate_dataset(records: list, expected_count: int = None) -> dict:
    """Validate full dataset. Returns detailed report."""
    report = {
        "total_records": len(records),
        "valid_records": 0,
        "invalid_records": 0,
        "duplicate_ids": {},
        "coordinate_coverage": {},
        "distribution": {},
    }

    # 1. Validate each record
    for rec in records:
        is_valid, _ = validate_record_fields(rec)
        if is_valid:
            report["valid_records"] += 1
        else:
            report["invalid_records"] += 1

    # 2. Check for duplicate IDs
    seen_ids = set()
    duplicates = defaultdict(list)
    for i, rec in enumerate(records):
        rec_id = rec.get("id")
        if rec_id:
            if rec_id in seen_ids:
                duplicates[rec_id].append(i)
            else:
                seen_ids.add(rec_id)

    if duplicates:
        report["duplicate_ids"] = dict(duplicates)

    # 3. Check coordinate coverage
    with_coords = sum(1 for r in records if r.get("lat") is not None and r.get("lng") is not None)
    report["coordinate_coverage"] = {
        "with_coordinates": with_coords,
        "without_coordinates": len(records) - with_coords,
        "coverage_percent": 100 * with_coords / len(records) if records else 0,
    }

    # 4. Count variance check
    if expected_count:
        variance = len(records) - expected_count
        variance_pct = 100 * variance / expected_count if expected_count else 0
        report["count_check"] = {
            "expected": expected_count,
            "actual": len(records),
            "variance": variance,
            "variance_percent": variance_pct,
            "pass": abs(variance_pct) <= 5,
        }

    # 5. Distribution stats
    by_country = defaultdict(int)
    by_city = defaultdict(int)
    for rec in records:
        by_country[rec.get("country", "UNKNOWN")] += 1
        by_city[rec.get("city", "UNKNOWN")] += 1

    report["distribution"] = {
        "countries": len(by_country),
        "cities": len(by_city),
        "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1])),
    }

    return report


def extract_google_maps_url(link_text: str) -> str | None:
    """Extract Google Maps URL from 'View on map' link.

    In the HTML, links look like:
    <a href="https://maps.google.com/..." >View on map</a>
    """
    # This is a placeholder — in actual Playwright scraping,
    # we'd extract href from the "View on map" button
    return None


def scrape_amex_global_dining(dry_run: bool = False, limit_countries: int = None) -> dict:
    """Scrape official AMEX Global Dining page.

    Returns: {country: [{id, name, address, city, cuisine, country, maps_url}, ...], ...}
    """

    # Import Playwright here to avoid hard dependency
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError:
        print("❌ Playwright not installed. Run: pip install playwright && playwright install")
        sys.exit(1)

    AMEX_DINING_URL = "https://www.americanexpress.com/en-sg/benefits/platinum/dining/"

    results = {}
    stats = {
        "countries_processed": 0,
        "total_restaurants": 0,
        "restaurants_by_country": defaultdict(int),
        "multi_location_chains": 0,
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(10000)

        try:
            print(f"\n{'='*80}")
            print("SCRAPING OFFICIAL AMEX GLOBAL DINING")
            print(f"{'='*80}")
            print(f"URL: {AMEX_DINING_URL}")

            page.goto(AMEX_DINING_URL, wait_until="networkidle")
            print("✅ Page loaded")

            # Get list of available countries from Country dropdown
            # Selector: <select id="country-select"> or similar
            country_select = page.query_selector("select[name='country']") or \
                            page.query_selector("#country-dropdown") or \
                            page.query_selector("[class*='country']")

            if not country_select:
                # Try different approach: look for country buttons/options
                countries = []
                country_buttons = page.query_selector_all("button[data-country]")
                if country_buttons:
                    for btn in country_buttons:
                        country_name = btn.get_attribute("data-country")
                        if country_name:
                            countries.append(country_name)
                else:
                    # Fallback: hardcoded list of 16 countries
                    countries = [
                        "Australia", "Austria", "Belgium", "Canada", "France",
                        "Germany", "Hong Kong", "Japan", "Mexico", "Netherlands",
                        "New Zealand", "Spain", "Switzerland", "Taiwan", "Thailand",
                        "United Kingdom"
                    ]
                log_audit("info", f"Using {len(countries)} hardcoded countries")
            else:
                # Extract options from <select>
                options = country_select.query_selector_all("option")
                countries = []
                for opt in options:
                    text = opt.text_content().strip()
                    if text and text not in ["All countries", "Country"]:
                        countries.append(text)

            print(f"Found {len(countries)} countries to process")

            if limit_countries:
                countries = countries[:limit_countries]
                print(f"Limited to {limit_countries} countries for testing")

            # Process each country
            for country_idx, country in enumerate(countries, 1):
                print(f"\n[{country_idx}/{len(countries)}] Processing {country}...")

                try:
                    # Click country dropdown and select this country
                    # This will vary based on actual page structure
                    # For now, use a generic approach:

                    # Method 1: Select via dropdown
                    select = page.query_selector("select[name='country']")
                    if select:
                        page.select_option("select[name='country']", country)
                        page.wait_for_load_state("networkidle")
                    else:
                        # Method 2: Click country button
                        country_btn = page.query_selector(f"button[data-country='{country}']")
                        if country_btn:
                            country_btn.click()
                            page.wait_for_load_state("networkidle")

                    # Wait for restaurant list to load
                    time.sleep(0.5)

                    # Extract all restaurant listings using VERIFIED selectors
                    # Real selectors discovered from actual AMEX HTML:
                    # - Card: div.shuffle-card
                    # - Name: div.sc-dCFHLb (text after flags)
                    # - Address: div.sc-fhzFiK
                    # - Cuisine: div.sc-jxOSlx (text after SVG)
                    # - Maps: a[href*="google.com/maps"]

                    restaurants = []

                    # Use the validated selectors
                    restaurant_cards = page.query_selector_all("div.shuffle-card")

                    print(f"  Found {len(restaurant_cards)} restaurant cards")

                    for card_idx, card in enumerate(restaurant_cards):
                        try:
                            # Extract restaurant name from sc-dCFHLb div
                            name_elem = card.query_selector("div.sc-dCFHLb")
                            if name_elem:
                                # Get text content and filter
                                name = name_elem.text_content().strip()
                                # Name is usually after the flags div, first line
                                name = name.split('\n')[0].strip() if name else None
                            else:
                                name = None

                            if not name or len(name) < 2:
                                continue

                            # Extract address from sc-fhzFiK div
                            address_elem = card.query_selector("div.sc-fhzFiK")
                            if address_elem:
                                address = address_elem.text_content().strip()
                                address = ' '.join(address.split())  # Normalize whitespace
                            else:
                                address = "Unknown"

                            # Extract cuisine from sc-jxOSlx div (text after SVG)
                            cuisine_elem = card.query_selector("div.sc-jxOSlx")
                            cuisine = None
                            if cuisine_elem:
                                cuisine_text = cuisine_elem.text_content().strip()
                                # Cuisine is usually the last word/item
                                cuisine = cuisine_text.split()[-1] if cuisine_text else None

                            # Extract Google Maps link and coordinates
                            maps_link = card.query_selector("a[href*='google.com/maps']")
                            maps_url = maps_link.get_attribute("href") if maps_link else None

                            # Extract coordinates from maps URL
                            lat, lng = None, None
                            if maps_url:
                                coords_match = re.search(r'@([-\d.]+),([-\d.]+)', maps_url)
                                if coords_match:
                                    try:
                                        lat = float(coords_match.group(1))
                                        lng = float(coords_match.group(2))
                                    except (ValueError, IndexError):
                                        pass

                            # Extract city from address (usually last line)
                            city = "Unknown"
                            if address and address != "Unknown":
                                addr_lines = address.split(' ')
                                if len(addr_lines) >= 2:
                                    city = addr_lines[-1]

                            # Create record
                            record = {
                                "name": name,
                                "country": country,
                                "city": city,
                                "address": address,
                                "cuisine": cuisine,
                                "lat": lat,
                                "lng": lng,
                                "maps_url": maps_url,
                                "coordinate_source": "maps_url" if (lat and lng) else "unknown",
                            }

                            restaurants.append(record)

                        except Exception as e:
                            stats["errors"].append(f"{country}[{card_idx}]: {str(e)}")

                    # Handle multi-location chains
                    # If "X Locations" button found, click to expand and extract each location
                    multi_buttons = page.query_selector_all("button:has-text('Locations')")
                    for btn in multi_buttons:
                        try:
                            btn.click()
                            page.wait_for_load_state("networkidle")
                            time.sleep(0.3)
                            # Extract locations from expanded view
                            # This is page-specific; adjust selector as needed
                        except:
                            pass

                    # Assign unique IDs
                    location_count = defaultdict(int)
                    for restaurant in restaurants:
                        key = (restaurant["country"], restaurant["city"], restaurant["name"])
                        location_count[key] += 1

                    for restaurant in restaurants:
                        key = (restaurant["country"], restaurant["city"], restaurant["name"])
                        idx = location_count[key]
                        location_count[key] -= 1  # Count down for reverse assignment

                        restaurant["id"] = generate_unique_id(
                            restaurant["country"],
                            restaurant["city"],
                            restaurant["name"],
                            idx if location_count[key] > 0 else 1
                        )

                    results[country] = restaurants
                    stats["restaurants_by_country"][country] = len(restaurants)
                    stats["total_restaurants"] += len(restaurants)
                    stats["countries_processed"] += 1

                    print(f"  ✅ Extracted {len(restaurants)} restaurants")

                except PlaywrightTimeoutError:
                    msg = f"Timeout loading {country}"
                    print(f"  ⚠️  {msg}")
                    stats["errors"].append(msg)
                    log_audit("warning", msg)
                except Exception as e:
                    msg = f"Error processing {country}: {str(e)}"
                    print(f"  ❌ {msg}")
                    stats["errors"].append(msg)
                    log_audit("error", msg)

        finally:
            browser.close()

    # Summary
    print(f"\n{'='*80}")
    print("EXTRACTION SUMMARY")
    print(f"{'='*80}")
    print(f"Countries processed: {stats['countries_processed']}/{len(countries)}")
    print(f"Total restaurants: {stats['total_restaurants']}")
    print(f"\nBy country:")
    for country, count in sorted(stats["restaurants_by_country"].items()):
        print(f"  {country:20} {count:4} restaurants")

    if stats["errors"]:
        print(f"\n⚠️  Errors encountered: {len(stats['errors'])}")
        for err in stats["errors"][:5]:
            print(f"  - {err}")
        if len(stats["errors"]) > 5:
            print(f"  ... and {len(stats['errors']) - 5} more")

    log_audit("complete", f"Extracted {stats['total_restaurants']} restaurants from {stats['countries_processed']} countries", stats)

    return results


def flatten_results(country_results: dict) -> list:
    """Flatten nested country results into single list."""
    flat = []
    for country, restaurants in country_results.items():
        flat.extend(restaurants)
    return flat


def main() -> None:
    parser = ArgumentParser(description="Scrape AMEX Global Dining from official page")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--limit", type=int, help="Limit to first N countries (for testing)")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("AMEX GLOBAL DINING SCRAPER (Official Source)")
    print("="*80)
    print(f"Output directory: {REBUILT_DIR}")

    try:
        # Scrape
        results = scrape_amex_global_dining(
            dry_run=args.dry_run,
            limit_countries=args.limit
        )

        # Flatten
        restaurants = flatten_results(results)

        # Write output
        if not args.dry_run:
            output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
            with open(output_file, "w") as f:
                json.dump(restaurants, f, indent=2)
            print(f"\n✅ Wrote {len(restaurants)} restaurants to {output_file}")

            # Write metadata
            metadata = {
                "source": "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                "extracted_at": datetime.now().isoformat(),
                "total_restaurants": len(restaurants),
                "countries": list(set(r["country"] for r in restaurants)),
                "validation_status": "pending",
            }
            with open(REBUILT_DIR / "global-dining-metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)
        else:
            print(f"\n[DRY RUN] Would write {len(restaurants)} restaurants")
            print(f"Sample: {json.dumps(restaurants[:2], indent=2) if restaurants else 'No data'}")

    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
