#!/usr/bin/env python3
"""Small self-check for Pocket Concierge availability aggregation."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrape_pocket_availability import summarize_slots  # noqa: E402


def main() -> None:
    summary = summarize_slots([
        {
            "id": "slot-1",
            "startTime": "2026-06-30T18:00:00+09:00",
            "seatingType": "COUNTER",
            "minPartySize": 1,
            "maxPartySize": 2,
            "course": {"serviceType": "DINNER"},
        },
        {
            "id": "slot-2",
            "startTime": "2026-06-30T19:00:00+09:00",
            "seatingType": "TABLE",
            "minPartySize": 4,
            "maxPartySize": 6,
            "course": {"serviceType": "DINNER"},
        },
        {
            "startTime": "2026-06-30T20:00:00+09:00",
            "minPartySize": 1,
            "maxPartySize": 8,
            "course": {"serviceType": "DINNER"},
        },
    ])
    day = summary["2026-06-30"]
    assert day["times"] == ["18:00", "19:00"]
    assert day["sessions"] == ["DINNER"]
    assert day["party_ranges"] == [[1, 2], [4, 6]]
    assert day["seating"] == ["COUNTER", "TABLE"]
    assert day["min_party_size"] == 1
    assert day["max_party_size"] == 6
    assert day["slot_count"] == 2


if __name__ == "__main__":
    main()
