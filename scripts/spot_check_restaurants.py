#!/usr/bin/env python3
"""
Spot-check a random sample of restaurants to verify they actually exist
and are still in business.

Uses Google Maps API (via search) to verify restaurant existence.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"


def load_global_dining():
    """Load Global Dining data."""
    data_file = DATA_DIR / "global-restaurants.json"
    if not data_file.exists():
        return []
    return json.loads(data_file.read_text())


def generate_spot_check_sample(all_records, sample_size=50):
    """Generate a representative sample for spot-checking."""
    # Group by country
    by_country = {}
    for r in all_records:
        country = r.get("country", "Unknown")
        if country not in by_country:
            by_country[country] = []
        by_country[country].append(r)

    # Select restaurants from each country proportionally
    sample = []
    for country, restaurants in sorted(by_country.items()):
        # Proportional sample from each country
        country_sample_size = max(2, int(sample_size * len(restaurants) / len(all_records)))
        selected = random.sample(restaurants, min(country_sample_size, len(restaurants)))
        sample.extend(selected)

    return sample[:sample_size]


def create_spot_check_list():
    """Create a spot-check validation list."""
    print("=" * 80)
    print("SPOT-CHECK VALIDATION - Global Dining Sample")
    print("=" * 80)
    print()

    data = load_global_dining()
    print(f"Total restaurants in dataset: {len(data)}")
    print()

    sample = generate_spot_check_sample(data, sample_size=50)

    print(f"Generated {len(sample)} spot-check items (representative sample)\n")
    print("Instructions:")
    print("1. For each restaurant below, verify:")
    print("   - Does the restaurant still exist? (Google Maps search)")
    print("   - Is it still actively operating?")
    print("   - Can you make a reservation there?")
    print("2. Mark as VALID or INVALID")
    print("3. Note any discrepancies in name/location")
    print()

    # Group by country for organized checking
    by_country = {}
    for r in sample:
        country = r.get("country", "Unknown")
        if country not in by_country:
            by_country[country] = []
        by_country[country].append(r)

    spot_check_items = []

    for country in sorted(by_country.keys()):
        print(f"\n{'=' * 80}")
        print(f"{country} ({len(by_country[country])} restaurants)")
        print(f"{'=' * 80}\n")

        for i, r in enumerate(by_country[country], 1):
            name = r.get("name", "Unknown")
            city = r.get("city", "Unknown")
            cuisine = r.get("cuisines", ["Unknown"])
            cuisine_str = ", ".join(cuisine) if isinstance(cuisine, list) else cuisine
            url = r.get("source_google_map_url", "N/A")

            item = {
                "id": r.get("id"),
                "country": country,
                "name": name,
                "city": city,
                "cuisine": cuisine_str,
                "google_maps_url": url,
                "status": "PENDING",
                "notes": ""
            }
            spot_check_items.append(item)

            print(f"{i}. {name} ({city})")
            print(f"   Cuisine: {cuisine_str}")
            if url and url.startswith("http"):
                print(f"   Map: {url[:60]}...")
            print()

    # Save spot-check list
    output_file = DATA_DIR / "spot-check-list.json"
    with open(output_file, "w") as f:
        json.dump(spot_check_items, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 80}")
    print(f"Spot-check list saved to: {output_file}")
    print(f"Total items: {len(spot_check_items)}")
    print()
    print("Next steps:")
    print("1. Review each restaurant on Google Maps")
    print("2. Update 'status' field: VALID or INVALID")
    print("3. Add notes on 'status' or data discrepancies")
    print("4. Run analysis to generate validation report")
    print()


if __name__ == "__main__":
    random.seed(42)  # For reproducible sample
    create_spot_check_list()
