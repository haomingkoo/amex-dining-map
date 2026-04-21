#!/usr/bin/env python3
"""
Audit Global Dining: identify which restaurants are actually in the active program
by scraping the public country listing pages.

Strategy:
1. Scrape each country's public listing page
2. Extract restaurant names/locations actively listed
3. Compare against our data
4. Identify which are missing from public listings (likely inactive)
"""

import json
import asyncio
import re
from pathlib import Path
from collections import defaultdict
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

async def scrape_country_listings():
    """Scrape the active restaurant listings for each country."""
    active_restaurants = defaultdict(list)

    countries = [
        "australia", "austria", "canada", "france", "germany",
        "hong-kong", "italy", "mexico", "monaco", "new-zealand",
        "singapore", "spain", "taiwan", "thailand", "united-kingdom", "united-states"
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for country_slug in countries:
            print(f"\nScraping {country_slug}...")
            page = await browser.new_page()

            try:
                url = f"https://platinumdining.caffeinesoftware.com/{country_slug}/"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                # Extract restaurant names from the page
                restaurants = await page.evaluate("""
                    () => {
                        const results = [];
                        const seen = new Set();

                        // Look for restaurant links and headings
                        document.querySelectorAll('a[href*="/"], h2, h3, .restaurant-name, [class*="name"]').forEach(el => {
                            const text = el.textContent?.trim();
                            if (text && text.length > 2 && text.length < 200 && !seen.has(text)) {
                                // Skip navigation links, generic text
                                if (!text.match(/^(Home|Back|Search|Filter|Map|Book|Reserve|View|More|Loading)/i)) {
                                    results.push(text);
                                    seen.add(text);
                                }
                            }
                        });

                        // Also check body text for restaurant listings
                        const bodyText = document.body.innerText;
                        return {
                            extracted: results.slice(0, 100),  // Limit to avoid noise
                            pageTitle: document.title,
                            hasContent: bodyText.length > 500
                        };
                    }
                """)

                if restaurants["extracted"]:
                    active_restaurants[country_slug] = restaurants["extracted"]
                    print(f"  Found {len(restaurants['extracted'])} restaurant entries")
                else:
                    print(f"  Warning: No restaurants extracted")

            except Exception as e:
                print(f"  Error: {e}")

            await page.close()

        await browser.close()

    return active_restaurants


def load_local_data():
    """Load our local Global Dining data."""
    data_file = DATA_DIR / "global-restaurants.json"
    if not data_file.exists():
        return []
    return json.loads(data_file.read_text())


def normalize_name(name):
    """Normalize restaurant name for comparison."""
    return re.sub(r'[^\w\s]', '', name.lower()).strip()


def audit_restaurants(local_data, active_listings):
    """
    Compare local data against active public listings.
    Identify restaurants that are in our data but not in public listings.
    """
    # Build normalized lookup of active restaurants
    active_by_country = {}
    for country_slug, names in active_listings.items():
        normalized = {normalize_name(n) for n in names if n}
        active_by_country[country_slug] = normalized

    # Map slug to proper country name
    slug_to_country = {
        "australia": "Australia",
        "austria": "Austria",
        "canada": "Canada",
        "france": "France",
        "germany": "Germany",
        "hong-kong": "Hong Kong",
        "italy": "Italy",
        "mexico": "Mexico",
        "monaco": "Monaco",
        "new-zealand": "New Zealand",
        "singapore": "Singapore",
        "spain": "Spain",
        "taiwan": "Taiwan",
        "thailand": "Thailand",
        "united-kingdom": "United Kingdom",
        "united-states": "United States",
    }

    # Group local data by country
    local_by_country = defaultdict(list)
    for r in local_data:
        country = r.get("country")
        if country:
            local_by_country[country].append(r)

    # Find inactive (not in active listings)
    inactive = defaultdict(list)
    active_in_both = defaultdict(int)

    for country, restaurants in local_by_country.items():
        # Find the slug for this country
        slug = None
        for s, c in slug_to_country.items():
            if c == country:
                slug = s
                break

        if not slug or slug not in active_by_country:
            print(f"Warning: No public listing data for {country}")
            continue

        active_set = active_by_country[slug]

        for r in restaurants:
            name = r.get("name", "")
            normalized = normalize_name(name)

            # Check if this restaurant appears in public listings
            found = False
            for active_name in active_set:
                if normalize_name(active_name) == normalized:
                    found = True
                    break

            if found:
                active_in_both[country] += 1
            else:
                inactive[country].append({
                    "name": name,
                    "city": r.get("city"),
                    "id": r.get("id")
                })

    return inactive, active_in_both


def generate_audit_report(inactive, active_in_both, total_local):
    """Generate audit report."""
    report = []
    report.append("=" * 80)
    report.append("GLOBAL DINING AUDIT REPORT")
    report.append("Comparing local data against public country listing pages")
    report.append("=" * 80)
    report.append("")

    total_inactive = sum(len(v) for v in inactive.values())
    total_active = sum(active_in_both.values())

    report.append(f"Total in local data: {total_local}")
    report.append(f"Verified in public listings: {total_active}")
    report.append(f"Not found in public listings: {total_inactive}")
    report.append(f"Unverified/unknown: {total_local - total_active - total_inactive}")
    report.append("")

    if inactive:
        report.append("RESTAURANTS NOT IN PUBLIC LISTINGS (candidates for removal):")
        report.append("-" * 80)

        for country in sorted(inactive.keys()):
            restaurants = inactive[country]
            report.append(f"\n{country} ({len(restaurants)} inactive):")
            for r in restaurants[:10]:
                report.append(f"  - {r['name']} ({r['city']})")
            if len(restaurants) > 10:
                report.append(f"  ... and {len(restaurants) - 10} more")

        report.append("")
        report.append(f"Total candidate removals: {total_inactive}")

    return "\n".join(report)


async def main():
    print("Starting Global Dining audit...\n")

    print("Loading local data...")
    local_data = load_local_data()
    print(f"Loaded {len(local_data)} restaurants\n")

    print("Scraping public country listing pages...")
    active_listings = await scrape_country_listings()
    print(f"\nScraped {len(active_listings)} countries\n")

    print("Auditing against public listings...")
    inactive, active_verified = audit_restaurants(local_data, active_listings)

    # Generate report
    report = generate_audit_report(inactive, active_verified, len(local_data))
    print(report)

    # Save report
    report_path = DATA_DIR / "audit-inactive-restaurants.txt"
    report_path.write_text(report)
    print(f"\nReport saved to {report_path}")

    # Save detailed inactive list for review
    inactive_details = {country: [r for r in restaurants]
                       for country, restaurants in inactive.items()}
    inactive_json = DATA_DIR / "audit-inactive-restaurants.json"
    inactive_json.write_text(json.dumps(inactive_details, indent=2, ensure_ascii=False) + "\n")
    print(f"Inactive list saved to {inactive_json}")


if __name__ == "__main__":
    asyncio.run(main())
