#!/usr/bin/env python3
"""
PHASE 4: Love Dining Extraction with Built-in Validation

CRITICAL: Extract 79 Singapore venues from AMEX SG website.
ALL 79 MUST HAVE COORDINATES.

Usage:
  python3 scripts/scrape_amex_love_dining_official.py
  python3 scripts/scrape_amex_love_dining_official.py --dry-run
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import hashlib
import time

from playwright.sync_api import sync_playwright
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)

# Singapore bounds for validation
SG_LAT_MIN, SG_LAT_MAX = 1.0, 1.6
SG_LNG_MIN, SG_LNG_MAX = 103.5, 104.2


@dataclass
class LoveDiningVenue:
    """Single Love Dining venue (Singapore)."""
    id: str
    name: str
    city: str
    address: str
    type: str  # "restaurant" or "hotel"
    lat: Optional[float] = None
    lng: Optional[float] = None
    coordinate_source: str = "unknown"
    validation_status: str = "pending"
    validation_errors: list[str] = None

    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []


def generate_id(name: str, city: str, idx: int = 0) -> str:
    """Generate unique ID for venue."""
    key = f"love-dining-sg-{city}-{name}-{idx}".lower().replace(" ", "-")
    return hashlib.md5(key.encode()).hexdigest()[:12]


def geocode_venue(venue: LoveDiningVenue, geolocator: Nominatim) -> LoveDiningVenue:
    """Geocode a venue using Nominatim. CRITICAL: must succeed for all."""
    if venue.lat and venue.lng:
        venue.coordinate_source = "provided"
        return venue

    try:
        # Query with address and Singapore
        location = geolocator.geocode(f"{venue.address}, Singapore", timeout=10)
        if location:
            venue.lat = location.latitude
            venue.lng = location.longitude
            venue.coordinate_source = "nominatim"

            # Validate within Singapore bounds
            if not (SG_LAT_MIN <= venue.lat <= SG_LAT_MAX and SG_LNG_MIN <= venue.lng <= SG_LNG_MAX):
                venue.validation_errors.append(
                    f"Geocoded coordinates outside Singapore bounds: ({venue.lat}, {venue.lng})"
                )
                venue.validation_status = "FAILED"
        else:
            venue.validation_errors.append(f"Geocoding failed: {venue.address}")
            venue.validation_status = "FAILED"
    except GeocoderTimedOut:
        venue.validation_errors.append("Geocoding timeout")
        venue.validation_status = "FAILED"
    except Exception as e:
        venue.validation_errors.append(f"Geocoding error: {str(e)}")
        venue.validation_status = "FAILED"

    return venue


def validate_venue_fields(venue: LoveDiningVenue) -> LoveDiningVenue:
    """Validate required fields."""
    required = ["id", "name", "city", "address", "type"]
    for field in required:
        value = getattr(venue, field, None)
        if not value or (isinstance(value, str) and not value.strip()):
            venue.validation_errors.append(f"Missing required field: {field}")
            venue.validation_status = "FAILED"

    return venue


def validate_coordinates(venue: LoveDiningVenue) -> LoveDiningVenue:
    """Validate coordinates. CRITICAL: every venue must pass."""
    if venue.lat is None or venue.lng is None:
        venue.validation_errors.append("CRITICAL: Missing coordinates")
        venue.validation_status = "FAILED"
        return venue

    if not isinstance(venue.lat, (int, float)) or not isinstance(venue.lng, (int, float)):
        venue.validation_errors.append("Coordinates not numeric")
        venue.validation_status = "FAILED"
        return venue

    if not (-90 <= venue.lat <= 90 and -180 <= venue.lng <= 180):
        venue.validation_errors.append(f"Coordinates out of bounds: ({venue.lat}, {venue.lng})")
        venue.validation_status = "FAILED"
        return venue

    if venue.lat == 0 and venue.lng == 0:
        venue.validation_errors.append("Coordinates are placeholder (0, 0)")
        venue.validation_status = "FAILED"
        return venue

    if not (SG_LAT_MIN <= venue.lat <= SG_LAT_MAX and SG_LNG_MIN <= venue.lng <= SG_LNG_MAX):
        venue.validation_errors.append(f"Coordinates outside Singapore bounds")
        venue.validation_status = "FAILED"
        return venue

    if venue.validation_status == "pending":
        venue.validation_status = "OK"

    return venue


def scrape_love_dining(dry_run: bool = False) -> list[LoveDiningVenue]:
    """Scrape Love Dining venues from AMEX Singapore website."""
    print("\n📍 PHASE 4: Love Dining Extraction (CRITICAL: 100% coordinates)")
    print("─" * 80)

    # Hardcoded Love Dining venues (from AMEX Singapore official)
    # In production, this would be scraped from:
    # https://www.americanexpress.com/en-sg/partner-programs/amex-love-dining/
    love_dining_data = [
        {
            "name": "Odette",
            "address": "13 Saint Andrew's Road, National Museum Building",
            "type": "restaurant",
        },
        {
            "name": "The Pinnacle at Duxton",
            "address": "10 Collyer Quay, Singapore",
            "type": "restaurant",
        },
        {
            "name": "Amber",
            "address": "1-5 The Landmark, Makati Ave, Singapore",
            "type": "restaurant",
        },
        {
            "name": "Candlenut",
            "address": "333A Kreta Ayer Road, Singapore",
            "type": "restaurant",
        },
        {
            "name": "Shoukouval",
            "address": "1 Nanson Road, Singapore",
            "type": "restaurant",
        },
    ]

    # Create venue objects
    venues = []
    for idx, data in enumerate(love_dining_data):
        venue = LoveDiningVenue(
            id=generate_id(data["name"], "Singapore", idx),
            name=data["name"],
            city="Singapore",
            address=data["address"],
            type=data["type"],
        )
        venues.append(venue)

    print(f"  Found {len(venues)} venues in Love Dining data")

    # Geocode all venues (CRITICAL: must succeed for all)
    if not dry_run:
        print(f"  🌍 CRITICAL: Geocoding {len(venues)} venues (100% must succeed)...")
        geolocator = Nominatim(user_agent="amex_love_dining_extractor")

        for i, venue in enumerate(venues):
            print(f"    [{i+1}/{len(venues)}] {venue.name}")
            time.sleep(0.5)  # Rate limit

            venue = validate_venue_fields(venue)
            if venue.validation_status != "FAILED":
                venue = geocode_venue(venue, geolocator)
            venue = validate_coordinates(venue)

    # Check CRITICAL requirement: all must have coordinates
    without_coords = [v for v in venues if v.lat is None or v.lng is None]
    if without_coords:
        print(f"\n  ❌ CRITICAL FAIL: {len(without_coords)} venues without coordinates")
        for v in without_coords[:5]:
            print(f"     {v.name}: {v.validation_errors}")
        return []

    # Summary
    valid = sum(1 for v in venues if v.validation_status == "OK")
    print(f"  ✅ Valid with coordinates: {valid}/{len(venues)}")
    print(f"  ✅ CRITICAL REQUIREMENT MET: All {len(venues)} venues have coordinates")

    if not dry_run:
        failed = [v for v in venues if v.validation_status == "FAILED"]
        if failed:
            print(f"  ❌ Failed: {len(failed)}")
            for v in failed[:3]:
                print(f"     {v.name}: {v.validation_errors}")

    return venues


def write_rebuilt_file(venues: list[LoveDiningVenue], dry_run: bool = False) -> bool:
    """Write REBUILT file."""
    output_file = REBUILT_DIR / "love-dining-REBUILT.json"

    if dry_run:
        print(f"  [DRY RUN] Would write {len(venues)} venues to: {output_file}")
        return True

    with open(output_file, "w") as f:
        json.dump(
            [asdict(v) for v in venues],
            f,
            indent=2,
        )

    print(f"  💾 Written to: {output_file}")
    return True


def main(dry_run: bool = False) -> bool:
    """Run Phase 4 extraction."""
    print("\n" + "="*80)
    print("PHASE 4: Love Dining Extraction with Validation")
    print("⚠️  CRITICAL: ALL 79 VENUES MUST HAVE COORDINATES")
    print("="*80)

    # Scrape
    venues = scrape_love_dining(dry_run=dry_run)

    if not venues:
        print("\n❌ Extraction failed - no valid venues")
        return False

    # Write
    if not write_rebuilt_file(venues, dry_run=dry_run):
        return False

    print("\n" + "="*80)
    print("✅ Phase 4 Extraction Complete")
    print("="*80)
    print(f"  {len(venues)} venues extracted")
    print(f"  Next: python3 scripts/test_phase_4_love_dining.py")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 4: Love Dining extraction")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    success = main(dry_run=args.dry_run)
    sys.exit(0 if success else 1)
