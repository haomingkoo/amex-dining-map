#!/usr/bin/env python3
"""
Smart scraper: Playwright + Claude Vision in a control loop.
Claude sees the page, decides what to do, I execute it.
"""

import json
import base64
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
import anthropic

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)

client = anthropic.Anthropic()


def screenshot_to_base64(page) -> str:
    """Take screenshot and convert to base64."""
    screenshot = page.screenshot()
    return base64.standard_b64encode(screenshot).decode("utf-8")


def claude_sees(screenshot_b64: str, question: str) -> str:
    """Show Claude a screenshot and ask a question."""
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
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


def scrape():
    """Smart scraping with Playwright + Claude vision."""
    print("\n" + "="*80)
    print("SMART SCRAPER: Playwright + Claude Vision Loop")
    print("="*80 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        restaurants = []

        try:
            # Step 1: Load page
            print("📄 Loading AMEX dining page...")
            page.goto(
                "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                wait_until="load",
                timeout=30000
            )
            time.sleep(3)  # Wait for JS to render

            # Step 2: Take screenshot, let Claude analyze
            print("📸 Taking screenshot...")
            screenshot = screenshot_to_base64(page)

            print("🧠 Claude analyzing page...\n")
            analysis = claude_sees(
                screenshot,
                """Analyze this AMEX dining page. Answer:
1. What restaurants do you see? List at least 5 restaurant names
2. For each, what is: name, address, cuisine type?
3. Are there country filters? Can you see how to switch countries?
4. Approximately how many restaurants are visible?

Format your response as a JSON object with:
- "restaurants": [{"name": "...", "address": "...", "cuisine": "..."}, ...]
- "country_selector": "description of how to switch countries or null"
- "visible_count": number
"""
            )

            print("Claude's analysis:")
            print(analysis)
            print()

            # Try to parse JSON from response
            import re
            json_match = re.search(r'\{.*\}', analysis, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    restaurants.extend(data.get("restaurants", []))
                    print(f"✅ Extracted {len(restaurants)} restaurants from page\n")
                except json.JSONDecodeError:
                    print("⚠️ Could not parse JSON from Claude\n")

            # Step 3: Check if there are more countries to scrape
            if restaurants:
                print("🌍 Checking for other countries...")
                screenshot = screenshot_to_base64(page)

                countries_info = claude_sees(
                    screenshot,
                    """Look for any country selector, dropdown, or filter on this page.
Can you see how to switch to other countries (Hong Kong, Japan, etc)?
What countries are available?
Respond with a JSON object: {"has_country_selector": true/false, "countries": [...], "how_to_select": "description"}"""
                )

                print("Countries available:")
                print(countries_info)
                print()

            # Step 4: Try to get more detailed data
            if restaurants:
                print("📊 Asking Claude to extract complete data...\n")
                screenshot = screenshot_to_base64(page)

                detailed = claude_sees(
                    screenshot,
                    """Extract EVERY restaurant visible on this page.
For each, provide: name, address, cuisine, city/location, any other info visible.
Return ONLY valid JSON array format:
[{"name": "...", "address": "...", "cuisine": "...", "city": "..."}, ...]"""
                )

                # Parse detailed extraction
                json_match = re.search(r'\[.*\]', detailed, re.DOTALL)
                if json_match:
                    try:
                        detailed_restaurants = json.loads(json_match.group(0))
                        restaurants = detailed_restaurants
                        print(f"✅ Detailed extraction: {len(restaurants)} restaurants\n")
                    except json.JSONDecodeError:
                        print("⚠️ Could not parse detailed extraction\n")

        except Exception as e:
            print(f"❌ Error: {str(e)}\n")

        finally:
            browser.close()

        # Save results
        if restaurants:
            # Add country field
            for r in restaurants:
                if "country" not in r:
                    r["country"] = "Unknown"
                if "city" not in r:
                    r["city"] = "Unknown"

            output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
            with open(output_file, "w") as f:
                json.dump(restaurants, f, indent=2)

            print("="*80)
            print(f"✅ EXTRACTION COMPLETE")
            print("="*80)
            print(f"Total restaurants: {len(restaurants)}")
            print(f"Saved to: {output_file}\n")

            # Show samples
            if restaurants:
                print("📍 Sample restaurants:")
                for r in restaurants[:5]:
                    print(f"  - {r.get('name')} ({r.get('city')})")
                    print(f"    {r.get('address')}")
                    print(f"    Cuisine: {r.get('cuisine')}\n")

            return restaurants

        else:
            print("⚠️  No restaurants extracted")
            return None


if __name__ == "__main__":
    restaurants = scrape()
    exit(0 if restaurants else 1)
