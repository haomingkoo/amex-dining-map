#!/usr/bin/env python3
"""Audit active map pins for impossible country-level coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COUNTRY_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "Australia": (-44.5, -10.0, 112.0, 154.0),
    "Austria": (46.0, 50.0, 9.0, 18.0),
    "Canada": (41.0, 84.0, -141.0, -52.0),
    "China": (18.0, 54.0, 73.0, 135.5),
    "France": (41.0, 52.0, -6.0, 10.0),
    "Germany": (47.0, 56.0, 5.0, 16.0),
    "Greece": (34.0, 42.0, 19.0, 30.0),
    "Hong Kong": (22.1, 22.6, 113.8, 114.5),
    "Indonesia": (-11.5, 6.5, 94.0, 142.0),
    "Italy": (35.0, 48.0, 6.0, 19.0),
    "Japan": (24.0, 46.5, 122.0, 146.5),
    "Malaysia": (0.5, 7.5, 99.0, 120.0),
    "Maldives": (-1.0, 8.5, 72.0, 74.5),
    "Mexico": (14.0, 33.0, -119.0, -86.0),
    "Monaco": (43.70, 43.80, 7.40, 7.50),
    "Netherlands": (50.5, 54.0, 3.0, 7.5),
    "New Zealand": (-48.0, -33.0, 166.0, 179.9),
    "Portugal": (30.0, 42.5, -32.0, -6.0),
    "Singapore": (1.1, 1.5, 103.5, 104.1),
    "South Korea": (33.0, 39.5, 124.0, 132.0),
    "Spain": (27.0, 44.0, -19.0, 5.0),
    "Switzerland": (45.0, 48.0, 5.5, 11.0),
    "Taiwan": (21.5, 25.5, 119.0, 122.5),
    "Thailand": (5.0, 21.0, 97.0, 106.0),
    "Turkey": (35.0, 43.0, 25.0, 45.0),
    "United Arab Emirates": (22.0, 27.0, 51.0, 57.0),
    "United Kingdom": (49.0, 61.0, -9.0, 3.0),
    "United States": (18.0, 72.0, -171.0, -66.0),
    "Vietnam": (8.0, 24.5, 102.0, 110.5),
}


DATASETS = [
    ("global", Path("data/global-restaurants.json"), None, "lng"),
    ("japan", Path("data/japan-restaurants.json"), "Japan", "lng"),
    ("plat-stay", Path("data/plat-stays.json"), None, "lng"),
    ("love-dining", Path("data/love-dining.json"), "Singapore", "lon"),
    ("table-for-two", Path("data/table-for-two.json"), "Singapore", "lon"),
]


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "records", "restaurants", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    return []


def in_bounds(country: str | None, lat: float, lng: float) -> bool:
    bounds = COUNTRY_BOUNDS.get(country or "")
    if not bounds:
        return True
    min_lat, max_lat, min_lng, max_lng = bounds
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def audit_dataset(name: str, path: Path, default_country: str | None, lng_key: str) -> tuple[int, int, int, list[str]]:
    records = records_from_payload(json.loads(path.read_text(encoding="utf-8")))
    mapped = 0
    missing = 0
    checked = 0
    issues: list[str] = []

    for record in records:
        lat = record.get("lat")
        lng = record.get(lng_key if lng_key in record else "lng")
        if lat is None or lng is None:
            missing += 1
            continue

        mapped += 1
        country = record.get("country") or default_country
        if country not in COUNTRY_BOUNDS:
            continue

        checked += 1
        lat_float = float(lat)
        lng_float = float(lng)
        if not in_bounds(country, lat_float, lng_float):
            issues.append(
                f"{name}: {record.get('id')} / {record.get('name')} "
                f"has {lat_float}, {lng_float} outside {country}"
            )

    return mapped, missing, checked, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable audit output")
    args = parser.parse_args()

    results = []
    all_issues: list[str] = []
    for dataset in DATASETS:
        mapped, missing, checked, issues = audit_dataset(*dataset)
        results.append({
            "dataset": dataset[0],
            "mapped": mapped,
            "missing": missing,
            "checked": checked,
            "issues": issues,
        })
        all_issues.extend(issues)

    if args.json:
        print(json.dumps({"issue_count": len(all_issues), "datasets": results}, indent=2))
    else:
        for result in results:
            print(
                f"{result['dataset']}: checked {result['checked']} of {result['mapped']} mapped pins; "
                f"{result['missing']} records missing coordinates"
            )
        if all_issues:
            print("\nOut-of-bounds pins:")
            for issue in all_issues:
                print(f"- {issue}")
        else:
            print("\nNo out-of-bounds active pins found.")

    return 1 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
