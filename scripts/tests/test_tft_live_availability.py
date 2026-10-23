from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.send_table_for_two_alerts import Subscription, matching_slots
from scripts.tft_live_availability import overlay_live_availability
from scripts.track_table_for_two_releases import append_current


NOW = datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc)
FRESH = "2026-10-23T01:55:00Z"


def roster() -> dict:
    return {
        "last_verified_at": "2026-10-22T22:00:00Z",
        "availability_source": {"project": "AMEXPlatSG", "api_base": "https://api.diningcity.asia/public"},
        "venues": [
            {
                "id": "tft-a",
                "name": "Alpha",
                "availability": {
                    "project": "AMEXPlatSG",
                    "status": "live_available",
                    "checked_at": "2026-10-22T22:00:00Z",
                    "meals": [{"meal": "Dinner", "status": "available", "slots": [{"date": "2026-11-01", "time": "19:00", "max_seats": 2}]}],
                },
            },
            {"id": "tft-b", "name": "Bravo", "availability": {"status": "live_no_seats", "meals": []}},
        ],
    }


def live_venue(venue_id: str, checked_at: str | None = FRESH, status: str = "live_available") -> dict:
    meals = [{"meal": "Lunch", "status": "available", "slots": [{"date": "2026-11-05", "time": "12:00", "max_seats": 4}]}]
    return {"id": venue_id, "project": "AMEXPlatSG", "status": status, "checked_at": checked_at, "meals": meals if status == "live_available" else []}


def snapshot(*venues: dict, generated_at: str = FRESH) -> dict:
    return {"schema_version": 1, "source_project": "AMEXPlatSG", "generated_at": generated_at, "venues": list(venues)}


def subscription(**overrides) -> Subscription:
    values = dict(email="a@example.com", name="", party_size=2, dates=(), date_start="", date_end="", sessions=(), venues=(), unsubscribe_url="", source_label="test")
    values.update(overrides)
    return Subscription(**values)


def test_live_slots_replace_committed_availability_for_alert_matching() -> None:
    payload = overlay_live_availability(roster(), snapshot(live_venue("tft-a")), NOW)

    matches = matching_slots(subscription(), payload["venues"])

    assert [(m["venue_name"], m["date"], m["time"], m["meal"]) for m in matches] == [("Alpha", "2026-11-05", "12:00", "Lunch")]


def test_venue_missing_from_snapshot_does_not_keep_committed_slots() -> None:
    payload = overlay_live_availability(roster(), snapshot(live_venue("tft-b")), NOW)

    alpha = payload["venues"][0]["availability"]

    assert (alpha["status"], alpha["meals"]) == ("unknown", [])


def test_retained_venue_older_than_the_limit_is_unknown() -> None:
    payload = overlay_live_availability(roster(), snapshot(live_venue("tft-a", checked_at="2026-10-23T01:00:00Z")), NOW)

    assert payload["venues"][0]["availability"]["status"] == "unknown"


def test_stale_snapshot_fails_loudly() -> None:
    with pytest.raises(ValueError, match="stale"):
        overlay_live_availability(roster(), snapshot(live_venue("tft-a"), generated_at="2026-10-23T01:00:00Z"), NOW)


def test_wrong_project_snapshot_is_rejected() -> None:
    bad = snapshot(live_venue("tft-a"))
    bad["source_project"] = "OTHER"

    with pytest.raises(ValueError, match="project"):
        overlay_live_availability(roster(), bad, NOW)


def test_release_tracking_observes_live_dates_at_snapshot_time() -> None:
    payload = overlay_live_availability(roster(), snapshot(live_venue("tft-a")), NOW)
    history: dict = {"schema_version": 1, "source_project": "AMEXPlatSG", "observations": []}

    added = append_current(payload, history)

    assert added == 1
    assert history["observations"][0]["slot_date"] == "2026-11-05"
    assert history["observations"][0]["first_seen_at"] == "2026-10-23T01:55:00Z"


def test_release_history_is_rewritten_only_when_a_date_is_new(tmp_path, monkeypatch) -> None:
    import json
    import sys

    from scripts import track_table_for_two_releases

    data = tmp_path / "live.json"
    output = tmp_path / "history.json"
    data.write_text(json.dumps(overlay_live_availability(roster(), snapshot(live_venue("tft-a")), NOW)))
    monkeypatch.setattr(sys, "argv", ["track", "--data", str(data), "--output", str(output)])
    track_table_for_two_releases.main()
    first = output.read_text()
    later = overlay_live_availability(roster(), snapshot(live_venue("tft-a", checked_at="2026-10-23T01:58:00Z"), generated_at="2026-10-23T01:58:00Z"), NOW)
    data.write_text(json.dumps(later))

    track_table_for_two_releases.main()

    assert output.read_text() == first
