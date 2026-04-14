#!/usr/bin/env python3
"""
Parse AMEX dining HTML sample to extract restaurants with real selectors.

Usage:
  python3 scripts/parse_amex_html_sample.py /path/to/sample.html
"""

import json
import sys
from pathlib import Path
from typing import Optional
import re
import hashlib

from html.parser import HTMLParser
import html

DATA_DIR = Path(__file__).parent.parent / "data"


def extract_coordinates_from_maps_url(maps_url: str) -> tuple[Optional[float], Optional[float]]:
    """Extract latitude and longitude from Google Maps URL.

    URL format: https://www.google.com/maps/search/.../@LAT,LNG/
    """
    if not maps_url:
        return None, None

    # Look for @lat,lng pattern
    match = re.search(r'@([-\d.]+),([-\d.]+)', maps_url)
    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
            return lat, lng
        except (ValueError, IndexError):
            pass

    return None, None


def extract_city_from_address(address: str) -> str:
    """Extract city name from address string.

    Usually the second line or after the first <br>.
    """
    if not address:
        return "Unknown"

    lines = address.split('\n')
    lines = [line.strip() for line in lines if line.strip()]

    # City is usually the last line
    if len(lines) >= 2:
        return lines[-1]
    elif lines:
        return lines[0]

    return "Unknown"


def generate_id(country: str, name: str, city: str, index: int = 1) -> str:
    """Generate unique ID for restaurant."""
    key = f"amex-{country}-{city}-{name}-{index}".lower().replace(" ", "-")
    return hashlib.md5(key.encode()).hexdigest()[:12]


def parse_html_sample(html_file: str, country: str) -> list[dict]:
    """Parse AMEX HTML sample using regex to extract restaurants.

    Real selectors discovered from actual AMEX HTML:
    - Restaurant card: div.shuffle-card
    - Name: First text in div.sc-dCFHLb (after flags)
    - Address: div.sc-fhzFiK
    - Cuisine: Text in div.sc-jxOSlx (after SVG)
    - Maps link: a[href*="google.com/maps"]
    """
    print(f"\n📄 Parsing {Path(html_file).name} ({country})...")

    with open(html_file) as f:
        html_content = f.read()

    # Find all shuffle-card divs - simpler approach
    card_pattern = r'<div class="[^"]*shuffle-card[^"]*"[^>]*>(.*?)(?=<div class="[^"]*shuffle-card|</div>\s*</div>\s*</div>\s*</div>\s*</html>)'
    cards = re.findall(card_pattern, html_content, re.DOTALL)
    print(f"  Found {len(cards)} restaurant cards")

    if not cards:
        # Fallback: split by shuffle-card divs
        parts = html_content.split('class="shuffle-card')
        cards = parts[1:] if len(parts) > 1 else []
        print(f"  Fallback: Found {len(cards)} parts with shuffle-card")

    restaurants = []
    seen_names = {}

    for idx, card_html in enumerate(cards):
        try:
            # Extract name from sc-dCFHLb div
            name_match = re.search(
                r'<div class="[^"]*sc-dCFHLb[^"]*"[^>]*>.*?</div>\s*([^<]+)',
                card_html,
                re.DOTALL
            )
            name = name_match.group(1).strip() if name_match else None
            name = re.sub(r'<[^>]+>', '', name).strip() if name else None

            if not name or len(name) < 2:
                continue

            # Track name for duplicate detection
            if name not in seen_names:
                seen_names[name] = 1
                name_idx = 1
            else:
                seen_names[name] += 1
                name_idx = seen_names[name]

            # Extract address from sc-fhzFiK div
            address_match = re.search(
                r'<div class="[^"]*sc-fhzFiK[^"]*"[^>]*>(.*?)</div>',
                card_html,
                re.DOTALL
            )
            if address_match:
                address = address_match.group(1)
                address = re.sub(r'<br\s*/?>', ' ', address)
                address = re.sub(r'<[^>]+>', '', address)
                address = ' '.join(address.split())
            else:
                address = "Unknown"

            # Extract cuisine from sc-jxOSlx div (text after SVG)
            cuisine_match = re.search(
                r'<div class="[^"]*sc-jxOSlx[^"]*"[^>]*>.*?</svg>\s*([^<]+)',
                card_html,
                re.DOTALL
            )
            cuisine = cuisine_match.group(1).strip() if cuisine_match else None

            # Extract maps URL
            maps_match = re.search(
                r'<a[^>]*href="(https://www\.google\.com/maps/[^"]*)"',
                card_html
            )
            maps_url = maps_match.group(1) if maps_match else None
            lat, lng = extract_coordinates_from_maps_url(maps_url)

            # Extract city from address
            city = extract_city_from_address(address)

            # Create restaurant record
            restaurant = {
                "id": generate_id(country, name, city, name_idx),
                "name": name,
                "country": country,
                "city": city,
                "address": address,
                "cuisine": cuisine,
                "lat": lat,
                "lng": lng,
                "maps_url": maps_url,
                "coordinate_source": "maps_url" if lat else "unknown",
            }

            restaurants.append(restaurant)

        except Exception as e:
            print(f"  ⚠️  Card {idx}: {str(e)}")
            continue

    print(f"  ✅ Extracted {len(restaurants)} restaurants")

    return restaurants


def main():
    """Parse one or more HTML samples."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse AMEX HTML samples")
    parser.add_argument("html_file", help="Path to HTML sample file")
    parser.add_argument("--country", default="Unknown", help="Country name")
    parser.add_argument("--output", default=None, help="Output JSON file")
    args = parser.parse_args()

    html_file = Path(args.html_file)
    if not html_file.exists():
        print(f"❌ File not found: {html_file}")
        return False

    # Parse
    restaurants = parse_html_sample(str(html_file), args.country)

    if not restaurants:
        print(f"\n❌ No restaurants extracted")
        return False

    # Print sample
    print(f"\n📊 Sample restaurants:")
    for r in restaurants[:3]:
        print(f"  {r['name']}")
        print(f"    {r['address']}")
        print(f"    Cuisine: {r['cuisine']}")
        print(f"    Coords: ({r['lat']}, {r['lng']})")
        print()

    # Save if output specified
    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(restaurants, f, indent=2)
        print(f"💾 Saved {len(restaurants)} restaurants to: {output_file}")

    print(f"\n✅ Successfully extracted {len(restaurants)} restaurants from {args.country}")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
