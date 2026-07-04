#!/usr/bin/env python3
"""Cache public Pocket Concierge availability for Japan dining filters."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESTAURANTS_PATH = DATA_DIR / "japan-restaurants.json"
OUTPUT_PATH = DATA_DIR / "pocket-availability.json"

GRAPHQL_URL = "https://pocket-concierge.jp/graphql"
SOURCE_URL = "https://pocket-concierge.jp/en/"
USER_AGENT = "JapanDiningMapMVP/0.2 (+https://local.dev)"
DEFAULT_DAYS = 90
DEFAULT_WORKERS = 12

CALENDAR_QUERY = """
query VenueAvailabilityCalendar($id: ID!) {
  venue(id: $id) {
    availabilityCalendar {
      reservationDates
      waitlistDates
    }
  }
}
""".strip()

AVAILABILITY_QUERY = """
query AvailabilitySearch($venueId: ID!, $date: ISO8601Date!) {
  availabilitySearch(venueId: $venueId, date: $date) {
    ... on ReservableAvailability {
      id
      startTime
      endTime
      seatingType
      maxPartySize
      minPartySize
      course {
        serviceType
      }
    }
    ... on WaitlistableAvailability {
      startTime
      endTime
      maxPartySize
      minPartySize
      course {
        serviceType
      }
    }
  }
}
""".strip()


def post_graphql(query: str, variables: dict, operation_name: str, retries: int = 4) -> dict:
    payload = json.dumps({
        "operationName": operation_name,
        "query": query,
        "variables": variables,
    }).encode("utf-8")
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt in range(retries):
        request = urllib.request.Request(
            GRAPHQL_URL,
            data=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://pocket-concierge.jp",
                "Referer": SOURCE_URL,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in retry_statuses and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise

    return {}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def pocket_venue_id(record: dict) -> str:
    raw = str(record.get("id") or "")
    if raw.startswith("pocket-"):
        return raw.removeprefix("pocket-")
    return raw


def calendar_for(record: dict) -> tuple[str, dict]:
    record_id = str(record.get("id") or "")
    venue_id = pocket_venue_id(record)
    response = post_graphql(
        CALENDAR_QUERY,
        {"id": venue_id},
        "VenueAvailabilityCalendar",
    )
    errors = response.get("errors")
    calendar = (
        ((response.get("data") or {}).get("venue") or {}).get("availabilityCalendar")
        or {}
    )
    return record_id, {
        "venue_id": venue_id,
        "reservation_dates": sorted(set(calendar.get("reservationDates") or [])),
        "waitlist_dates": sorted(set(calendar.get("waitlistDates") or [])),
        "error": "; ".join(error.get("message", "GraphQL error") for error in errors or []) or None,
    }


def normalize_time(value: str | None) -> str:
    if not value or "T" not in value:
        return ""
    return value.split("T", 1)[1][:5]


def normalize_slot_date(value: str | None) -> str:
    if not value:
        return ""
    return value[:10]


def compact_ranges(ranges: set[tuple[int, int]]) -> list[list[int]]:
    return [list(item) for item in sorted(ranges)]


def summarize_slots(slots: list[dict]) -> dict[str, dict]:
    by_date: dict[str, dict] = defaultdict(lambda: {
        "times": set(),
        "sessions": set(),
        "party_ranges": set(),
        "seating": set(),
        "slot_count": 0,
    })

    for slot in slots:
        if not slot.get("id"):
            continue
        slot_date = normalize_slot_date(slot.get("startTime"))
        if not slot_date:
            continue
        min_party = int(slot.get("minPartySize") or 0)
        max_party = int(slot.get("maxPartySize") or 0)
        if min_party <= 0 or max_party <= 0:
            continue
        bucket = by_date[slot_date]
        bucket["slot_count"] += 1
        bucket["party_ranges"].add((min_party, max_party))
        time_value = normalize_time(slot.get("startTime"))
        if time_value:
            bucket["times"].add(time_value)
        seating = slot.get("seatingType")
        if seating:
            bucket["seating"].add(str(seating))
        service = ((slot.get("course") or {}).get("serviceType") or "").upper()
        if service:
            bucket["sessions"].add(service)

    compacted = {}
    for slot_date, bucket in sorted(by_date.items()):
        ranges = compact_ranges(bucket["party_ranges"])
        compacted[slot_date] = {
            "times": sorted(bucket["times"]),
            "sessions": sorted(bucket["sessions"]),
            "party_ranges": ranges,
            "seating": sorted(bucket["seating"]),
            "slot_count": bucket["slot_count"],
            "min_party_size": min(item[0] for item in ranges),
            "max_party_size": max(item[1] for item in ranges),
        }
    return compacted


def availability_for(job: tuple[str, str, str]) -> tuple[str, str, dict]:
    record_id, venue_id, selected_date = job
    response = post_graphql(
        AVAILABILITY_QUERY,
        {"venueId": venue_id, "date": selected_date},
        "AvailabilitySearch",
    )
    errors = response.get("errors")
    if errors:
        return record_id, selected_date, {
            "error": "; ".join(error.get("message", "GraphQL error") for error in errors),
        }
    slots = (response.get("data") or {}).get("availabilitySearch") or []
    return record_id, selected_date, summarize_slots(slots).get(selected_date, {})


def date_in_window(value: str, start: date, end: date) -> bool:
    return start.isoformat() <= value <= end.isoformat()


def build_payload(restaurants: list[dict], days: int, workers: int) -> dict:
    fetched_at = datetime.now(UTC).isoformat()
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    window_end = today + timedelta(days=days)

    records: dict[str, dict] = {}
    print(f"Fetching Pocket Concierge calendars for {len(restaurants)} venues...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(calendar_for, record): record for record in restaurants}
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            try:
                record_id, calendar = future.result()
            except Exception as exc:
                record_id = str(futures[future].get("id") or f"error-{index}")
                calendar = {"error": str(exc), "reservation_dates": [], "waitlist_dates": [], "dates": {}}
            calendar["dates"] = {}
            records[record_id] = calendar
            if index % 100 == 0:
                print(f"Fetched {index}/{len(restaurants)} calendars...")

    jobs: list[tuple[str, str, str]] = []
    for record_id, record in records.items():
        venue_id = record.get("venue_id")
        if not venue_id:
            continue
        for selected_date in record.get("reservation_dates") or []:
            if date_in_window(selected_date, today, window_end):
                jobs.append((record_id, venue_id, selected_date))

    print(f"Fetching {len(jobs)} date-level availability checks through {window_end.isoformat()}...")
    slot_errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(availability_for, job) for job in jobs]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            try:
                record_id, selected_date, date_summary = future.result()
            except Exception as exc:
                slot_errors += 1
                continue
            if date_summary.get("error"):
                slot_errors += 1
            if date_summary:
                records[record_id]["dates"][selected_date] = date_summary
            if index % 500 == 0:
                print(f"Fetched {index}/{len(jobs)} date checks...")

    available_venues = sum(1 for record in records.values() if record.get("dates"))
    waitlist_venues = sum(1 for record in records.values() if record.get("waitlist_dates"))
    slot_date_count = sum(len(record.get("dates") or {}) for record in records.values())
    return {
        "dataset": "pocket_concierge_availability",
        "source_name": "Pocket Concierge",
        "source_url": SOURCE_URL,
        "api_url": GRAPHQL_URL,
        "fetched_at": fetched_at,
        "window_start": today.isoformat(),
        "window_end": window_end.isoformat(),
        "window_days": days,
        "venue_count": len(restaurants),
        "calendar_checked_count": len(records),
        "date_check_count": len(jobs),
        "date_check_error_count": slot_errors,
        "available_venue_count": available_venues,
        "waitlist_venue_count": waitlist_venues,
        "slot_date_count": slot_date_count,
        "records": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(RESTAURANTS_PATH))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=0, help="Limit venues for smoke checks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    restaurants = load_json(Path(args.input))
    if args.limit:
        restaurants = restaurants[:args.limit]
    payload = build_payload(restaurants, max(args.days, 0), max(args.workers, 1))
    save_json(Path(args.output), payload)
    print(
        "Cached "
        f"{payload['available_venue_count']} venues with bookable dates, "
        f"{payload['slot_date_count']} venue/date summaries."
    )


if __name__ == "__main__":
    main()
