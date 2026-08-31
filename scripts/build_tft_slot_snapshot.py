#!/usr/bin/env python3
"""Build the bounded public AMEXPlatSG slot projection used by Railway."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_SOURCE = Path("data/table-for-two.json")
DEFAULT_OUTPUT = Path("data/table-for-two-slots.json")
SOURCE_PROJECT = "AMEXPlatSG"
MAX_VENUES = 50
MAX_MEALS_PER_VENUE = 4
MAX_SLOTS = 20_000


def _max_seats(slot: dict, meal: dict) -> int:
    for value in (
        slot.get("max_seats"),
        slot.get("total_available_seats"),
        meal.get("max_seats"),
        meal.get("seats"),
    ):
        try:
            seats = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= seats <= 10:
            return seats
    return 0


def build_snapshot(source: dict) -> dict:
    source_project = (source.get("availability_source") or {}).get("project")
    if source_project != SOURCE_PROJECT:
        raise ValueError(f"availability source must declare project={SOURCE_PROJECT}")
    venues = source.get("venues") or []
    if not isinstance(venues, list) or len(venues) > MAX_VENUES:
        raise ValueError("venue count is invalid")
    projected = []
    slot_count = 0
    for venue in venues:
        if venue.get("booking_project_status") == "not_listed":
            continue
        venue_id = str(venue.get("id") or "")
        if re.fullmatch(r"[a-z0-9-]{1,80}", venue_id) is None:
            raise ValueError("venue id is invalid")
        availability = venue.get("availability") or {}
        meals = availability.get("meals") or []
        if not isinstance(meals, list) or len(meals) > MAX_MEALS_PER_VENUE:
            raise ValueError(f"meal count is invalid for {venue_id}")
        projected_meals = []
        for meal in meals:
            meal_name = str(meal.get("meal") or "")
            if meal_name not in {"Lunch", "Dinner"}:
                continue
            slots = []
            for slot in meal.get("slots") or []:
                slot_date = str(slot.get("date") or "")
                slot_time = str(slot.get("time") or "")
                if (
                    re.fullmatch(r"\d{4}-\d{2}-\d{2}", slot_date) is None
                    or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", slot_time)
                    is None
                ):
                    continue
                slots.append(
                    {
                        "date": slot_date,
                        "time": slot_time,
                        "max_seats": _max_seats(slot, meal),
                    }
                )
            unique = {
                (slot["date"], slot["time"], slot["max_seats"]): slot
                for slot in slots
            }
            ordered = [unique[key] for key in sorted(unique)]
            slot_count += len(ordered)
            if slot_count > MAX_SLOTS:
                raise ValueError("slot count exceeds the public projection limit")
            projected_meals.append(
                {
                    "meal": meal_name,
                    "status": str(meal.get("status") or "unknown"),
                    "slots": ordered,
                }
            )
        projected.append(
            {
                "id": venue_id,
                "project": availability.get("project"),
                "status": str(availability.get("status") or "unknown"),
                "checked_at": availability.get("checked_at")
                or availability.get("captured_at"),
                "meals": sorted(projected_meals, key=lambda item: item["meal"]),
            }
        )
    return {
        "schema_version": 1,
        "source_project": SOURCE_PROJECT,
        "generated_at": source.get("availability_last_checked_at"),
        "venues": sorted(projected, key=lambda item: item["id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    snapshot = build_snapshot(json.loads(args.source.read_text()))
    rendered = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            raise SystemExit(f"{args.output} is stale; rebuild the TFT slot snapshot")
        print("TFT slot snapshot is current")
        return 0
    args.output.write_text(rendered)
    print(
        f"Wrote {len(snapshot['venues'])} venues to {args.output} "
        f"({len(rendered.encode('utf-8'))} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
