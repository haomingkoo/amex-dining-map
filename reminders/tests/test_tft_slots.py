from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import tft_guide, tft_slot_source, tft_slots


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)


def catalog() -> dict:
    return copy.deepcopy(tft_guide.load_catalog())


def snapshot() -> dict:
    payload = json.loads((ROOT / "data" / "table-for-two-slots.json").read_text())
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["checked_at"] = (NOW - timedelta(minutes=10)).isoformat()
    return payload


def answer(command: str, payload: dict | None = None) -> str:
    return tft_guide.handle_message(
        command,
        catalog(),
        NOW,
        slot_loader=lambda: payload or snapshot(),
    )


def test_vue_filters_party_meal_date_and_preferred_time_together():
    result = answer("/slots VUE | 2 | dinner | 2026-10-29 | 19:00")

    assert "Observed matching AMEXPlatSG slots" in result
    for value in ("18:00", "18:30", "19:00", "19:30", "20:00"):
        assert f"2026-10-29 {value}" in result
    assert "2 pax, Dinner, 2026-10-29, within 60 minutes of 19:00 SGT" in result
    assert "checked 30 Aug, 10:50 SGT" in result
    assert "Booking and voucher redemption remain in the Amex Experiences App" in result
    assert (
        "#/table-for-two?venue=tft-vue&party=2&meal=dinner&date=2026-10-29&time=19%3A00"
        in result
    )


@pytest.mark.parametrize(
    "command",
    [
        "/slots VUE | 3 | dinner | 2026-10-29",
        "/slots VUE | 2 | lunch | 2026-10-29",
        "/slots VUE | 2 | dinner | 2026-10-30",
        "/slots VUE | 2 | dinner | 2026-10-29 | 16:59",
    ],
)
def test_every_slot_filter_can_remove_nonmatching_observations(command: str):
    result = answer(command)

    assert "No matching slot was observed" in result
    assert "sold out" in result
    assert "Observed matching AMEXPlatSG slots" not in result


def test_generic_diningcity_project_is_excluded():
    payload = snapshot()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["project"] = "GenericDiningCity"

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert "no verifiable AMEXPlatSG slot snapshot" in result
    assert "2026-10-29 19:00" not in result


def test_unknown_status_is_unverifiable_not_fresh_empty_coverage():
    payload = snapshot()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["status"] = "unknown"
    vue["meals"] = []

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert "no verifiable AMEXPlatSG slot snapshot" in result
    assert "No matching slot was observed" not in result
    assert "1 unverifiable" in result


def test_any_search_discloses_catalog_venues_missing_from_snapshot():
    payload = snapshot()
    payload["venues"] = [
        venue for venue in payload["venues"] if venue["id"] == "tft-vue"
    ]

    result = answer("/slots any | 2 | dinner | weekend", payload)

    missing = len(catalog()["venues"]) - 1
    assert f"{missing} unverifiable" in result


def test_per_venue_staleness_overrides_recent_top_level_generation_time():
    payload = snapshot()
    payload["generated_at"] = NOW.isoformat()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["checked_at"] = (NOW - timedelta(minutes=31)).isoformat()

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert "older than 30 minutes" in result
    assert "current availability cannot be determined" in result
    assert "Observed matching AMEXPlatSG slots" not in result


def test_weekend_any_uses_transparent_next_30_day_defaults():
    payload = snapshot()
    venue = next(item for item in payload["venues"] if item["id"] == "tft-colony")
    venue["checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
    venue["project"] = "AMEXPlatSG"
    venue["status"] = "live_available"
    venue["meals"] = [
        {
            "meal": "Dinner",
            "status": "available",
            "slots": [
                {"date": "2026-09-05", "time": "19:00", "max_seats": 2},
                {"date": "2026-09-07", "time": "19:00", "max_seats": 2},
            ],
        }
    ]

    result = answer("/slots any | 2 | dinner | weekend", payload)

    assert "Colony — 2026-09-05 19:00" in result
    assert "2026-09-07" not in result
    assert "weekends in the next 30 days" in result
    assert (
        "Open filtered Table for Two: https://amex-explorer.kooexperience.com/"
        "#/table-for-two?party=2&meal=dinner&day=weekend"
        in result
    )


def test_conversational_weekend_query_defaults_transparently_and_checks_both_meals():
    payload = snapshot()
    for venue_id, meal, slot_date in (
        ("tft-vue", "Dinner", "2026-09-05"),
        ("tft-colony", "Lunch", "2026-09-06"),
    ):
        venue = next(item for item in payload["venues"] if item["id"] == venue_id)
        venue["checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
        venue["project"] = "AMEXPlatSG"
        venue["status"] = "live_available"
        venue["meals"] = [
            {
                "meal": meal,
                "status": "available",
                "slots": [{"date": slot_date, "time": "19:00", "max_seats": 2}],
            }
        ]
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return payload

    result = tft_guide.handle_message(
        "Which TFT venues have weekend slots?", catalog(), NOW, loader
    )

    assert "VUE — 2026-09-05 19:00, dinner" in result
    assert "Colony — 2026-09-06 19:00, lunch" in result
    assert "Filters: 2 pax, Lunch or Dinner, weekends in the next 30 days" in result
    assert calls == 1


def test_invalid_or_ambiguous_query_does_not_fetch_source():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return snapshot()

    invalid = tft_guide.handle_message("/slots VUE dinner", catalog(), NOW, loader)
    ambiguous_catalog = catalog()
    duplicate = copy.deepcopy(ambiguous_catalog["venues"][0])
    duplicate["id"] = "tft-duplicate"
    duplicate["aliases"] = ["VUE"]
    ambiguous_catalog["venues"].append(duplicate)
    ambiguous = tft_guide.handle_message(
        "/slots VUE | 2 | dinner | 2026-10-29",
        ambiguous_catalog,
        NOW,
        loader,
    )

    assert "Use /slots" in invalid
    assert "could not match" in ambiguous
    assert calls == 0


@pytest.mark.parametrize(
    "command",
    [
        "/slots VUE | 2 | dinner | 20261029 | 19:00",
        "/slots VUE | 2 | dinner | 2026-W44-4 | 19:00",
        "/slots VUE | 2 | dinner | 2026-10-29 | 19",
        "/slots VUE | 2 | dinner | 2026-10-29 | 1900",
        "/slots VUE | 2 | dinner | 2026-10-29 | 19:00:00",
    ],
)
def test_strict_date_and_time_formats_are_rejected_without_fetch(command: str):
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return snapshot()

    result = tft_guide.handle_message(command, catalog(), NOW, loader)

    assert "Use /slots" in result
    assert calls == 0


def test_source_failure_returns_one_bounded_nonclaim():
    def fail():
        raise tft_slot_source.SlotSourceUnavailable

    result = tft_guide.handle_message(
        "/slots VUE | 2 | dinner | 2026-10-29", catalog(), NOW, fail
    )

    assert "will not make an availability claim" in result
    assert "amex-explorer.kooexperience.com" in result
    assert len(result) <= tft_guide.MAX_REPLY_LENGTH


def test_slot_command_requires_a_token_boundary():
    result = answer("/slotsVUE | 2 | dinner | 2026-10-29")

    assert "Observed matching" not in result
    assert "http" not in result
