#!/usr/bin/env python3
"""
Extract AMEX restaurants using Playwright + BeautifulSoup.
No API keys. No external services. Just pure scraping.
"""

import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from html.parser import HTMLParser
import re

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


def extract_restaurants_from_html(html: str) -> list:
    """Parse HTML and extract restaurants using regex."""
    restaurants = []

    # Find all shuffle-card divs (restaurant cards)
    # Split by shuffle-card to find individual cards
    parts = html.split('class="shuffle-card')

    for part in parts[1:]:  # Skip first part before any shuffle-card
        try:
            # Extract name from sc-dCFHLb div
            name_match = re.search(
                r'<div[^>]*class="[^"]*sc-dCFHLb[^"]*"[^>]*>.*?</div>\s*([^<]+)',
                part,
                re.DOTALL
            )
            name = name_match.group(1).strip() if name_match else None
            name = re.sub(r'<[^>]+>', '', name).strip() if name else None

            if not name or len(name) < 2:
                continue

            # Extract address from sc-fhzFiK div
            address_match = re.search(
                r'<div[^>]*class="[^"]*sc-fhzFiK[^"]*"[^>]*>(.*?)</div>',
                part,
                re.DOTALL
            )
            if address_match:
                address = address_match.group(1)
                address = re.sub(r'<br\s*/?>', ' ', address)
                address = re.sub(r'<[^>]+>', '', address)
                address = ' '.join(address.split())
            else:
                address = "Unknown"

            # Extract cuisine from sc-jxOSlx div
            cuisine_match = re.search(
                r'<div[^>]*class="[^"]*sc-jxOSlx[^"]*"[^>]*>.*?</svg>\s*([^<]+)',
                part,
                re.DOTALL
            )
            cuisine = cuisine_match.group(1).strip() if cuisine_match else None

            # Extract Google Maps URL
            maps_match = re.search(
                r'<a[^>]*href="(https://www\.google\.com/maps/[^"]*)"',
                part
            )
            maps_url = maps_match.group(1) if maps_match else None

            # Extract coordinates from maps URL
            lat, lng = None, None
            if maps_url:
                coords_match = re.search(r'@([-\d.]+),([-\d.]+)', maps_url)
                if coords_match:
                    try:
                        lat = float(coords_match.group(1))
                        lng = float(coords_match.group(2))
                    except ValueError:
                        pass

            # Extract city (usually last line of address)
            city = "Unknown"
            if address and address != "Unknown":
                addr_parts = address.split(' ')
                if len(addr_parts) > 1:
                    city = addr_parts[-1]

            # Create record
            restaurant = {
                "id": f"amex-{name.lower()[:20]}-{city.lower()[:10]}".replace(" ", "-"),
                "name": name,
                "country": "Unknown",  # Will update when we know country
                "city": city,
                "address": address,
                "cuisine": cuisine,
                "lat": lat,
                "lng": lng,
                "maps_url": maps_url,
            }

            restaurants.append(restaurant)

        except Exception as e:
            continue

    return restaurants


def scrape_amex():
    """Scrape AMEX dining using Playwright + pure parsing."""
    print("\n" + "="*80)
    print("DIRECT SCRAPER: Playwright + BeautifulSoup (No API Keys)")
    print("="*80 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        all_restaurants = []

        try:
            # Load page
            print("📄 Loading AMEX dining page...")
            page.goto(
                "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                wait_until="networkidle",
                timeout=60000
            )
            print("✅ Page loaded\n")

            # Wait for content to render
            time.sleep(3)

            # Get full HTML
            print("📄 Extracting HTML...")
            html = page.content()
            print(f"✅ Got {len(html)} bytes of HTML\n")

            # Parse restaurants
            print("🔍 Parsing restaurants from HTML...")
            restaurants = extract_restaurants_from_html(html)
            print(f"✅ Found {len(restaurants)} restaurants\n")

            if not restaurants:
                print("⚠️ No restaurants found on current page")
                print("   Checking page structure...")

                # Debug: show what divs we have
                div_count = html.count('<div')
                shuffle_count = html.count('shuffle-card')
                print(f"   Total divs: {div_count}")
                print(f"   Shuffle-cards: {shuffle_count}")

            all_restaurants.extend(restaurants)

            # Show samples
            if all_restaurants:
                print("📍 Sample restaurants extracted:")
                for r in all_restaurants[:5]:
                    print(f"  - {r['name']} ({r['city']})")
                    print(f"    {r['address']}")
                    if r['cuisine']:
                        print(f"    {r['cuisine']}")
                print()

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()

        finally:
            browser.close()

        # Save results
        if all_restaurants:
            output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
            with open(output_file, "w") as f:
                json.dump(all_restaurants, f, indent=2)

            print("="*80)
            print("✅ EXTRACTION COMPLETE")
            print("="*80)
            print(f"Total restaurants: {len(all_restaurants)}")
            print(f"Saved to: {output_file}\n")

            return all_restaurants
        else:
            print("="*80)
            print("⚠️  No restaurants extracted")
            print("="*80 + "\n")
            return None


if __name__ == "__main__":
    restaurants = scrape_amex()
    exit(0 if restaurants else 1)
