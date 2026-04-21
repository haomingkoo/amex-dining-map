#!/usr/bin/env python3
"""
Verify our dining data against official Amex Platinum Dining source.
Scrapes platinumdining.caffeinesoftware.com and compares with local data.
"""

import json
import asyncio
from pathlib import Path
from urllib.parse import urljoin
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

async def scrape_official_restaurants():
    """Scrape all restaurants from official Platinum Dining source."""
    restaurants = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Get list of countries
        await page.goto("https://platinumdining.caffeinesoftware.com/", wait_until="networkidle")
        countries = await page.evaluate("""
            () => {
                const links = [];
                document.querySelectorAll('a[href*="/"]').forEach(a => {
                    const href = a.getAttribute('href');
                    if (href && href.match(/^\\/[a-z-]+\\/$/) && href !== '/') {
                        const country = href.replace(/\\//g, '');
                        if (country && !links.includes(country)) links.push(country);
                    }
                });
                return links;
            }
        """)

        print(f"Found {len(countries)} countries: {countries[:5]}...")

        # Scrape each country
        for country in countries:
            print(f"\nScraping {country}...")
            try:
                url = f"https://platinumdining.caffeinesoftware.com/{country}/"
                await page.goto(url, wait_until="networkidle", timeout=30000)

                country_restaurants = await page.evaluate("""
                    () => {
                        const results = [];
                        document.querySelectorAll('a[href*="/"]').forEach(a => {
                            const href = a.getAttribute('href');
                            const text = a.textContent.trim();
                            // Match restaurant links: /country/region/restaurant-name
                            if (href && href.match(/^\\/[a-z-]+\\/[a-z-]+\\/[a-z-]/)) {
                                results.push({
                                    name: text,
                                    url: href
                                });
                            }
                        });
                        // Remove duplicates
                        const seen = new Set();
                        return results.filter(r => {
                            const key = r.name + r.url;
                            if (seen.has(key)) return false;
                            seen.add(key);
                            return true;
                        });
                    }
                """)

                for resto in country_restaurants:
                    key = f"{country}:{resto['name']}"
                    restaurants[key] = {
                        "country": country,
                        "name": resto["name"],
                        "url": resto["url"]
                    }

                print(f"  Found {len(country_restaurants)} restaurants")

            except Exception as e:
                print(f"  Error scraping {country}: {e}")

        await browser.close()

    return restaurants


def load_local_data():
    """Load our local restaurant data."""
    data_file = DATA_DIR / "global-restaurants.json"
    if not data_file.exists():
        return []
    return json.loads(data_file.read_text())


def compare_data(official, local):
    """Compare official data with local data."""
    # Build lookup maps
    official_by_key = {f"{r['country']}:{r['name']}": r for r in official}

    local_names = {}
    for r in local:
        key = f"{r.get('country')}:{r.get('name')}"
        if key not in local_names:
            local_names[key] = r

    # Find missing in our data (in official but not local)
    missing = {}
    for key, official_r in official_by_key.items():
        if key not in local_names:
            country, name = key.split(":", 1)
            if country not in missing:
                missing[country] = []
            missing[country].append(name)

    # Find extra in our data (in local but not official)
    extra = {}
    for key, local_r in local_names.items():
        if key not in official_by_key:
            country, name = key.split(":", 1)
            if country not in extra:
                extra[country] = []
            extra[country].append(name)

    return missing, extra


def generate_report(missing, extra, official_count, local_count):
    """Generate verification report."""
    report = []
    report.append("=" * 70)
    report.append("PLATINUM DINING DATA VERIFICATION REPORT")
    report.append("=" * 70)
    report.append("")

    report.append(f"Official Source Count: {official_count} restaurants")
    report.append(f"Local Data Count: {local_count} restaurants")
    report.append(f"Difference: {local_count - official_count:+d}")
    report.append("")

    if missing:
        report.append("MISSING FROM OUR DATA (in official, not in ours):")
        report.append("-" * 70)
        for country in sorted(missing.keys()):
            restaurants = missing[country]
            report.append(f"  {country}: {len(restaurants)} missing")
            for name in restaurants[:3]:
                report.append(f"    - {name}")
            if len(restaurants) > 3:
                report.append(f"    ... and {len(restaurants) - 3} more")
        report.append("")

    if extra:
        report.append("EXTRA IN OUR DATA (in ours, not in official):")
        report.append("-" * 70)
        for country in sorted(extra.keys()):
            restaurants = extra[country]
            report.append(f"  {country}: {len(restaurants)} extra")
            for name in restaurants[:3]:
                report.append(f"    - {name}")
            if len(restaurants) > 3:
                report.append(f"    ... and {len(restaurants) - 3} more")
        report.append("")

    if not missing and not extra:
        report.append("✓ All data matches official source!")
        report.append("")

    return "\n".join(report)


async def main():
    print("Starting verification...\n")

    # Load local data
    print("Loading local data...")
    local_data = load_local_data()
    print(f"  Loaded {len(local_data)} restaurants from local data\n")

    # Scrape official data
    print("Scraping official source (platinumdining.caffeinesoftware.com)...")
    official_data = await scrape_official_restaurants()
    print(f"\n  Scraped {len(official_data)} restaurants from official source\n")

    # Convert to list format for comparison
    official_list = list(official_data.values())

    # Compare
    print("Comparing data...")
    missing, extra = compare_data(official_list, local_data)

    # Generate and print report
    report = generate_report(missing, extra, len(official_list), len(local_data))
    print(report)

    # Save report
    report_path = DATA_DIR / "verification-report.txt"
    report_path.write_text(report)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
