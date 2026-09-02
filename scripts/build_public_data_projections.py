#!/usr/bin/env python3
"""Build small route-specific projections for the static Explorer deployment."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


RELEASE_SUMMARY_KEYS = ("schema_version", "source_project", "updated_at", "patterns")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def tft_ratings_projection(table_for_two: dict, ratings: dict) -> dict:
    venues = table_for_two.get("venues")
    if not isinstance(venues, list) or not venues:
        raise ValueError("Table for Two payload must contain venues")

    venue_ids = [venue.get("id") for venue in venues if isinstance(venue, dict)]
    if len(venue_ids) != len(venues) or any(not isinstance(venue_id, str) for venue_id in venue_ids):
        raise ValueError("Every Table for Two venue must have a string id")
    if len(set(venue_ids)) != len(venue_ids):
        raise ValueError("Table for Two venue ids must be unique")
    if not isinstance(ratings, dict):
        raise ValueError("Google ratings payload must be an object")

    missing = [venue_id for venue_id in venue_ids if venue_id not in ratings]
    if missing:
        raise ValueError(f"Missing Google ratings for Table for Two venues: {', '.join(missing)}")
    return {venue_id: ratings[venue_id] for venue_id in venue_ids}


def tft_catalog_projection(table_for_two: dict) -> dict:
    """Keep venue/menu provenance while moving duplicated slots to the slot snapshot."""
    if not isinstance(table_for_two, dict):
        raise ValueError("Table for Two payload must be an object")
    projected = copy.deepcopy(table_for_two)
    venues = projected.get("venues")
    if not isinstance(venues, list) or not venues:
        raise ValueError("Table for Two payload must contain venues")
    ids = [venue.get("id") for venue in venues if isinstance(venue, dict)]
    diningcity_ids = [
        str(venue.get("dining_city_id") or "")
        for venue in venues
        if isinstance(venue, dict)
    ]
    if len(ids) != len(venues) or len(set(ids)) != len(ids):
        raise ValueError("Table for Two venue ids must be present and unique")
    if "" in diningcity_ids or len(set(diningcity_ids)) != len(diningcity_ids):
        raise ValueError("Table for Two DiningCity ids must be present and unique")
    for venue in venues:
        venue.pop("availability", None)
    return projected


def release_history_summary(history: dict) -> dict:
    if not isinstance(history, dict):
        raise ValueError("Release history payload must be an object")
    missing = [key for key in RELEASE_SUMMARY_KEYS if key not in history]
    if missing:
        raise ValueError(f"Release history is missing: {', '.join(missing)}")
    if not isinstance(history["patterns"], list):
        raise ValueError("Release history patterns must be a list")
    return {key: history[key] for key in RELEASE_SUMMARY_KEYS}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-for-two", type=Path, required=True)
    parser.add_argument("--ratings", type=Path, required=True)
    parser.add_argument("--release-history", type=Path, required=True)
    parser.add_argument("--tft-catalog-output", type=Path, required=True)
    parser.add_argument("--tft-ratings-output", type=Path, required=True)
    parser.add_argument("--release-summary-output", type=Path, required=True)
    args = parser.parse_args()

    table_for_two = load_json(args.table_for_two)
    tft_catalog = tft_catalog_projection(table_for_two)
    tft_ratings = tft_ratings_projection(
        table_for_two,
        load_json(args.ratings),
    )
    release_summary = release_history_summary(load_json(args.release_history))
    write_json(args.tft_catalog_output, tft_catalog)
    write_json(args.tft_ratings_output, tft_ratings)
    write_json(args.release_summary_output, release_summary)
    print(
        f"Public projections: {len(tft_catalog['venues'])} TFT venues, "
        f"{len(tft_ratings)} TFT ratings, "
        f"{len(release_summary['patterns'])} release patterns"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
