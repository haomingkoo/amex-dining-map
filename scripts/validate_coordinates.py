"""
Coordinate validation script using Nominatim geocoding + Haversine distance math.

For each hotel/venue in plat-stays.json and love-dining.json:
  1. Query Nominatim (OSM) by name + country
  2. Calculate Haversine distance between stored coord and Nominatim result
  3. Report anything suspicious

This is deterministic and math-based — no agent guessing.
"""

import json
import math
import time
import sys
import urllib.request
import urllib.parse
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "amex-dining-map-coord-validator/1.0 (github.com/haomingkoo)"
DELAY = 1.1  # Nominatim rate limit: 1 req/s
FLAG_THRESHOLD_M = 300  # flag if Nominatim result is more than 300m from stored


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in meters between two WGS84 points."""
    R = 6_371_000  # earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nominatim_search(query: str, countrycodes: str = "") -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "limit": "3",
        "addressdetails": "1",
    }
    if countrycodes:
        params["countrycodes"] = countrycodes
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return []


def country_to_code(country: str) -> str:
    codes = {
        "Singapore": "sg",
        "Malaysia": "my",
        "Thailand": "th",
        "Japan": "jp",
        "Indonesia": "id",
        "Philippines": "ph",
        "Australia": "au",
        "United Kingdom": "gb",
        "France": "fr",
        "Germany": "de",
        "United States": "us",
        "China": "cn",
        "Hong Kong": "hk",
        "Taiwan": "tw",
        "South Korea": "kr",
        "India": "in",
        "Maldives": "mv",
        "Vietnam": "vn",
        "Cambodia": "kh",
        "Myanmar": "mm",
        "Brunei": "bn",
        "Macau": "mo",
    }
    return codes.get(country, "")


def validate_dataset(records: list[dict], dataset_label: str, threshold_m: int = FLAG_THRESHOLD_M):
    print(f"\n{'='*60}")
    print(f"  {dataset_label}  ({len(records)} records)")
    print(f"{'='*60}")

    flagged = []
    no_result = []
    ok = []

    for i, rec in enumerate(records):
        name = rec.get("name", "")
        country = rec.get("country", "")
        city = rec.get("city", "")
        stored_lat = rec.get("lat")
        stored_lng = rec.get("lng")

        if stored_lat is None or stored_lng is None:
            no_result.append((name, "no stored coordinate"))
            continue

        # Build query: hotel name + city + country
        query = f"{name}, {city}, {country}".strip(", ")
        cc = country_to_code(country)

        results = nominatim_search(query, cc)
        time.sleep(DELAY)

        if not results:
            # Try just name + country
            results = nominatim_search(f"{name}, {country}", cc)
            time.sleep(DELAY)

        if not results:
            no_result.append((name, country))
            print(f"  [{i+1}/{len(records)}] NO RESULT  {name[:60]}")
            continue

        best = results[0]
        nom_lat = float(best["lat"])
        nom_lng = float(best["lon"])
        dist = haversine_m(stored_lat, stored_lng, nom_lat, nom_lng)
        nom_display = best.get("display_name", "")[:80]

        status = "FLAG" if dist > threshold_m else "ok  "
        print(f"  [{i+1}/{len(records)}] {status}  {dist:6.0f}m  {name[:50]}")

        if dist > threshold_m:
            flagged.append({
                "name": name,
                "country": country,
                "city": city,
                "stored": (stored_lat, stored_lng),
                "nominatim": (nom_lat, nom_lng),
                "distance_m": round(dist),
                "nominatim_match": nom_display,
            })
        else:
            ok.append(name)

    print(f"\nSummary: {len(ok)} ok, {len(flagged)} flagged (>{threshold_m}m), {len(no_result)} no Nominatim result")

    if flagged:
        print(f"\nFlagged records:")
        for f in sorted(flagged, key=lambda x: -x["distance_m"]):
            print(f"  {f['distance_m']:5}m  {f['name']}")
            print(f"         stored:    {f['stored'][0]:.6f}, {f['stored'][1]:.6f}")
            print(f"         nominatim: {f['nominatim'][0]:.6f}, {f['nominatim'][1]:.6f}")
            print(f"         match:     {f['nominatim_match']}")

    if no_result:
        print(f"\nNo Nominatim result (manual check needed):")
        for name, note in no_result:
            print(f"  {name}  [{note}]")

    return flagged


def main():
    datasets = []

    plat = DATA_DIR / "plat-stays.json"
    if plat.exists():
        with open(plat) as f:
            datasets.append((json.load(f), "PLAT STAY"))

    love = DATA_DIR / "love-dining.json"
    if love.exists():
        with open(love) as f:
            datasets.append((json.load(f), "LOVE DINING"))

    all_flagged = []
    for records, label in datasets:
        flagged = validate_dataset(records, label)
        all_flagged.extend(flagged)

    print(f"\n{'='*60}")
    print(f"TOTAL FLAGGED: {len(all_flagged)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
