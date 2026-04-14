"""
Coordinate validation using Google Maps URLs + Haversine math.

For each record with a Google Maps URL in the ratings data:
  1. Extract lat/lng from the maps_url
  2. Calculate Haversine distance to stored coordinate
  3. Flag anything > 200m off
  4. Output corrected coordinates for manual review

This is more reliable than Nominatim for hotel precision.
"""

import json
import math
import re
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
FLAG_THRESHOLD_M = 200


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in meters between two WGS84 points."""
    R = 6_371_000  # earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def extract_coords_from_gmaps_url(url: str) -> Optional[tuple[float, float]]:
    """Extract lat,lng from Google Maps URL. Format: /@lat,lng,zoom"""
    match = re.search(r'/@([-\d.]+),([-\d.]+),', url)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def validate_from_gmaps(dataset_file: Path, dataset_label: str) -> list[dict]:
    if not dataset_file.exists():
        return []

    with open(dataset_file) as f:
        records = json.load(f)

    ratings_file = DATA_DIR / "google-maps-ratings.json"
    ratings = {}
    if ratings_file.exists():
        with open(ratings_file) as f:
            ratings = json.load(f)

    print(f"\n{'='*70}")
    print(f"  {dataset_label}  ({len(records)} records)")
    print(f"{'='*70}")

    flagged = []
    checked = 0
    no_gmaps_url = 0

    for rec in records:
        rec_id = rec.get("id", "")
        name = rec.get("name", "")
        stored_lat = rec.get("lat")
        stored_lng = rec.get("lng")

        if stored_lat is None or stored_lng is None:
            continue

        # Look up Google Maps URL in ratings
        rating_rec = ratings.get(rec_id, {})
        maps_url = rating_rec.get("maps_url", "")

        if not maps_url:
            no_gmaps_url += 1
            continue

        coords = extract_coords_from_gmaps_url(maps_url)
        if not coords:
            no_gmaps_url += 1
            continue

        gmaps_lat, gmaps_lng = coords
        dist = haversine_m(stored_lat, stored_lng, gmaps_lat, gmaps_lng)
        checked += 1

        status = "🚩 FLAG" if dist > FLAG_THRESHOLD_M else "✓ ok"
        print(f"  {status}  {dist:7.1f}m  {name[:60]}")

        if dist > FLAG_THRESHOLD_M:
            flagged.append({
                "id": rec_id,
                "name": name,
                "stored": (stored_lat, stored_lng),
                "gmaps": (gmaps_lat, gmaps_lng),
                "distance_m": round(dist),
                "correction": {
                    "lat": gmaps_lat,
                    "lng": gmaps_lng,
                }
            })

    print(f"\nChecked: {checked}, Flagged: {len(flagged)}, No Google Maps URL: {no_gmaps_url}")

    if flagged:
        print(f"\n{'='*70}")
        print(f"  FLAGGED ({len(flagged)} records need coordinate correction)")
        print(f"{'='*70}")
        for f in sorted(flagged, key=lambda x: -x["distance_m"]):
            print(f"\n  {f['name']}")
            print(f"    Distance:  {f['distance_m']}m")
            print(f"    Current:   {f['stored'][0]:.7f}, {f['stored'][1]:.7f}")
            print(f"    Google:    {f['gmaps'][0]:.7f}, {f['gmaps'][1]:.7f}")

    return flagged


def main():
    all_flagged = []

    plat = DATA_DIR / "plat-stays.json"
    flagged = validate_from_gmaps(plat, "PLAT STAY")
    all_flagged.extend(flagged)

    love = DATA_DIR / "love-dining.json"
    flagged = validate_from_gmaps(love, "LOVE DINING")
    all_flagged.extend(flagged)

    print(f"\n{'='*70}")
    print(f"TOTAL FLAGGED: {len(all_flagged)}")
    print(f"{'='*70}")

    # Output corrected JSON for manual review
    if all_flagged:
        corrections = {f["id"]: f["correction"] for f in all_flagged}
        print(f"\nCorrections to apply (copy to python script or review):")
        for rec_id, corr in corrections.items():
            print(f'  "{rec_id}": {corr},')


if __name__ == "__main__":
    main()
