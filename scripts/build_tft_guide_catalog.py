#!/usr/bin/env python3
"""Build the small deterministic TFT guide catalogue shipped with Railway."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = Path("data/table-for-two.json")
DEFAULT_RELEASE_HISTORY = Path("data/table-for-two-release-history.json")
DEFAULT_OUTPUT = Path("reminders/app/tft_guide_catalog.json")
SOURCE_PROJECT = "AMEXPlatSG"

REVIEWED_ALIASES = {
    "tft-15-stamford-restaurant": ["15 Stamford"],
    "tft-colony": ["Colony at the Ritz Carlton", "Colony Ritz Carlton"],
    "tft-cultivate": ["Cultivate Cafe"],
    "tft-ginger": ["Ginger at Park Royal"],
    "tft-kees": ["Kees"],
    "tft-one-ninety": ["One Ninety", "One Ninety Restaurant"],
    "tft-vineyard": ["Vineyard at Hort Park"],
}


def _menu_projection(menu: dict | None) -> dict | None:
    if not isinstance(menu, dict):
        return None
    return {
        key: menu.get(key)
        for key in (
            "status",
            "url",
            "filename",
            "card",
            "label",
            "checked_at",
            "last_seen_at",
            "sha256",
        )
        if menu.get(key) is not None
    }


def _parsed_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _release_projection(history: dict, venue_ids: set[str]) -> dict[str, list[dict]]:
    if history.get("source_project") != SOURCE_PROJECT:
        raise ValueError(f"release history must declare source_project={SOURCE_PROJECT}")
    latest: dict[tuple[str, str], tuple[datetime, str]] = {}
    for observation in history.get("observations") or []:
        venue_id = observation.get("venue_id")
        meal = observation.get("meal")
        observed_at = observation.get("first_seen_at")
        try:
            lead_days = int(observation.get("lead_days"))
        except (TypeError, ValueError):
            continue
        parsed_at = _parsed_time(observed_at)
        if (
            venue_id not in venue_ids
            or not meal
            or observation.get("baseline")
            or lead_days < 0
            or parsed_at is None
        ):
            continue
        key = (str(venue_id), str(meal))
        if key not in latest or parsed_at > latest[key][0]:
            latest[key] = (parsed_at, str(observed_at))

    projected: dict[str, list[dict]] = {venue_id: [] for venue_id in venue_ids}
    for pattern in history.get("patterns") or []:
        venue_id = pattern.get("venue_id")
        meal = pattern.get("meal")
        if venue_id not in venue_ids or not meal:
            continue
        projected[str(venue_id)].append(
            {
                key: pattern.get(key)
                for key in (
                    "meal",
                    "observation_count",
                    "median_lead_days",
                    "lead_days_min",
                    "lead_days_max",
                    "typical_first_seen_sgt",
                    "typical_time_observation_share",
                    "confidence",
                )
            }
            | {
                "latest_observation_at": (
                    latest.get((str(venue_id), str(meal))) or (None, None)
                )[1]
            }
        )
    return {
        venue_id: sorted(patterns, key=lambda item: str(item["meal"]).casefold())
        for venue_id, patterns in projected.items()
    }


def build_catalog(source: dict, release_history: dict | None = None) -> dict:
    if release_history is None:
        release_history = json.loads(DEFAULT_RELEASE_HISTORY.read_text())
    venue_ids = {str(venue["id"]) for venue in source.get("venues") or []}
    release_patterns = _release_projection(release_history, venue_ids)
    venues = []
    for venue in source.get("venues") or []:
        menus = {
            card: projected
            for card, menu in sorted((venue.get("menu_pdfs") or {}).items())
            if (projected := _menu_projection(menu)) is not None
        }
        fallback = _menu_projection(venue.get("menu_pdf"))
        if not menus and fallback:
            menus[str(fallback.get("card") or "default").lower()] = fallback
        venues.append(
            {
                "id": venue["id"],
                "name": venue["name"],
                "dining_city_name": venue.get("dining_city_name"),
                "category": venue.get("category"),
                "address": venue.get("address"),
                "aliases": REVIEWED_ALIASES.get(venue["id"], []),
                "menus": menus,
                "release_patterns": release_patterns.get(venue["id"], []),
                "explorer_route": f"#/table-for-two?venue={venue['id']}",
            }
        )
    return {
        "schema_version": 2,
        "source": "data/table-for-two.json",
        "program": source.get("program") or "Table for Two",
        "official_url": source["official_url"],
        "roster_checked_at": source.get("last_verified_at"),
        "menu_source": {
            "checked_at": (source.get("menu_source") or {}).get("checked_at")
        },
        "release_source": {
            "source": "data/table-for-two-release-history.json",
            "project": release_history.get("source_project"),
            "updated_at": release_history.get("updated_at"),
            "observation_count": len(release_history.get("observations") or []),
        },
        "manual_review_required": bool(source.get("manual_review_required")),
        "venues": sorted(venues, key=lambda item: item["name"].casefold()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--release-history", type=Path, default=DEFAULT_RELEASE_HISTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = build_catalog(
        json.loads(args.source.read_text()),
        json.loads(args.release_history.read_text()),
    )
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            raise SystemExit(f"{args.output} is stale; rebuild the TFT guide catalogue")
        print("TFT guide catalogue is current")
        return 0
    args.output.write_text(rendered)
    print(f"Wrote {len(catalog['venues'])} TFT guide venues to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
