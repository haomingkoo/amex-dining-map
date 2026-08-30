#!/usr/bin/env python3
"""Build the small deterministic TFT guide catalogue shipped with Railway."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SOURCE = Path("data/table-for-two.json")
DEFAULT_OUTPUT = Path("reminders/app/tft_guide_catalog.json")

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


def build_catalog(source: dict) -> dict:
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
                "explorer_route": f"#/table-for-two?venue={venue['id']}",
            }
        )
    return {
        "schema_version": 1,
        "source": "data/table-for-two.json",
        "program": source.get("program") or "Table for Two",
        "official_url": source["official_url"],
        "roster_checked_at": source.get("last_verified_at"),
        "menu_source": {
            "checked_at": (source.get("menu_source") or {}).get("checked_at")
        },
        "manual_review_required": bool(source.get("manual_review_required")),
        "venues": sorted(venues, key=lambda item: item["name"].casefold()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = build_catalog(json.loads(args.source.read_text()))
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
