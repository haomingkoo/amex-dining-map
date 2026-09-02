#!/usr/bin/env python3
"""Losslessly merge two concurrently produced public update ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts import source_change_alert
except ModuleNotFoundError:
    import source_change_alert


REVIEW_FIELDS = {
    "status",
    "reviewed_at",
    "review_note",
    "retracted_at",
    "retraction_note",
    "corrected_by",
    "corrects",
}
DELIVERY_FIELDS = {"owner_delivery_state", "owner_delivery_recorded_at"}


def _review_rank(event: dict) -> tuple[int, int, str]:
    return (
        int(bool(event.get("retracted_at"))),
        int(bool(event.get("reviewed_at"))),
        str(event.get("retracted_at") or event.get("reviewed_at") or ""),
    )


def _merge_event(left: dict, right: dict) -> dict:
    merged = dict(left)
    for key in (set(left) | set(right)) - REVIEW_FIELDS - DELIVERY_FIELDS:
        old = left.get(key)
        new = right.get(key)
        if old == new or new is None:
            continue
        if old is None:
            merged[key] = new
            continue
        raise ValueError(f"conflicting immutable update event {left.get('id')}: {key}")
    review_winner = right if _review_rank(right) > _review_rank(left) else left
    for key in REVIEW_FIELDS:
        if key in review_winner:
            merged[key] = review_winner[key]
    delivery_winner = max(
        (left, right), key=lambda event: str(event.get("owner_delivery_recorded_at") or "")
    )
    for key in DELIVERY_FIELDS:
        if key in delivery_winner:
            merged[key] = delivery_winner[key]
    return merged


def merge_ledgers(left: dict, right: dict) -> dict:
    if left.get("schema_version") != 1 or right.get("schema_version") != 1:
        raise ValueError("update ledger schema_version must be 1")
    events: dict[str, dict] = {}
    for event in [*(left.get("updates") or []), *(right.get("updates") or [])]:
        event_id = str(event.get("id") or "")
        if not event_id:
            raise ValueError("update event has no ID")
        events[event_id] = (
            _merge_event(events[event_id], event) if event_id in events else dict(event)
        )
    ordered = sorted(
        events.values(), key=lambda event: (event.get("detected_at") or "", event["id"]), reverse=True
    )
    return {
        "schema_version": 1,
        "updated_at": max(str(left.get("updated_at") or ""), str(right.get("updated_at") or "")),
        "updates": ordered,
        "identity_state": source_change_alert.rebuild_identity_state(ordered),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    merged = merge_ledgers(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    print(f"Merged {len(merged['updates'])} update events without loss.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
