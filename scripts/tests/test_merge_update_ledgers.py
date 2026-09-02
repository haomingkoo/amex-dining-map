from scripts import merge_update_ledgers


def event(event_id: str, **extra):
    return {
        "id": event_id,
        "stream_id": f"stream-{event_id}",
        "transition_id": f"transition-{event_id}",
        "occurrence": 1,
        "detected_at": "2026-09-03T00:00:00Z",
        "status": "review_required",
        "kind": "source_updated",
        **extra,
    }


def ledger(*events):
    return {"schema_version": 1, "updated_at": "2026-09-03T00:00:00Z", "updates": list(events)}


def test_merge_preserves_events_from_both_concurrent_writers():
    merged = merge_update_ledgers.merge_ledgers(ledger(event("left-id")), ledger(event("right-id")))

    assert {item["id"] for item in merged["updates"]} == {"left-id", "right-id"}
    assert set(merged["identity_state"]["streams"]) == {"stream-left-id", "stream-right-id"}


def test_merge_keeps_human_review_and_latest_delivery_receipt():
    reviewed = event(
        "shared-id",
        status="published",
        reviewed_at="2026-09-03T01:00:00Z",
        review_note="approved",
        owner_delivery_state="sent",
        owner_delivery_recorded_at="2026-09-03T01:01:00Z",
    )
    stale = event("shared-id")

    merged = merge_update_ledgers.merge_ledgers(ledger(reviewed), ledger(stale))["updates"][0]

    assert merged["status"] == "published"
    assert merged["review_note"] == "approved"
    assert merged["owner_delivery_state"] == "sent"


def test_merge_rejects_conflicting_immutable_event_content():
    left = event("shared-id", subject="Original")
    right = event("shared-id", subject="Different")

    try:
        merge_update_ledgers.merge_ledgers(ledger(left), ledger(right))
    except ValueError as exc:
        assert "conflicting immutable update event" in str(exc)
    else:
        raise AssertionError("immutable conflict was not rejected")
