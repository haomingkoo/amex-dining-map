#!/usr/bin/env python3
"""
Interactive scraper: Playwright clicks through the page to load restaurants.
"""

import json
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


def extract_restaurants_from_html(html: str) -> list:
    """Parse HTML and extract restaurants."""
    restaurants = []

    # Find all shuffle-card divs
    parts = html.split('class="shuffle-card')

    for part in parts[1:]:
        try:
            # Extract name
            name_match = re.search(
                r'<div[^>]*class="[^"]*sc-dCFHLb[^"]*"[^>]*>.*?</div>\s*([^<]+)',
                part,
                re.DOTALL
            )
            name = name_match.group(1).strip() if name_match else None
            name = re.sub(r'<[^>]+>', '', name).strip() if name else None

            if not name or len(name) < 2:
                continue

            # Extract address
            address_match = re.search(
                r'<div[^>]*class="[^"]*sc-fhzFiK[^"]*"[^>]*>(.*?)</div>',
                part,
                re.DOTALL
            )
            address = address_match.group(1) if address_match else "Unknown"
            address = re.sub(r'<br\s*/?>', ' ', address)
            address = re.sub(r'<[^>]+>', '', address)
            address = ' '.join(address.split())

            # Extract cuisine
            cuisine_match = re.search(
                r'<div[^>]*class="[^"]*sc-jxOSlx[^"]*"[^>]*>.*?</svg>\s*([^<]+)',
                part,
                re.DOTALL
            )
            cuisine = cuisine_match.group(1).strip() if cuisine_match else None

            # Extract maps URL and coordinates
            maps_match = re.search(
                r'<a[^>]*href="(https://www\.google\.com/maps/[^"]*)"',
                part
            )
            maps_url = maps_match.group(1) if maps_match else None

            lat, lng = None, None
            if maps_url:
                coords_match = re.search(r'@([-\d.]+),([-\d.]+)', maps_url)
                if coords_match:
                    try:
                        lat = float(coords_match.group(1))
                        lng = float(coords_match.group(2))
                    except ValueError:
                        pass

            # Extract city
            city = "Unknown"
            if address and address != "Unknown":
                addr_parts = address.split(' ')
                if len(addr_parts) > 1:
                    city = addr_parts[-1]

            restaurant = {
                "name": name,
                "address": address,
                "cuisine": cuisine,
                "city": city,
                "lat": lat,
                "lng": lng,
            }

            restaurants.append(restaurant)

        except:
            continue

    return restaurants


def scrape_with_interaction():
    """Scrape by interacting with the page."""
    print("\n" + "="*80)
    print("INTERACTIVE SCRAPER: Click through countries and load restaurants")
    print("="*80 + "\n")

    all_restaurants = []
    countries_tried = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Show browser for debugging
        page = browser.new_page()

        try:
            # Load page
            print("📄 Loading AMEX dining page...")
            page.goto(
                "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                wait_until="load",
                timeout=60000
            )
            print("✅ Page loaded\n")

            # Wait for JavaScript to render
            print("⏳ Waiting for JavaScript to render...")
            time.sleep(5)

            # Try to find and interact with country selector
            print("🔍 Looking for country selector...\n")

            selectors_to_try = [
                "select",
                "[data-testid='country-select']",
                "[data-testid='country']",
                "select[name='country']",
                "button[data-country]",
                "[aria-label*='country' i]",
                ".country-selector",
            ]

            country_selector = None
            for selector in selectors_to_try:
                try:
                    elem = page.query_selector(selector)
                    if elem:
                        print(f"✅ Found selector: {selector}\n")
                        country_selector = selector
                        break
                except:
                    pass

            if not country_selector:
                print("⚠️ No country selector found, extracting current page...\n")

                # Just extract what's on current page
                html = page.content()
                restaurants = extract_restaurants_from_html(html)

                if restaurants:
                    print(f"✅ Extracted {len(restaurants)} restaurants from current page\n")
                    all_restaurants.extend(restaurants)
                else:
                    print("❌ No restaurants found on page\n")
                    print("Debugging info:")
                    print(f"  - HTML length: {len(html)} bytes")
                    print(f"  - Contains 'shuffle-card': {'shuffle-card' in html}")
                    print(f"  - Contains divs: {'<div' in html}")
            else:
                # Try to get country options and iterate
                print("🌍 Attempting to iterate through countries...\n")

                # Try to extract all options
                options = page.query_selector_all(f"{country_selector} > *")
                print(f"Found {len(options)} options\n")

                for idx, option in enumerate(options[:3]):  # Try first 3
                    try:
                        option.click()
                        time.sleep(3)  # Wait for content to load

                        html = page.content()
                        restaurants = extract_restaurants_from_html(html)

                        if restaurants:
                            print(f"✅ Country {idx}: {len(restaurants)} restaurants")
                            all_restaurants.extend(restaurants)
                        else:
                            print(f"⚠️ Country {idx}: No restaurants found")

                    except Exception as e:
                        print(f"❌ Error with country {idx}: {str(e)}")
                        continue

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

        print("\n" + "="*80)
        print("✅ EXTRACTION COMPLETE")
        print("="*80)
        print(f"Total restaurants: {len(all_restaurants)}")
        print(f"Saved to: {output_file}\n")

        if all_restaurants:
            print("📍 Sample restaurants:")
            for r in all_restaurants[:5]:
                print(f"  - {r['name']} ({r['city']})")
                print(f"    {r['address']}")

        return all_restaurants
    else:
        print("\n" + "="*80)
        print("❌ No restaurants extracted")
        print("="*80 + "\n")
        return None


if __name__ == "__main__":
    restaurants = scrape_with_interaction()
    exit(0 if restaurants else 1)
