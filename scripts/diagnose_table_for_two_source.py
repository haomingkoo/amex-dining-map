#!/usr/bin/env python3
"""Compare Table for Two cache source responses for one DiningCity venue.

This is a read-only diagnostic. It intentionally does not write to
data/table-for-two.json because app screenshots and generic booking slots are
not Table for Two cache data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_table_for_two import DININGCITY_PROJECT, VENUES, fetch_json  # noqa: E402


def normalized(value: object) -> str:
    return str(value or "").strip().lower()


def find_venue(query: str) -> dict:
    needle = normalized(query)
    for venue in VENUES:
        haystack = {
            normalized(venue.get("id")),
            normalized(venue.get("name")),
            normalized(venue.get("app_name")),
            normalized(venue.get("dining_city_id")),
            normalized(venue.get("dining_city_name")),
        }
        if needle in haystack:
            return venue
    for venue in VENUES:
        joined = " ".join(
            normalized(venue.get(key))
            for key in ("id", "name", "app_name", "dining_city_id", "dining_city_name")
        )
        if needle and needle in joined:
            return venue
    raise SystemExit(f"No Table for Two venue matched {query!r}.")


def project_summary(projects: object) -> str:
    if not isinstance(projects, list):
        return "project list unavailable"
    for project in projects:
        if isinstance(project, dict) and project.get("project") == DININGCITY_PROJECT:
            count = project.get("online_restaurant_count")
            count_text = f", online_restaurant_count={count}" if count is not None else ""
            return f"{DININGCITY_PROJECT} present{count_text}"
    return f"{DININGCITY_PROJECT} not present"


def available_2018_summary(payload: object) -> tuple[int, int, list[str], list[str]]:
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    dates: set[str] = set()
    times: set[str] = set()
    slot_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("date"):
            dates.add(str(row["date"]))
        for slot in row.get("times") or []:
            if not isinstance(slot, dict):
                continue
            slot_count += 1
            if slot.get("time"):
                times.add(str(slot["time"]))
    return len(rows), slot_count, sorted(dates), sorted(times)


def booking_slot_summary(payload: object) -> tuple[int, list[str], list[str]]:
    slots = payload.get("time_slots", []) if isinstance(payload, dict) else []
    if not isinstance(slots, list):
        slots = []
    dates = sorted({str(slot.get("date")) for slot in slots if isinstance(slot, dict) and slot.get("date")})
    times = sorted({
        str(slot.get("formated_time") or slot.get("time"))
        for slot in slots
        if isinstance(slot, dict) and (slot.get("formated_time") or slot.get("time"))
    })
    return len(slots), dates, times


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", nargs="?", default="Colony", help="Venue name, id, or DiningCity id")
    parser.add_argument("--date", default="2026-04-29", help="Selected date to probe in YYYY-MM-DD form")
    args = parser.parse_args()

    venue = find_venue(args.venue)
    dining_city_id = venue.get("dining_city_id")
    if not dining_city_id:
        raise SystemExit(f"{venue.get('name')} has no DiningCity id.")

    projects = fetch_json(f"/restaurants/{dining_city_id}/projects/program_and_event")
    amex_payload = fetch_json(f"/restaurants/{dining_city_id}/available_2018", {"project": DININGCITY_PROJECT})
    selected_payload = fetch_json(
        f"/restaurants/{dining_city_id}/available_2018",
        {"project": DININGCITY_PROJECT, "selected_date": args.date},
    )
    generic_booking = fetch_json(f"/restaurants/{dining_city_id}/book_now_available_time_slots")

    rows, slot_count, dates, times = available_2018_summary(amex_payload)
    selected_rows, selected_slot_count, selected_dates, selected_times = available_2018_summary(selected_payload)
    generic_count, generic_dates, generic_times = booking_slot_summary(generic_booking)

    print(f"Venue: {venue.get('app_name') or venue.get('name')} ({dining_city_id})")
    print(f"Project listing: {project_summary(projects)}")
    print(
        f"AMEXPlatSG available_2018: {rows} date rows, {slot_count} slot rows"
        f"{f' | dates={dates[:5]}' if dates else ''}"
        f"{f' | times={times[:8]}' if times else ''}"
    )
    print(
        f"AMEXPlatSG available_2018 selected_date={args.date}: {selected_rows} date rows, "
        f"{selected_slot_count} slot rows"
        f"{f' | dates={selected_dates[:5]}' if selected_dates else ''}"
        f"{f' | times={selected_times[:8]}' if selected_times else ''}"
    )
    print(
        f"Generic book_now_available_time_slots: {generic_count} slots"
        f"{f' | dates={generic_dates[:5]}' if generic_dates else ''}"
        f"{f' | times={generic_times[:8]}' if generic_times else ''}"
    )
    print()
    print("Interpretation:")
    print("- available_2018 with AMEXPlatSG is the cache source used by this app.")
    print("- book_now_available_time_slots is generic DiningCity booking inventory and is not treated as Table for Two.")
    print("- If the Amex app shows seats while AMEXPlatSG returns empty, the app is using authenticated or app-specific context we do not have in GitHub.")
    print()
    print("Raw generic booking response:")
    print(json.dumps(generic_booking, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
