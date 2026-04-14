#!/usr/bin/env python3
"""
Test parser for AMEX Global Dining HTML samples.

Use this to validate extraction logic before running full Playwright scraper.
Parses the HTML structure the user provided from the official AMEX page.

Example usage:
  python3 scripts/parse_amex_html_samples.py < /tmp/amex-hong-kong.html
"""

import sys
import re
import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"


def parse_amex_html(html_content: str) -> list:
    """Parse AMEX Global Dining HTML and extract restaurants.

    Expected HTML structure (from official AMEX page):
    ```html
    <div class="restaurant-listing">
      <h3>Restaurant Name</h3>
      <p>Street Address, City</p>
      <p>Postal Code</p>
      <p class="cuisine">Cuisine Type</p>
      <a href="...google maps...">View on map</a>
    </div>
    ```
    """

    restaurants = []
    country = None
    city = None

    # Extract country from <select> or heading
    country_match = re.search(r'<option[^>]*selected[^>]*>([^<]+)</option>', html_content)
    if not country_match:
        country_match = re.search(r'Country:\s*</h\d>\s*<p>([^<]+)</p>', html_content)
    if not country_match:
        country_match = re.search(r'>([A-Z][a-z\s]+)</option>', html_content)

    if country_match:
        country = country_match.group(1).strip()

    # Extract city from <select> or content
    city_match = re.search(r'City:\s*</\w+>\s*<p>([^<]+)</p>', html_content)
    if city_match:
        city = city_match.group(1).strip()

    print(f"Parsing HTML: Country={country}, City={city}")

    # Split HTML into restaurant blocks
    # Look for pattern: heading (h1-h6 or strong/bold) followed by address lines
    # Then restaurant name, address, cuisine, map link

    # Pattern 1: Name on its own line, then address, then city, then postal, then cuisine
    restaurant_pattern = r'([A-Z][^<]*?)\s*<[^>]*>\s*([^<]+[A-Z][^<]+)\s*<[^>]*>\s*([A-Z][a-z\s]+)\s*<[^>]*>\s*(\d+)\s*<[^>]*>\s*([A-Z][^<]+)\s*<[^>]*>\s*(?:View on map|Make a booking)'

    # More flexible approach: find restaurant names (all caps or Title Case start of a line)
    # Look for lines with addresses, cuisines, and map links

    lines = html_content.split('<br>') + html_content.split('<br/>')

    current_restaurant = None
    for line in lines:
        line = line.strip()

        # Skip empty lines and UI text
        if not line or line in ['View on map', 'Make a booking:', 'Country:', 'City:', 'Cuisine:', 'All cities', 'All cuisines']:
            continue

        # Remove HTML tags
        clean_line = re.sub(r'<[^>]+>', '', line).strip()

        if not clean_line:
            continue

        # Detect restaurant name: usually a short line with title case
        if (len(clean_line) < 80 and
                (clean_line[0].isupper() or "'" in clean_line or "(" in clean_line) and
                "\n" not in clean_line and
                not any(x in clean_line for x in ['View on map', 'Make a booking', 'Phone:', '+'])):

            # Check if this looks like an address (has numbers, street indicators)
            if not any(x in clean_line for x in [', Street', 'Road', 'St.', 'Rd.', 'Avenue', 'Ave.', 'Lane', 'Blvd', 'Drive', 'Square']):
                # Likely a restaurant name
                if current_restaurant:
                    restaurants.append(current_restaurant)

                current_restaurant = {
                    "name": clean_line,
                    "country": country,
                    "city": city,
                    "address": None,
                    "cuisine": None,
                    "maps_url": None,
                }

        # Detect address: contains street/avenue/road indicators or numbers
        elif current_restaurant and any(x in clean_line for x in [', Street', 'Road', 'Rd.', 'Avenue', 'Ave.', 'Lane', 'Blvd', 'Str.', 'St.', '/F', 'Floor', 'Level']):
            if not current_restaurant["address"]:
                current_restaurant["address"] = clean_line
            elif "cuisine" not in str(current_restaurant):
                # Multi-line address
                current_restaurant["address"] += " " + clean_line

        # Detect city: usually single-word capitalized that's not an address
        elif current_restaurant and clean_line and clean_line[0].isupper() and len(clean_line.split()) <= 2:
            if not any(x in clean_line for x in [', Street', 'Road', 'Rd', 'Ave', 'Lane', 'Blvd']):
                if not current_restaurant["city"] or current_restaurant["city"] == "Unknown":
                    current_restaurant["city"] = clean_line

        # Detect cuisine: single line with limited length, no numbers/addresses
        elif current_restaurant and 3 < len(clean_line) < 50:
            if not any(x in clean_line for x in ['/', 'floor', 'Floor', 'Level', 'level', 'Str', 'Street']):
                if not current_restaurant["cuisine"] and clean_line not in [country, city]:
                    current_restaurant["cuisine"] = clean_line

        # Detect maps URL
        elif current_restaurant and ('maps.google.com' in clean_line or 'maps.app' in clean_line):
            url_match = re.search(r'href=["\']([^"\']*maps[^"\']*)["\']', clean_line)
            if url_match:
                current_restaurant["maps_url"] = url_match.group(1)

    if current_restaurant:
        restaurants.append(current_restaurant)

    # Clean up results
    cleaned = []
    for r in restaurants:
        if r["name"] and r["country"]:
            # Generate ID
            name_slug = re.sub(r"[^a-z0-9]+", "-", r["name"].lower()).strip("-")
            city_slug = re.sub(r"[^a-z0-9]+", "-", (r["city"] or "unknown").lower()).strip("-")
            country_slug = re.sub(r"[^a-z0-9]+", "-", r["country"].lower()).strip("-")
            r["id"] = f"amex-global-{country_slug}-{city_slug}-{name_slug}"
            cleaned.append(r)

    return cleaned


def main():
    """Read HTML from stdin and parse."""
    html = sys.stdin.read()

    if not html.strip():
        print("❌ No HTML input. Pipe HTML content via stdin.")
        sys.exit(1)

    print(f"\nParsing HTML ({len(html)} bytes)...")
    restaurants = parse_amex_html(html)

    print(f"\n✅ Extracted {len(restaurants)} restaurants\n")

    # Display results
    for r in restaurants[:10]:
        print(f"  • {r['name']}")
        print(f"    {r['country']} / {r['city']}")
        print(f"    {r['cuisine']}")
        print()

    if len(restaurants) > 10:
        print(f"  ... and {len(restaurants) - 10} more")

    # Output JSON
    print("\nJSON output:")
    print(json.dumps(restaurants[:5], indent=2))


if __name__ == "__main__":
    main()
