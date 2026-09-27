from __future__ import annotations

import pytest

from scripts import apply_love_dining_listing_review as listing_review
from scripts.apply_love_dining_review import _records_digest

RECORDS = [{"id": "love-a", "name": "A", "type": "restaurant"}]
OLD_DIGEST = "0" * 64


def case() -> tuple[dict, dict, dict]:
    digest = _records_digest(RECORDS)
    manifest = {
        "schema_version": 1,
        "kind": "listing_review",
        "previous_reviewed_records_sha256": OLD_DIGEST,
        "records_sha256": digest,
        "reviewed_at": "2026-09-27T05:30:00Z",
        "review_note": "Checked against the official page.",
        "published_event_ids": ["removed-b"],
        "rejected_source_event_ids": ["source"],
    }
    meta = {
        "records_sha256": digest,
        "reviewed_records_sha256": OLD_DIGEST,
        "major_change_reasons": [listing_review.LISTING_REASON],
    }
    ledger = {
        "updates": [
            {"id": "removed-b", "program_id": "love-dining", "kind": "removed", "status": "review_required"},
            {"id": "source", "program_id": "love-dining", "kind": "source_updated", "status": "review_required"},
        ]
    }
    return manifest, meta, ledger


def test_listing_review_publishes_events_and_clears_flag():
    manifest, meta, ledger = case()

    updated_meta, updated_ledger = listing_review.apply_listing_review(manifest, RECORDS, meta, ledger)

    assert updated_meta["manual_review_required"] is False
    assert updated_meta["reviewed_records_sha256"] == manifest["records_sha256"]
    assert [event["status"] for event in updated_ledger["updates"]] == ["published", "rejected"]


def test_listing_review_rejects_changed_records():
    manifest, meta, ledger = case()

    with pytest.raises(ValueError, match="record hash"):
        listing_review.apply_listing_review(manifest, RECORDS + [{"id": "love-c"}], meta, ledger)


def test_listing_review_refuses_to_leave_events_unreviewed():
    manifest, meta, ledger = case()
    manifest["published_event_ids"] = []

    with pytest.raises(ValueError, match="unreviewed"):
        listing_review.apply_listing_review(manifest, RECORDS, meta, ledger)
