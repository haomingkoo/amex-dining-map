#!/usr/bin/env python3
"""
Scrape AMEX with Playwright + Claude Vision.

Take screenshots of the page, use Claude vision to see and understand it,
then tell Playwright what to do next.

Usage:
  python3 scripts/scrape_with_vision.py
"""

import asyncio
import json
import sys
import base64
from pathlib import Path
from datetime import datetime

import anthropic
from playwright.sync_api import sync_playwright

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


def take_screenshot(page) -> str:
    """Take screenshot and return as base64."""
    screenshot = page.screenshot()
    return base64.standard_b64encode(screenshot).decode("utf-8")


def analyze_with_vision(client: anthropic.Anthropic, screenshot_b64: str, question: str) -> str:
    """Send screenshot to Claude for analysis."""
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": question
                    }
                ],
            }
        ],
    )
    return message.content[0].text


def scrape_with_vision():
    """Scrape AMEX using vision-guided Playwright."""
    print("\n" + "="*80)
    print("PHASE 2: Extract with Playwright + Claude Vision")
    print("="*80)
    print("Using Claude to see and guide the browser...\n")

    client = anthropic.Anthropic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Show browser for debugging
        page = browser.new_page()

        try:
            # Step 1: Load AMEX page
            print("📄 Loading AMEX dining page...")
            page.goto(
                "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                wait_until="load",
                timeout=30000
            )
            page.wait_for_load_state("networkidle")
            print("✅ Page loaded\n")

            # Step 2: Take screenshot and analyze
            print("📸 Analyzing page with vision...")
            screenshot = take_screenshot(page)

            analysis = analyze_with_vision(
                client,
                screenshot,
                """Analyze this AMEX dining page. Tell me:
1. What do you see on the page?
2. Are there restaurant listings visible? How many?
3. Is there a country selector or filter? Where is it?
4. What are the CSS selectors or button labels for navigation?
5. List 3-5 restaurant names you can see."""
            )

            print("Vision Analysis:")
            print(analysis)
            print()

            # Step 3: Get instructions from Claude on how to extract data
            print("💡 Asking Claude how to extract restaurants...")
            instructions = analyze_with_vision(
                client,
                screenshot,
                """Based on what you see on this page, provide exact step-by-step instructions
for a Playwright script to:
1. Navigate through all countries
2. Extract restaurant name, address, cuisine, location
3. Return the data as JSON

Be specific about selectors, button labels, and interactions needed."""
            )

            print("Extraction Instructions:")
            print(instructions)
            print()

            # Step 4: Ask Claude to extract visible restaurants
            print("🍽️  Extracting visible restaurants...")
            extraction = analyze_with_vision(
                client,
                screenshot,
                """Look at all the restaurant cards/items visible on this page.
For EACH restaurant, extract:
- Name
- Address/Location
- Cuisine (if shown)
- City

Return ONLY a valid JSON array with these fields: name, address, cuisine, city, country.
Example: [{"name": "Restaurant A", "address": "123 Main St", "cuisine": "Italian", "city": "Hong Kong", "country": "Hong Kong"}]"""
            )

            print("Raw Extraction:")
            print(extraction)
            print()

            # Try to parse JSON from response
            import re
            json_match = re.search(r'\[.*\]', extraction, re.DOTALL)
            if json_match:
                try:
                    restaurants = json.loads(json_match.group(0))
                    print(f"✅ Extracted {len(restaurants)} restaurants\n")

                    # Save results
                    output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
                    with open(output_file, "w") as f:
                        json.dump(restaurants, f, indent=2)
                    print(f"💾 Saved to: {output_file}\n")

                    # Print samples
                    if restaurants:
                        print("📍 Sample restaurants:")
                        for r in restaurants[:3]:
                            print(f"  - {r.get('name')} ({r.get('city')})")
                            print(f"    {r.get('address')}")
                        print()

                    return restaurants

                except json.JSONDecodeError as e:
                    print(f"⚠️  Could not parse JSON: {e}")
                    return None

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            browser.close()


def main():
    """Run extraction."""
    restaurants = scrape_with_vision()

    if restaurants:
        print("\n" + "="*80)
        print("✅ Extraction successful!")
        print("="*80)
        print(f"Total restaurants: {len(restaurants)}")
        return True
    else:
        print("\n" + "="*80)
        print("⚠️ Extraction completed but no data extracted")
        print("="*80)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
