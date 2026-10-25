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
    vue["project"] = "AMEXPlatSG"
    vue["status"] = "live_available"
    vue["meals"] = [
        {
            "meal": "Dinner",
            "status": "available",
            "slots": [
                {"date": "2026-10-29", "time": value, "max_seats": 2}
                for value in ("18:00", "18:30", "19:00", "19:30", "20:00")
            ],
        }
    ]
    return payload


def other_venue(payload: dict) -> tuple[dict, str]:
    # The booking project drops and re-adds venues, so take a second venue from the
    # snapshot instead of naming one the roster may remove.
    names = {venue["id"]: venue["name"] for venue in catalog()["venues"]}
    return next(
        (venue, names[venue["id"]])
        for venue in payload["venues"]
        if venue["id"] != "tft-vue" and venue["id"] in names
    )


def answer(command: str, payload: dict | None = None) -> str:
    return tft_guide.handle_message(
        command,
        catalog(),
        NOW,
        slot_loader=lambda: payload or snapshot(),
    )


def test_vue_filters_party_meal_date_and_preferred_time_together():
    result = answer("/slots VUE | 2 | dinner | 2026-10-29 | 19:00")

    assert result.startswith("Open tables, dinner for 2 at VUE on Thu 29 Oct, around 7:00pm:")
    for value in ("6:00pm", "6:30pm", "7:00pm", "7:30pm", "8:00pm"):
        assert f"Thu 29 Oct {value} (up to 2 people)" in result
    assert f"Last checked 30 Aug, 10:50am. {tft_slots.SOURCE_NOTE}" in result
    for jargon in ("observ", "AMEXPlatSG", "cached", "Official TFT", "—", "Filters:"):
        assert jargon not in result
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

    assert result.startswith("No ")
    assert "Open tables," not in result
    assert tft_slots.SOURCE_NOTE in result


def test_generic_diningcity_project_is_excluded():
    payload = snapshot()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["project"] = "GenericDiningCity"

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert result.startswith("I do not have current times for VUE right now.")
    assert "7:00pm" not in result


def test_unknown_status_is_unverifiable_not_fresh_empty_coverage():
    payload = snapshot()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["status"] = "unknown"
    vue["meals"] = []

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert result.startswith("I do not have current times for VUE right now.")
    assert "Last checked" not in result


def test_any_search_discloses_catalog_venues_missing_from_snapshot():
    payload = snapshot()
    payload["venues"] = [
        venue for venue in payload["venues"] if venue["id"] == "tft-vue"
    ]

    result = answer("/slots any | 2 | dinner | weekend", payload)

    missing = len(catalog()["venues"]) - 1
    assert f"{missing} venues were left out because I do not have a recent check." in result


def test_per_venue_staleness_overrides_recent_top_level_generation_time():
    payload = snapshot()
    payload["generated_at"] = NOW.isoformat()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["checked_at"] = (NOW - timedelta(minutes=31)).isoformat()

    result = answer("/slots VUE | 2 | dinner | 2026-10-29", payload)

    assert result.startswith("I cannot see current times for VUE right now.")
    assert "The last check was 30 Aug, 10:29am, which is too old to rely on." in result
    assert "Open tables," not in result


def test_weekend_any_uses_transparent_next_62_day_defaults():
    payload = snapshot()
    venue, venue_name = other_venue(payload)
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

    assert result.startswith("Open tables, weekend dinners for 2 in the next 62 days:")
    assert f"• {venue_name}, Sat 5 Sep: 7:00pm (1 time)" in result
    assert "Mon 7 Sep" not in result
    assert (
        "Open in Amex Explorer: https://amex-explorer.kooexperience.com/"
        "#/table-for-two?party=2&meal=dinner&day=weekend"
        in result
    )


def test_conversational_weekend_query_defaults_transparently_and_checks_both_meals():
    payload = snapshot()
    lunch_venue, lunch_venue_name = other_venue(payload)
    for venue_id, meal, slot_date in (
        ("tft-vue", "Dinner", "2026-09-05"),
        (lunch_venue["id"], "Lunch", "2026-09-06"),
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

    assert "• VUE, Sat 5 Sep: dinner 7:00pm (1 time)" in result
    assert f"• {lunch_venue_name}, Sun 6 Sep: lunch 7:00pm (1 time)" in result
    assert result.startswith("Open tables, weekend lunch or dinner for 2 in the next 62 days:")
    assert calls == 1


def test_invalid_or_ambiguous_query_does_not_fetch_source():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return snapshot()

    invalid = tft_guide.handle_message("/slots VUE | 2", catalog(), NOW, loader)
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

    assert result.startswith(tft_slots.UNAVAILABLE)
    assert "amex-explorer.kooexperience.com" in result
    assert len(result) <= tft_guide.MAX_REPLY_LENGTH


def test_slot_command_requires_a_token_boundary():
    result = answer("/slotsVUE | 2 | dinner | 2026-10-29")

    assert "Open tables," not in result
    assert "http" not in result


def counting_loader(payload: dict | None = None) -> tuple[list[int], object]:
    calls = [0]

    def loader():
        calls[0] += 1
        return payload or snapshot()

    return calls, loader


@pytest.mark.parametrize(
    ("question", "venue_id"),
    [
        ("which dates is VUE available?", "tft-vue"),
        ("what dates does Park90 have?", "tft-park90"),
        ("When can I book VUE for dinner?", "tft-vue"),
        ("any dates for Kaya at The Standard lunch for 4?", "tft-kaya-at-the-standard"),
        ("any dates for Kaya lunch for 4?", "tft-kaya-at-the-standard"),
        ("which dates does VUE have in December?", "tft-vue"),
    ],
)
def test_natural_dates_question_runs_a_slot_lookup_for_that_venue(question, venue_id):
    calls, loader = counting_loader()

    result = tft_guide.handle_message(question, catalog(), NOW, loader)

    assert tft_slots.SOURCE_NOTE in result
    assert f"#/table-for-two?venue={venue_id}&" in result
    assert calls[0] == 1


@pytest.mark.parametrize(
    "question",
    ["when can I book Osteria Mozza for dinner?", "any dates for Odette lunch for 4?"],
)
def test_natural_dates_question_with_unknown_venue_does_not_guess(question):
    calls, loader = counting_loader()

    result = tft_guide.handle_message(question, catalog(), NOW, loader)

    assert result.startswith("I could not match that to one exact Table for Two venue.")
    assert calls[0] == 0


def test_natural_dates_question_with_ambiguous_venue_does_not_guess():
    ambiguous_catalog = catalog()
    duplicate = copy.deepcopy(ambiguous_catalog["venues"][0])
    duplicate["id"] = "tft-duplicate"
    duplicate["aliases"] = ["VUE"]
    ambiguous_catalog["venues"].append(duplicate)
    calls, loader = counting_loader()

    result = tft_guide.handle_message(
        "which dates is VUE available?", ambiguous_catalog, NOW, loader
    )

    assert "could not match that to one exact Table for Two venue" in result
    assert calls[0] == 0


def test_natural_dates_question_defaults_to_two_pax_both_meals_and_max_range():
    result = answer("which dates is VUE available?")

    assert result.startswith("Open tables, lunch or dinner for 2 at VUE in the next 62 days:")


@pytest.mark.parametrize(
    ("question", "filters"),
    [
        ("when can I book VUE for dinner?", "dinners for 2"),
        ("any dates for VUE lunch for 4?", "lunches for 4"),
        ("which dates is VUE available for 3 pax?", "lunch or dinner for 3"),
        ("what dates does VUE have for 5 people?", "lunch or dinner for 5"),
        ("any dates for VUE 6 people dinner", "dinners for 6"),
    ],
)
def test_natural_dates_modifiers_override_meal_and_party(question, filters):
    result = answer(question)

    assert f"{filters} at VUE in the next 62 days" in result


@pytest.mark.parametrize(
    "question", ["any dates for VUE for 11?", "which dates is VUE available for 0 pax?"]
)
def test_natural_dates_party_out_of_range_uses_existing_error(question):
    calls, loader = counting_loader()

    result = tft_guide.handle_message(question, catalog(), NOW, loader)

    assert result.startswith("Party size must be a whole number from 1 to 10.")
    assert calls[0] == 0


@pytest.mark.parametrize(
    ("question", "date_range"),
    [
        ("which dates does VUE have in October?", "from Thu 1 Oct to Sat 31 Oct:"),
        ("which dates does VUE have in August?", "from Sun 30 Aug to Mon 31 Aug."),
        ("which dates does VUE have in July?", "from Thu 1 Jul to Sat 31 Jul 2027."),
        ("any dates for VUE in february for dinner", "from Mon 1 Feb to Sun 28 Feb 2027."),
    ],
)
def test_natural_dates_month_limits_range_to_that_month(question, date_range):
    result = answer(question)

    assert f"at VUE {date_range}" in result


def test_natural_dates_month_returns_slots_inside_that_month():
    result = answer("which dates does VUE have in October for dinner?")

    assert "• Thu 29 Oct: 6:00pm–8:00pm (5 times)" in result


def test_natural_dates_rejects_bad_slot_source_metadata():
    bad_catalog = catalog()
    bad_catalog["slot_source"]["project"] = "OTHER"
    calls, loader = counting_loader()

    result = tft_guide.handle_message(
        "which dates is VUE available?", bad_catalog, NOW, loader
    )

    assert result == tft_slots.UNAVAILABLE
    assert calls[0] == 0


def test_natural_dates_source_failure_returns_bounded_nonclaim():
    def fail():
        raise tft_slot_source.SlotSourceUnavailable

    result = tft_guide.handle_message("which dates is VUE available?", catalog(), NOW, fail)

    assert result.startswith(tft_slots.UNAVAILABLE)
    assert len(result) <= tft_guide.MAX_REPLY_LENGTH


def test_natural_dates_answer_checks_snapshot_project_and_reply_length():
    payload = snapshot()
    payload["source_project"] = "OTHER"

    result = answer("which dates is VUE available?", payload)

    assert result == tft_slots.UNAVAILABLE
    assert len(result) <= tft_guide.MAX_REPLY_LENGTH


@pytest.mark.parametrize(
    "message", ["hello there", "where is VUE?", "dates", "which dates" + " x" * 200]
)
def test_unrelated_messages_do_not_trigger_a_slot_lookup(message):
    calls, loader = counting_loader()

    result = tft_guide.handle_message(message, catalog(), NOW, loader)

    assert tft_slots.SOURCE_NOTE not in result
    assert calls[0] == 0


def test_help_mentions_plain_english_dates_question():
    result = tft_guide.handle_message("/help", catalog(), NOW)

    assert "which dates is VUE available?" in result


def test_range_answer_groups_slots_into_dates_and_links_without_a_date():
    result = answer("which dates does VUE have in October?")

    assert result.startswith("Open tables, lunch or dinner for 2 at VUE from Thu 1 Oct to Sat 31 Oct:")
    assert "• Thu 29 Oct: dinner 6:00pm–8:00pm (5 times)" in result
    assert "&date=" not in result


def test_single_day_answer_keeps_slot_rows_and_dated_link():
    result = answer("/slots VUE | 2 | dinner | 2026-10-29")

    assert "• Thu 29 Oct 6:00pm (up to 2 people)" in result
    assert "&date=2026-10-29" in result


@pytest.mark.parametrize(
    "command",
    ["/slots VUE dinner weekend", "/slots VUE | 2 | dinner | weekend", "/slots VUE ｜ 2 ｜ dinner ｜ weekend"],
)
def test_slots_accepts_plain_words_and_lookalike_pipes(command: str) -> None:
    result = answer(command)

    assert "Use /slots" not in result
    assert "weekend dinners for 2 at VUE in the next 62 days" in result


def test_slots_plain_venue_only_searches_that_venue() -> None:
    result = answer("/slots VUE")

    assert tft_slots.SOURCE_NOTE in result
    assert "venue=tft-vue" in result


def test_exact_slots_range_allows_62_days_and_rejects_63():
    allowed = tft_slots.parse_request("/slots VUE | 2 | dinner | 2026-08-30..2026-10-30", NOW)
    too_long = tft_slots.parse_request("/slots VUE | 2 | dinner | 2026-08-30..2026-10-31", NOW)

    assert isinstance(allowed, tft_slots.SlotRequest)
    assert too_long == "Date ranges are limited to 62 days per lookup."


def vue_with(meals: list[dict], status: str = "live_available") -> dict:
    payload = snapshot()
    vue = next(venue for venue in payload["venues"] if venue["id"] == "tft-vue")
    vue["status"] = status
    vue["meals"] = meals
    return payload


def meal(name: str, dates: list[str], at: str) -> dict:
    slots = [{"date": value, "time": at, "max_seats": 2} for value in dates]
    return {"meal": name, "status": "available", "slots": slots}


def body_lines(result: str) -> list[str]:
    return result.split("\n\n")[0].splitlines()


def test_empty_weekend_offers_weekday_dinners_at_the_same_venue():
    payload = vue_with([meal("Dinner", ["2026-09-01", "2026-09-03", "2026-09-15"], "18:00")])

    result = answer("/slots VUE | 2 | dinner | weekend", payload)

    assert body_lines(result) == [
        "No weekend dinners for 2 at VUE in the next 62 days.",
        "Weekday dinners are open on 3 days, 1–15 Sep. Earliest: Tue 1 Sep, 6:00pm.",
    ]
    assert result.count("https://") == 1
    assert result.endswith("Open in Amex Explorer: https://amex-explorer.kooexperience.com/#/table-for-two?venue=tft-vue&party=2&meal=dinner")


def test_empty_meal_offers_the_other_meal_at_the_same_venue():
    payload = vue_with([meal("Lunch", ["2026-09-05", "2026-09-12"], "12:00")])

    result = answer("/slots VUE dinner weekend", payload)

    assert body_lines(result) == [
        "No weekend dinners for 2 at VUE in the next 62 days.",
        "No dinners on other days either.",
        "Lunches are open on 2 days, 5–12 Sep. Earliest: Sat 5 Sep, 12:00pm.",
    ]
    assert result.endswith("https://amex-explorer.kooexperience.com/#/table-for-two?venue=tft-vue&party=2&meal=lunch")


def test_fully_booked_venue_says_nothing_is_open_in_the_window():
    payload = vue_with([], status="live_no_seats")

    result = answer("/slots VUE | 2 | dinner | weekend", payload)

    assert body_lines(result) == [
        "No weekend dinners for 2 at VUE in the next 62 days.",
        "Nothing else is open for 2 at VUE in the next 62 days.",
    ]
    assert f"Last checked 30 Aug, 10:50am. {tft_slots.SOURCE_NOTE}" in result
    assert result.endswith("https://amex-explorer.kooexperience.com/#/table-for-two?venue=tft-vue&party=2&meal=dinner&day=weekend")


def test_alternative_link_drops_the_date_and_time_that_found_nothing():
    result = answer("/slots VUE | 2 | dinner | 2026-10-30 | 19:00")

    assert "Dinners are open on one day: Thu 29 Oct, from 6:00pm." in result
    assert result.endswith("https://amex-explorer.kooexperience.com/#/table-for-two?venue=tft-vue&party=2&meal=dinner")


def test_alternatives_respect_party_size():
    payload = vue_with([meal("Dinner", ["2026-09-01"], "18:00")])

    result = answer("/slots VUE | 4 | dinner | weekend", payload)

    assert "Weekday" not in result
    assert "Nothing else is open for 4 at VUE" in result
