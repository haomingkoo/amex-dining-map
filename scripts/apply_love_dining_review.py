#!/usr/bin/env python3
"""Apply one hash-bound Love Dining record correction review."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

try:
    from scripts import scrape_love_dining, source_change_alert
except ModuleNotFoundError:
    import scrape_love_dining
    import source_change_alert


DEFAULT_MANIFEST = Path(
    "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json"
)
DEFAULT_DATA = Path("data/love-dining.json")
DEFAULT_META = Path("data/love-dining-source.json")
DEFAULT_UPDATES = Path("data/updates.json")
OFFICIAL_URL = (
    "https://www.americanexpress.com/sg/benefits/love-dining/"
    "love-dining-hotels.html"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _records_digest(records: list[dict]) -> str:
    official = [
        scrape_love_dining.official_record_projection(record) for record in records
    ]
    raw = json.dumps(official, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def apply_review(manifest: dict, records: list[dict], meta: dict, ledger: dict):
    if manifest.get("schema_version") != 1 or manifest.get("source_url") != OFFICIAL_URL:
        raise ValueError("invalid Love Dining correction manifest")
    mappings = manifest.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 6:
        raise ValueError("correction manifest must contain exactly six mappings")
    digest = _records_digest(records)
    if (
        digest != manifest.get("records_sha256")
        or meta.get("records_sha256") != digest
    ):
        raise ValueError("current Love Dining record hash does not match the review")
    reviewed_at = manifest.get("reviewed_at")
    review_note = manifest.get("review_note")
    if not isinstance(reviewed_at, str) or not isinstance(review_note, str):
        raise ValueError("review timestamp and note are required")

    records_by_id = {record.get("id"): record for record in records}
    updated_meta = copy.deepcopy(meta)
    updated_ledger = copy.deepcopy(ledger)
    superseded_ids = {
        mapping.get("superseded_correction_event_id") for mapping in mappings
    } - {None}
    updated_ledger["updates"] = [
        event
        for event in updated_ledger.get("updates", [])
        if event.get("id") not in superseded_ids
    ]
    updated_events = {event.get("id"): event for event in updated_ledger.get("updates", [])}

    for mapping in mappings:
        record = records_by_id.get(mapping.get("new_id"))
        if (
            record is None
            or record.get("name") != mapping.get("name")
            or record.get("address") != mapping.get("address")
            or record.get("hotel") != mapping.get("after_hotel")
            or mapping.get("old_id") in records_by_id
        ):
            raise ValueError(f"record does not match reviewed correction: {mapping.get('name')}")
        event_id = mapping.get("correction_event_id")
        event = updated_events.get(event_id)
        expected_change = {
            "field": "Hotel",
            "before": mapping.get("before_hotel"),
            "after": mapping.get("after_hotel"),
        }
        expected_after = source_change_alert.public_record_fields(record)
        expected_before = dict(expected_after)
        expected_before["Hotel"] = mapping.get("before_hotel")
        expected_stream = source_change_alert.update_stream_id(
            "love-dining", f"record:{mapping.get('new_id')}"
        )
        transition_id = event.get("transition_id") if event else None
        occurrence = event.get("occurrence") if event else None
        identity_is_valid = (
            isinstance(transition_id, str)
            and isinstance(occurrence, int)
            and not isinstance(occurrence, bool)
            and occurrence > 0
            and event.get("id")
            == source_change_alert._occurrence_id(
                expected_stream, transition_id, occurrence
            )
        )
        if (
            event is None
            or event.get("program") != "Love Dining"
            or event.get("program_id") != "love-dining"
            or event.get("route") != "#/love-dining"
            or event.get("kind") != "correction"
            or event.get("subject") != f"{mapping.get('name')} / Singapore"
            or event.get("status") not in {"review_required", "published"}
            or event.get("changes") != [expected_change]
            or event.get("before")
            != {"state": "listed", "fields": expected_before}
            or event.get("after")
            != {"state": "listed", "fields": expected_after}
            or event.get("source_url") != OFFICIAL_URL
            or event.get("stream_id") != expected_stream
            or transition_id != source_change_alert.update_event_id(event)
            or not identity_is_valid
        ):
            raise ValueError(f"correction event does not match review: {event_id}")
        event["status"] = "published"
        event["reviewed_at"] = reviewed_at
        event["review_note"] = review_note
        retracts_id = mapping.get("retracts_event_id")
        event["corrects"] = [retracts_id] if retracts_id else []
        if retracts_id:
            original = updated_events.get(retracts_id)
            if original is None or original.get("status") not in {"published", "retracted"}:
                raise ValueError(f"original event cannot be retracted: {retracts_id}")
            original["status"] = "retracted"
            original["retracted_at"] = reviewed_at
            original["retraction_note"] = (
                "Hotel attribution was incorrect; superseded by a reviewed correction."
            )
            original["corrected_by"] = event_id

    source_event = updated_events.get(manifest.get("source_event_id"))
    if source_event is None or source_event.get("status") not in {
        "review_required",
        "rejected",
    }:
        raise ValueError("source hash event is missing or already published")
    source_event["status"] = "rejected"
    source_event["reviewed_at"] = reviewed_at
    source_event["review_note"] = (
        "Superseded by six reviewed Hotel before-and-after correction events."
    )

    updated_meta["reviewed_records_sha256"] = manifest["records_sha256"]
    updated_meta["records_reviewed_at"] = reviewed_at
    updated_meta["major_change_reasons"] = [
        reason
        for reason in updated_meta.get("major_change_reasons", [])
        if reason != "Official Love Dining listing content changed"
    ]
    updated_meta["manual_review_required"] = bool(
        updated_meta["major_change_reasons"]
    )
    updated_ledger["updated_at"] = reviewed_at
    updated_ledger["identity_state"] = source_change_alert.rebuild_identity_state(
        updated_ledger["updates"]
    )
    return updated_meta, updated_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--updates", type=Path, default=DEFAULT_UPDATES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    with source_change_alert._ledger_lock(args.updates):
        manifest = _load(args.manifest)
        records = _load(args.data)
        meta = _load(args.meta)
        ledger = _load(args.updates)
        updated_meta, updated_ledger = apply_review(manifest, records, meta, ledger)
        if args.check:
            if updated_meta != meta or updated_ledger != ledger:
                raise SystemExit("Love Dining correction review has not been applied")
            print("Love Dining correction review is current")
            return 0
        source_change_alert._atomic_write_json(args.updates, updated_ledger)
        source_change_alert._atomic_write_json(args.meta, updated_meta)
    print("Applied reviewed Love Dining hotel-attribution corrections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
