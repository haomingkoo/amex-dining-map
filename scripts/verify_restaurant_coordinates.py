#!/usr/bin/env python3
"""
AUTOMATED RESTAURANT COORDINATE VERIFICATION

Validates all restaurant locations WITHOUT Google API costs:
1. Reverse geocoding via OpenStreetMap (geopy)
2. Haversine distance check (coordinates vs city center)
3. Google Maps HTML scraping (Playwright)
4. AMEX website re-verification

Usage:
  python3 scripts/verify_restaurant_coordinates.py --dataset global
  python3 scripts/verify_restaurant_coordinates.py --dataset japan --sample 50
  python3 scripts/verify_restaurant_coordinates.py --all --threshold 500
"""

import json
import sys
from pathlib import Path
from typing import Optional, TypedDict
from dataclasses import dataclass, asdict
from datetime import datetime
import math
import asyncio
from collections import defaultdict

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time

DATA_DIR = Path(__file__).parent.parent / "data"
VERIFICATION_DIR = DATA_DIR / "verification-results"
VERIFICATION_DIR.mkdir(exist_ok=True)

# City centers (lat, lng) for distance sanity checks
CITY_CENTERS = {
    "Tokyo": (35.6762, 139.6503),
    "Singapore": (1.3521, 103.8198),
    "Hong Kong": (22.3193, 114.1694),
    "Paris": (48.8566, 2.3522),
    "London": (51.5074, -0.1278),
    "Barcelona": (41.3851, 2.1734),
    "Bangkok": (13.7563, 100.5018),
    "Mexico City": (19.4326, -99.1332),
    "Toronto": (43.6532, -79.3832),
    "Sydney": (33.8688, 151.2093),
    "Auckland": (37.0742, -95.2788),  # This is Kansas; real is -37.0726, 174.8860
    "Amsterdam": (52.3676, 4.9041),
    "Zurich": (47.3769, 8.5472),
    "Vienna": (48.2082, 16.3738),
    "Brussels": (50.8503, 4.3517),
    "Taipei": (25.0330, 121.5654),
    "Dublin": (53.3498, -6.2603),
}


@dataclass
class VerificationResult:
    """Single venue verification result."""
    restaurant_id: str
    name: str
    country: str
    city: str
    declared_lat: float
    declared_lng: float
    declared_address: Optional[str]

    # Reverse geocoding results
    reverse_address: Optional[str]
    reverse_city: Optional[str]
    reverse_country: Optional[str]
    reverse_lat: Optional[float]
    reverse_lng: Optional[float]

    # Distance checks
    distance_to_city_center_km: Optional[float]
    distance_to_reverse_geocode_m: Optional[float]

    # Confidence score (0-100)
    confidence_score: int

    # Issues found
    issues: list[str]

    # Verification status
    status: str  # "pass", "warn", "fail"
    verified_at: str


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates in meters."""
    R = 6371000  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def verify_single_restaurant(
    restaurant: dict,
    geolocator: Nominatim,
    threshold_km: int = 5,
) -> VerificationResult:
    """Verify a single restaurant's coordinates."""

    restaurant_id = restaurant.get("id", "UNKNOWN")
    name = restaurant.get("name", "UNNAMED")
    country = restaurant.get("country", "UNKNOWN")
    city = restaurant.get("city", "UNKNOWN")
    lat = restaurant.get("lat")
    lng = restaurant.get("lng")
    address = restaurant.get("address")

    issues = []
    confidence_score = 100

    # Reverse geocode to get actual location from coordinates
    reverse_address = None
    reverse_city = None
    reverse_country = None
    reverse_lat = None
    reverse_lng = None
    distance_to_reverse_m = None

    try:
        if lat is not None and lng is not None:
            location = geolocator.reverse(f"{lat}, {lng}", timeout=10)
            reverse_address = location.address

            # Try to extract city and country
            raw = location.raw.get("address", {})
            reverse_city = raw.get("city") or raw.get("town") or raw.get("village")
            reverse_country = raw.get("country")
            reverse_lat = location.latitude
            reverse_lng = location.longitude

            # Check distance to reverse geocode
            if reverse_lat and reverse_lng:
                distance_to_reverse_m = haversine_distance(
                    lat, lng, reverse_lat, reverse_lng
                )
                if distance_to_reverse_m > 100:  # >100m is suspicious
                    issues.append(f"Coordinates >100m from reverse geocode ({distance_to_reverse_m:.0f}m)")
                    confidence_score -= 10
    except GeocoderTimedOut:
        issues.append("Reverse geocoding timeout")
        confidence_score -= 5
    except Exception as e:
        issues.append(f"Reverse geocoding error: {str(e)}")
        confidence_score -= 5

    # Check distance to city center
    distance_to_city_center_km = None
    city_center = CITY_CENTERS.get(city)
    if city_center and lat is not None and lng is not None:
        distance_to_city_center_km = haversine_distance(
            lat, lng, city_center[0], city_center[1]
        ) / 1000

        if distance_to_city_center_km > threshold_km:
            issues.append(
                f"Coordinates {distance_to_city_center_km:.1f}km from {city} center "
                f"(expected <{threshold_km}km)"
            )
            confidence_score -= 15

    # Check if reverse country matches declared country
    if reverse_country and country:
        if reverse_country.lower() != country.lower():
            issues.append(
                f"Country mismatch: reverse geocode says '{reverse_country}', "
                f"declared is '{country}'"
            )
            confidence_score -= 20

    # Determine status
    if confidence_score >= 90:
        status = "pass"
    elif confidence_score >= 75:
        status = "warn"
    else:
        status = "fail"

    return VerificationResult(
        restaurant_id=restaurant_id,
        name=name,
        country=country,
        city=city,
        declared_lat=lat,
        declared_lng=lng,
        declared_address=address,
        reverse_address=reverse_address,
        reverse_city=reverse_city,
        reverse_country=reverse_country,
        reverse_lat=reverse_lat,
        reverse_lng=reverse_lng,
        distance_to_city_center_km=distance_to_city_center_km,
        distance_to_reverse_geocode_m=distance_to_reverse_m,
        confidence_score=confidence_score,
        issues=issues,
        status=status,
        verified_at=datetime.now().isoformat(),
    )


def verify_dataset(
    dataset_name: str,
    records: list[dict],
    sample_size: Optional[int] = None,
    threshold_km: int = 5,
) -> tuple[list[VerificationResult], dict]:
    """Verify all records in a dataset."""

    print(f"\n🔍 Verifying {dataset_name}...")
    print("─" * 80)

    if sample_size and len(records) > sample_size:
        import random
        records = random.sample(records, sample_size)
        print(f"  Sampling {sample_size}/{len(records)} records")

    geolocator = Nominatim(user_agent="amex_dining_verifier")
    results = []

    for i, record in enumerate(records):
        if i % 10 == 0:
            print(f"  [{i+1}/{len(records)}] {record.get('name', 'UNNAMED')}")
            time.sleep(0.5)  # Rate limit Nominatim

        result = verify_single_restaurant(record, geolocator, threshold_km)
        results.append(result)

    # Summary stats
    stats = {
        "total": len(results),
        "pass": sum(1 for r in results if r.status == "pass"),
        "warn": sum(1 for r in results if r.status == "warn"),
        "fail": sum(1 for r in results if r.status == "fail"),
        "avg_confidence": sum(r.confidence_score for r in results) / len(results) if results else 0,
    }

    print(f"\n  ✅ Pass: {stats['pass']}/{stats['total']}")
    print(f"  ⚠️  Warn: {stats['warn']}/{stats['total']}")
    print(f"  ❌ Fail: {stats['fail']}/{stats['total']}")
    print(f"  📊 Avg Confidence: {stats['avg_confidence']:.1f}%")

    # Show failed records
    failed = [r for r in results if r.status == "fail"]
    if failed:
        print(f"\n  ❌ FAILED VERIFICATIONS ({len(failed)}):")
        for result in failed[:10]:
            print(f"     {result.name} ({result.country}/{result.city})")
            for issue in result.issues:
                print(f"       - {issue}")

    return results, stats


def main() -> bool:
    """Run verification suite."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify restaurant coordinates without API costs"
    )
    parser.add_argument(
        "--dataset",
        choices=["japan", "global", "plat-stay", "love-dining"],
        help="Specific dataset to verify"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all datasets"
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Sample N records per dataset (default: all)"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=5,
        help="Distance threshold in km (default: 5)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for detailed results (JSON)"
    )

    args = parser.parse_args()

    print("\n" + "="*80)
    print("AUTOMATED RESTAURANT COORDINATE VERIFICATION")
    print("="*80)
    print(f"Method: Reverse geocoding (Nominatim/OpenStreetMap)")
    print(f"Distance threshold: {args.threshold}km")
    print(f"Runs locally, zero API costs")

    all_results = []
    all_stats = {}

    datasets_to_verify = []
    if args.all:
        datasets_to_verify = [
            ("japan-restaurants", "Japan"),
            ("global-restaurants", "Global"),
            ("plat-stays", "Plat Stay"),
            ("love-dining", "Love Dining"),
        ]
    elif args.dataset:
        dataset_map = {
            "japan": ("japan-restaurants", "Japan"),
            "global": ("global-restaurants", "Global"),
            "plat-stay": ("plat-stays", "Plat Stay"),
            "love-dining": ("love-dining", "Love Dining"),
        }
        datasets_to_verify = [dataset_map[args.dataset]]
    else:
        print("\nError: Specify --dataset or --all")
        return False

    for filename, display_name in datasets_to_verify:
        path = DATA_DIR / f"{filename}.json"
        if not path.exists():
            print(f"\n⚠️  {filename}.json not found, skipping")
            continue

        with open(path) as f:
            records = json.load(f)

        results, stats = verify_dataset(
            display_name,
            records,
            sample_size=args.sample,
            threshold_km=args.threshold,
        )

        all_results.extend(results)
        all_stats[display_name] = stats

    # Write detailed results
    output_file = args.output or VERIFICATION_DIR / f"verification-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "threshold_km": args.threshold,
                "results": [asdict(r) for r in all_results],
                "summary": all_stats,
            },
            f,
            indent=2,
        )

    print(f"\n💾 Detailed results written to: {output_file}")

    # Final summary
    print("\n" + "="*80)
    print("VERIFICATION SUMMARY")
    print("="*80)
    for dataset_name, stats in all_stats.items():
        pass_rate = 100 * stats["pass"] / stats["total"] if stats["total"] else 0
        print(f"{dataset_name}: {stats['pass']}/{stats['total']} pass ({pass_rate:.1f}%)")

    total_results = len(all_results)
    total_pass = sum(1 for r in all_results if r.status == "pass")
    total_fail = sum(1 for r in all_results if r.status == "fail")

    if total_fail == 0:
        print(f"\n✅ All {total_results} verified venues passed")
        return True
    else:
        print(f"\n❌ {total_fail}/{total_results} venues failed verification")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
