#!/usr/bin/env python3
"""Local-only helper for Table for Two availability snapshots.

This intentionally does not reverse-engineer or store Amex app credentials. Use
it to merge manually captured app availability, or future local checks, into
data/table-for-two.json without committing user/session-specific app data.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_times(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/table-for-two.json")
    parser.add_argument("--venue-id", required=True)
    parser.add_argument("--meal", default="Lunch")
    parser.add_argument("--date", default="", help="Exact booking date as YYYY-MM-DD, when known")
    parser.add_argument("--date-label", default="", help="Human-readable date note when exact date is not known")
    parser.add_argument("--times", required=True, help="Comma-separated available times, e.g. 12:00,12:30")
    parser.add_argument("--seats", type=int, default=2)
    parser.add_argument("--captured-at", default=now_iso())
    parser.add_argument("--source", default="manual_app_capture")
    args = parser.parse_args()

    data_path = Path(args.data)
    payload = load_json(data_path)
    venues = payload.get("venues") or []
    venue = next((record for record in venues if record.get("id") == args.venue_id), None)
    if not venue:
        raise SystemExit(f"Unknown Table for Two venue id: {args.venue_id}")

    times = parse_times(args.times)
    status = "captured_available" if times else "captured_no_seats"
    venue["availability"] = {
        "status": status,
        "source": args.source,
        "captured_at": args.captured_at,
        "confidence": "manual_capture",
        "date": args.date or None,
        "date_label": args.date_label or args.date or "Date not specified",
        "summary": (
            f"At least {args.seats} Table for Two seats were captured for {args.meal} "
            f"{'on ' + args.date + ' ' if args.date else ''}at {', '.join(times)}."
            if times
            else f"No Table for Two seats were captured for {args.meal}."
        ),
        "meals": [
            {
                "meal": args.meal,
                "status": "available" if times else "no_seats",
                "seats": args.seats,
                "date": args.date or None,
                "date_label": args.date_label or args.date or "Date not specified",
                "times": times,
            }
        ],
        "notes": [
            "Manual or private local availability capture. Reconfirm in the Amex Experiences App before booking.",
        ],
    }
    payload["availability_last_checked_at"] = args.captured_at
    write_json(data_path, payload)
    print(f"Updated {venue.get('name')} availability: {venue['availability']['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
