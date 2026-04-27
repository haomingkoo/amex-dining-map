#!/usr/bin/env python3
"""
Enrich all restaurant datasets with Google Maps ratings using gosom/google-maps-scraper.

Covers:
  - data/global-restaurants.json   (Global Dining Credit, 2470 records)
  - data/japan-restaurants.json    (Pocket Concierge Japan, ~844 records)
  - data/love-dining.json          (Love Dining SG restaurants + hotel outlets, 79 records)
  - data/table-for-two.json        (Table for Two SG, 18 records)

Usage:
    # Full run (all datasets, writes to data/google-maps-ratings.json)
    python3 scripts/scrape_google_ratings.py

    # Specific datasets only
    python3 scripts/scrape_google_ratings.py --datasets global japan love tft

    # Dry run — generate queries file but don't run Docker
    python3 scripts/scrape_google_ratings.py --dry-run

    # Only re-scrape records not yet in the ratings cache
    python3 scripts/scrape_google_ratings.py --missing-only

    # Concurrency (default 4, lower = fewer bot detections)
    python3 scripts/scrape_google_ratings.py --concurrency 4

Requirements:
    docker (gosom/google-maps-scraper image)

Output:
    data/google-maps-ratings.json  — {restaurant_id: {rating, review_count, google_name, google_address, maps_url}}
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
RATINGS_PATH = DATA_DIR / "google-maps-ratings.json"

DOCKER_IMAGE = "gosom/google-maps-scraper"


# ─── Query generation ─────────────────────────────────────────────────────────

def make_query(record: dict, dataset: str) -> str:
    """Build a Google Maps search query for a restaurant record."""
    name = record.get("name", "")

    if dataset == "japan":
        city = record.get("city", "")
        prefecture = record.get("prefecture", "")
        loc = city or prefecture or "Japan"
        return f"{name} {loc} Japan"

    if dataset == "love":
        hotel = record.get("hotel", "")
        address = record.get("address", "")
        # Use first part of address (up to postal code) for disambiguation
        addr_short = re.split(r"Singapore \d{6}", address)[0].strip().rstrip(",")
        if hotel:
            return f"{name} {hotel} Singapore"
        return f"{name} {addr_short} Singapore" if addr_short else f"{name} Singapore"

    if dataset == "tft":
        display_name = record.get("dining_city_name") or name
        address = record.get("address", "")
        addr_short = re.split(r"Singapore \d{6}", address)[0].strip().rstrip(",")
        return f"{display_name} {addr_short} Singapore" if addr_short else f"{display_name} Singapore"

    # Global: use country + city
    country = record.get("country", "")
    city = record.get("city", "")
    loc = f"{city}, {country}" if city and city != country else country
    return f"{name} {loc}"


def build_queries(records: list[dict], dataset: str, existing_ids: set) -> list[tuple[str, str]]:
    """Return list of (query_line, record_id) pairs."""
    pairs = []
    for rec in records:
        rid = rec.get("id", "")
        if not rid:
            continue
        if rid in existing_ids:
            continue
        query = make_query(rec, dataset)
        # gosom supports custom ID with #!# separator
        pairs.append((f"{query} #!#{rid}", rid))
    return pairs


# ─── Docker runner ─────────────────────────────────────────────────────────────

def run_docker(queries_file: Path, results_file: Path, concurrency: int) -> bool:
    """Run gosom/google-maps-scraper via Docker. Returns True on success."""
    results_file.touch()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{queries_file}:/queries.txt:ro",
        "-v", f"{results_file}:/results.json",
        DOCKER_IMAGE,
        "-depth", "1",
        "-input", "/queries.txt",
        "-results", "/results.json",
        "-json",
        "-c", str(concurrency),
        "-exit-on-inactivity", "3m",
    ]

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


# ─── Result parsing ────────────────────────────────────────────────────────────

def parse_results(results_file: Path) -> list[dict]:
    """Parse gosom JSON output into a list of result records."""
    text = results_file.read_text().strip()
    if not text:
        return []

    # gosom outputs newline-delimited JSON objects
    records = []
    for line in text.splitlines():
        line = line.strip().strip(",").strip("[]")
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    # Fallback: try as JSON array
    if not records:
        try:
            records = json.loads(text)
        except json.JSONDecodeError:
            pass

    return records


def extract_id_from_input_id(result: dict) -> str | None:
    """gosom echoes the #!# custom ID in the 'input_id' or 'query' field."""
    for field in ("input_id", "query", "inputId"):
        val = result.get(field, "")
        if "#!#" in str(val):
            return val.split("#!#", 1)[1].strip()
    return None


def match_results_to_ids(
    raw_results: list[dict],
    id_map: dict[str, dict],  # query_line → record
) -> dict[str, dict]:
    """Map gosom output records back to our restaurant IDs."""
    matched: dict[str, dict] = {}

    for r in raw_results:
        rid = extract_id_from_input_id(r)
        if not rid:
            continue

        rating = r.get("review_rating") or r.get("rating")
        review_count = r.get("review_count") or r.get("reviewCount")

        # Skip if no useful data
        if rating is None and review_count is None:
            continue

        matched[rid] = {
            "rating": float(rating) if rating else None,
            "review_count": int(review_count) if review_count else None,
            "google_name": r.get("title") or r.get("name"),
            "google_address": r.get("address"),
            "maps_url": r.get("link") or r.get("url"),
            "scraped_at": time.strftime("%Y-%m-%d"),
        }

    return matched


# ─── Dataset loaders ──────────────────────────────────────────────────────────

def load_datasets(names: list[str]) -> dict[str, list[dict]]:
    datasets: dict[str, list[dict]] = {}
    if "global" in names:
        f = DATA_DIR / "global-restaurants.json"
        if f.exists():
            datasets["global"] = json.loads(f.read_text())
            print(f"  global: {len(datasets['global'])} records")
    if "japan" in names:
        f = DATA_DIR / "japan-restaurants.json"
        if f.exists():
            datasets["japan"] = json.loads(f.read_text())
            print(f"  japan: {len(datasets['japan'])} records")
    if "love" in names:
        f = DATA_DIR / "love-dining.json"
        if f.exists():
            datasets["love"] = json.loads(f.read_text())
            print(f"  love: {len(datasets['love'])} records")
    if "tft" in names:
        f = DATA_DIR / "table-for-two.json"
        if f.exists():
            payload = json.loads(f.read_text())
            datasets["tft"] = payload.get("venues", []) if isinstance(payload, dict) else payload
            print(f"  tft: {len(datasets['tft'])} records")
    return datasets


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Google Maps ratings for all restaurant datasets")
    p.add_argument("--datasets", nargs="+", default=["global", "japan", "love", "tft"],
                   choices=["global", "japan", "love", "tft"],
                   help="Which datasets to process (default: all)")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate queries file but don't run Docker")
    p.add_argument("--missing-only", action="store_true",
                   help="Only scrape records not yet in ratings cache")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Docker scraper concurrency (default: 4, lower = safer)")
    p.add_argument("--batch-size", type=int, default=500,
                   help="Process in batches of N (default: 500)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Load existing ratings cache
    existing_ratings: dict[str, dict] = {}
    if RATINGS_PATH.exists():
        existing_ratings = json.loads(RATINGS_PATH.read_text())
        print(f"Existing cache: {len(existing_ratings)} records")

    existing_ids = set(existing_ratings.keys()) if args.missing_only else set()

    print(f"\nLoading datasets: {args.datasets}")
    datasets = load_datasets(args.datasets)

    if not datasets:
        print("No datasets loaded. Check data files exist.")
        sys.exit(1)

    # Build full query list across all datasets
    all_queries: list[tuple[str, str]] = []
    for name, records in datasets.items():
        pairs = build_queries(records, name, existing_ids)
        print(f"  {name}: {len(pairs)} queries to run (of {len(records)} records)")
        all_queries.extend(pairs)

    print(f"\nTotal queries: {len(all_queries)}")

    if not all_queries:
        print("Nothing to scrape — all records already in cache.")
        return

    if args.dry_run:
        dry_path = DATA_DIR / "google-maps-queries.txt"
        dry_path.write_text("\n".join(q for q, _ in all_queries) + "\n")
        print(f"Dry run: queries written to {dry_path}")
        print("Run without --dry-run to execute Docker scraper.")
        return

    # Process in batches
    batch_size = args.batch_size
    batches = [all_queries[i:i+batch_size] for i in range(0, len(all_queries), batch_size)]
    print(f"\nProcessing {len(batches)} batch(es) of up to {batch_size} queries...")

    new_ratings: dict[str, dict] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for batch_num, batch in enumerate(batches, 1):
            print(f"\n─── Batch {batch_num}/{len(batches)} ({len(batch)} queries) ───")
            queries_file = tmp / f"queries_{batch_num}.txt"
            results_file = tmp / f"results_{batch_num}.json"

            queries_file.write_text("\n".join(q for q, _ in batch) + "\n")

            success = run_docker(queries_file, results_file, args.concurrency)
            if not success:
                print(f"  ⚠  Docker returned non-zero for batch {batch_num}")

            raw = parse_results(results_file)
            print(f"  Raw results: {len(raw)} records returned")

            matched = match_results_to_ids(raw, {})
            print(f"  Matched: {len(matched)} records with rating data")
            new_ratings.update(matched)

            # Save incremental progress after each batch
            merged = {**existing_ratings, **new_ratings}
            RATINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
            print(f"  Saved {len(merged)} total ratings → {RATINGS_PATH}")

    merged = {**existing_ratings, **new_ratings}
    RATINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")

    total = len(merged)
    added = len(new_ratings)
    print(f"\nDone. Added {added} new ratings. Total cache: {total}")
    print(f"Output → {RATINGS_PATH}")


if __name__ == "__main__":
    main()
