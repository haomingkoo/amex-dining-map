#!/usr/bin/env python3
"""Apply one hash-bound Love Dining listing review (added, removed or changed records)."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

try:
    from scripts import source_change_alert
    from scripts.apply_love_dining_review import _load, _records_digest
except ModuleNotFoundError:
    import source_change_alert
    from apply_love_dining_review import _load, _records_digest


DEFAULT_DATA = Path("data/love-dining.json")
DEFAULT_META = Path("data/love-dining-source.json")
DEFAULT_UPDATES = Path("data/updates.json")
LISTING_REASON = "Official Love Dining listing content changed"
RECORD_EVENT_KINDS = {"added", "removed", "details_updated"}


def _love_event(events: dict, event_id: str, kinds: set[str]) -> dict:
    event = events.get(event_id)
    if (
        event is None
        or event.get("program_id") != "love-dining"
        or event.get("kind") not in kinds
        or event.get("status") not in {"review_required", "rejected", "published"}
    ):
        raise ValueError(f"reviewed event does not match the ledger: {event_id}")
    return event


def apply_listing_review(manifest: dict, records: list[dict], meta: dict, ledger: dict):
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "listing_review":
        raise ValueError("invalid Love Dining listing review manifest")
    digest = _records_digest(records)
    if digest != manifest.get("records_sha256") or meta.get("records_sha256") != digest:
        raise ValueError("current Love Dining record hash does not match the review")
    if meta.get("reviewed_records_sha256") == digest:
        return copy.deepcopy(meta), copy.deepcopy(ledger)
    if meta.get("reviewed_records_sha256") != manifest.get("previous_reviewed_records_sha256"):
        raise ValueError("listing review lineage does not match reviewed metadata")
    reviewed_at = manifest.get("reviewed_at")
    review_note = manifest.get("review_note")
    if not isinstance(reviewed_at, str) or not isinstance(review_note, str) or not review_note:
        raise ValueError("review timestamp and note are required")

    updated_ledger = copy.deepcopy(ledger)
    events = {event.get("id"): event for event in updated_ledger.get("updates", [])}
    for event_id in manifest.get("published_event_ids") or []:
        event = _love_event(events, event_id, RECORD_EVENT_KINDS)
        event.update(status="published", reviewed_at=reviewed_at, review_note=review_note)
    for event_id in manifest.get("rejected_source_event_ids") or []:
        event = _love_event(events, event_id, {"source_updated"})
        event.update(status="rejected", reviewed_at=reviewed_at)
        event.setdefault("review_note", "Superseded by the reviewed record events.")
    pending = [
        event.get("id")
        for event in updated_ledger.get("updates", [])
        if event.get("program_id") == "love-dining" and event.get("status") == "review_required"
    ]
    if pending:
        raise ValueError(f"listing review leaves Love Dining events unreviewed: {pending}")

    updated_meta = copy.deepcopy(meta)
    updated_meta["reviewed_records_sha256"] = digest
    updated_meta["records_reviewed_at"] = reviewed_at
    updated_meta["major_change_reasons"] = [
        reason for reason in meta.get("major_change_reasons") or [] if reason != LISTING_REASON
    ]
    updated_meta["manual_review_required"] = bool(updated_meta["major_change_reasons"])
    updated_ledger["updated_at"] = reviewed_at
    return updated_meta, updated_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--updates", type=Path, default=DEFAULT_UPDATES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    with source_change_alert._ledger_lock(args.updates):
        meta = _load(args.meta)
        ledger = _load(args.updates)
        updated_meta, updated_ledger = apply_listing_review(
            _load(args.manifest), _load(args.data), meta, ledger
        )
        if args.check:
            if updated_meta != meta or updated_ledger != ledger:
                raise SystemExit("Love Dining listing review has not been applied")
            print("Love Dining listing review is current")
            return 0
        source_change_alert._atomic_write_json(args.updates, updated_ledger)
        source_change_alert._atomic_write_json(args.meta, updated_meta)
    print("Applied Love Dining listing review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
