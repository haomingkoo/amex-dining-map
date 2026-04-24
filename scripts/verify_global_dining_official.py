#!/usr/bin/env python3
"""Verify local Global Dining data against the official Amex dining API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import scrape_global_dining as global_sync


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "global-restaurants.json"


def record_key(record: dict[str, Any]) -> str:
    merchant_id = record.get("source_merchant_id")
    if merchant_id:
        return f"id:{merchant_id}"
    return "name:" + "|".join(
        global_sync.normalized_ascii(record.get(field))
        for field in ("country", "city", "name", "source_localized_address")
    )


def display_record(record: dict[str, Any]) -> str:
    parts = [
        record.get("name") or "Unknown",
        record.get("city") or record.get("region"),
        record.get("country"),
    ]
    return " / ".join(str(part) for part in parts if part)


def fetch_official_country_records(country_code: str) -> tuple[str, list[dict[str, Any]], int]:
    countries_payload = global_sync.http_json(global_sync.COUNTRIES_API_URL, retries=4)
    countries = global_sync.official_country_candidates(countries_payload)
    country = next((item for item in countries if item.get("key") == country_code), None)
    if not country:
        raise RuntimeError(f"{country_code} is not an active official Amex Global Dining country")

    official_records: list[dict[str, Any]] = []
    merchants = global_sync.fetch_official_merchants(country_code)
    for merchant in merchants:
        for row, parent in global_sync.official_merchant_rows(merchant):
            official_records.append(global_sync.build_record_from_official_api(country, row, parent))
    return global_sync.official_country_name(country), official_records, len(merchants)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country-code", default="TW", help="ISO country code to verify, e.g. TW or SG")
    parser.add_argument("--all", action="store_true", help="Verify every active non-Japan country")
    parser.add_argument("--max-list", type=int, default=25, help="Maximum missing/extra records to print")
    args = parser.parse_args()

    if args.all:
        countries_payload = global_sync.http_json(global_sync.COUNTRIES_API_URL, retries=4)
        country_codes = [country["key"] for country in global_sync.official_country_candidates(countries_payload)]
    else:
        country_codes = [args.country_code.upper()]

    local_records = json.loads(DATA_PATH.read_text())
    failures = 0

    for country_code in country_codes:
        country_name, official_records, official_top_level_count = fetch_official_country_records(country_code)

        local_country_records = [record for record in local_records if record.get("country") == country_name]
        local_by_key = {record_key(record): record for record in local_country_records}
        official_by_key = {record_key(record): record for record in official_records}

        missing_keys = sorted(set(official_by_key) - set(local_by_key))
        extra_keys = sorted(set(local_by_key) - set(official_by_key))

        print(f"{country_name}: official top-level={official_top_level_count}, official expanded={len(official_records)}, local expanded={len(local_country_records)}")

        if missing_keys:
            failures += 1
            print("  Missing locally:")
            for key in missing_keys[: args.max_list]:
                print(f"    + {display_record(official_by_key[key])}")
            if len(missing_keys) > args.max_list:
                print(f"    ... and {len(missing_keys) - args.max_list} more")

        if extra_keys:
            failures += 1
            print("  Extra locally:")
            for key in extra_keys[: args.max_list]:
                print(f"    - {display_record(local_by_key[key])}")
            if len(extra_keys) > args.max_list:
                print(f"    ... and {len(extra_keys) - args.max_list} more")

    if failures:
        print(f"\nFAILED: {failures} country comparison issue(s)")
        return 1

    scope = "all active countries" if args.all else "this country"
    print(f"\nOK: local records match the official Amex API for {scope}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
