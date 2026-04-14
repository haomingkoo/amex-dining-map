#!/usr/bin/env python3
"""
Inspect AMEX page to find the actual API endpoint for restaurant data.

Instead of scraping HTML, we spy on network requests to find what API
the page uses to fetch restaurants, then call that API directly.

Usage:
  python3 scripts/inspect_amex_api.py
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

DATA_DIR = Path(__file__).parent.parent / "data"


def inspect_api():
    """Load AMEX page and intercept network requests."""
    print("\n" + "="*80)
    print("INSPECTING AMEX API")
    print("="*80)
    print("Loading page and monitoring network requests...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Track network requests
        network_log = []

        def handle_response(response):
            """Log response from network request."""
            request = response.request
            url = request.url
            method = request.method

            # Only log successful responses with interesting content
            if response.status == 200 and ("api" in url.lower() or "dining" in url.lower() or "restaurant" in url.lower()):
                try:
                    # Try to get response body (works for JSON/text)
                    body = response.text()
                    content_type = response.headers.get("content-type", "")

                    entry = {
                        "url": url,
                        "method": method,
                        "status": response.status,
                        "content_type": content_type,
                        "size": len(body),
                        "preview": body[:500] if len(body) < 1000 else body[:500] + "...",
                    }

                    network_log.append(entry)
                    print(f"✅ {method} {url}")
                    print(f"   Status: {response.status} | Type: {content_type} | Size: {len(body)} bytes")

                    # If it looks like restaurant data, show preview
                    if "restaurant" in body.lower() or "dining" in body.lower():
                        print(f"   Preview: {entry['preview'][:100]}...")
                    print()

                except Exception as e:
                    print(f"⚠️  Could not read response: {str(e)}\n")

        page.on("response", handle_response)

        try:
            print("🌐 Opening: https://www.americanexpress.com/en-sg/benefits/platinum/dining/\n")
            page.goto(
                "https://www.americanexpress.com/en-sg/benefits/platinum/dining/",
                wait_until="networkidle",
                timeout=30000
            )
            print("✅ Page loaded\n")

            # Wait a bit more for lazy-loaded requests
            import time
            time.sleep(2)

            # Try to trigger country selection
            print("🔍 Looking for country selector...")
            selectors_to_try = [
                "select[name='country']",
                "#country-select",
                "[data-testid='country-select']",
                "button[data-country]",
                ".country-selector",
            ]

            for selector in selectors_to_try:
                elem = page.query_selector(selector)
                if elem:
                    print(f"✅ Found selector: {selector}\n")
                    break
            else:
                print("⚠️  Could not find country selector\n")

            # Check what's on the page
            print("📊 Page content check:")
            shuffle_cards = page.query_selector_all("div.shuffle-card")
            print(f"  - Shuffle cards found: {len(shuffle_cards)}")

            all_divs = page.query_selector_all("div")
            print(f"  - Total divs on page: {len(all_divs)}")

            # Look for any JSON-LD or inline data
            scripts = page.query_selector_all("script")
            print(f"  - Script tags: {len(scripts)}")

            for idx, script in enumerate(scripts[:5]):
                content = script.text_content()
                if "restaurant" in content.lower() or "dining" in content.lower():
                    print(f"    Script {idx} contains restaurant/dining data")
                    if len(content) < 500:
                        print(f"      Content: {content[:200]}...")

        except Exception as e:
            print(f"❌ Error: {str(e)}")
        finally:
            browser.close()

        # Summary
        print("\n" + "="*80)
        print("NETWORK LOG SUMMARY")
        print("="*80)
        if network_log:
            print(f"\n✅ Captured {len(network_log)} API requests:\n")
            for entry in network_log:
                print(f"🔗 {entry['method']} {entry['url']}")
                print(f"   Status: {entry['status']} | Type: {entry['content_type']} | Size: {entry['size']} bytes\n")

            # Save full log
            log_file = DATA_DIR / "network-inspection-log.json"
            with open(log_file, "w") as f:
                json.dump(network_log, f, indent=2)
            print(f"\n💾 Full log saved to: {log_file}")
        else:
            print("\n⚠️  No API requests captured")
            print("   The page might:")
            print("   - Use different selectors than expected")
            print("   - Load data inline (JSON-LD in <script> tags)")
            print("   - Require user interaction (country selection) to load data")
            print("   - Use a different domain for API calls")


if __name__ == "__main__":
    inspect_api()
