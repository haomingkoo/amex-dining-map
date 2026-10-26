"""Eligible days, blackouts and slot warnings in the guide replies."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

from app import tft_guide


NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.astimezone(tft_guide.SGT).date()
BLACKOUT = TODAY + timedelta(days=10)
# A Friday at least a few days out, so the dinner date is in range.
FRIDAY = TODAY + timedelta(days=(4 - TODAY.weekday()) % 7 + 7)


def _catalog() -> dict:
    venue = {
        "id": "tft-colony",
        "name": "Colony",
        "address": "7 Raffles Avenue",
        "category": "buffet",
        "aliases": [],
        "menus": {"default": {"status": "buffet_no_menu_expected"}},
        "eligibility": {
            "published_days": None,
            "terms_current": True,
            "observed_meals": [
                {"meal": "Lunch", "dates_seen": 77, "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
                 "days_label": "Mon–Sat", "rare_days": [], "never_days": ["Sun"],
                 "first_time": "12:30", "last_time": "13:30"},
                {"meal": "Dinner", "dates_seen": 65, "days": ["Mon", "Tue", "Wed", "Thu", "Sun"],
                 "days_label": "Sun–Thu", "rare_days": [], "never_days": ["Fri", "Sat"]},
            ],
            "merchant_blackouts": ["Easter Sunday", "F1 weekend (dates not given)"],
            "blackout_dates": [{"date": BLACKOUT.isoformat(), "reason": "Eve of Deepavali"}],
        },
    }
    return {
        "official_url": "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/",
        "roster_checked_at": NOW.isoformat(),
        "menu_source": {"checked_at": NOW.isoformat(), "review_required": False, "review_queue_count": 0},
        "eligibility_source": {"terms_current": True, "observed_since": "2026-08-18"},
        "slot_source": {
            "url": "https://amex-explorer.kooexperience.com/data/table-for-two-slots.json",
            "project": "AMEXPlatSG",
            "stale_after_minutes": 30,
        },
        "venues": [venue],
    }


def test_venue_reply_shows_days_meals_and_blackouts():
    answer = tft_guide.handle_message("/venue Colony", _catalog(), NOW)

    assert answer.startswith("Colony\n\nWhen Table for Two applies")
    assert "Days and meals: Not published. Check before booking." in answer
    assert "since 18 Aug 2026:" in answer
    assert "• Lunch: Mon–Sat, seatings 12:30pm–1:30pm" in answer
    assert "• Dinner: Sun–Thu" in answer
    assert "public holidays and their eves, plus Easter Sunday, F1 weekend (dates not given)." in answer
    assert f"({'Eve of Deepavali'})" in answer
    assert "—" not in answer.split("\n\n")[1]


def test_stale_terms_say_so_instead_of_listing_dates():
    catalog = _catalog()
    catalog["eligibility_source"]["terms_current"] = False
    catalog["venues"][0]["eligibility"]["terms_current"] = False
    answer = tft_guide.handle_message("/venue Colony", catalog, NOW)
    assert "terms changed since our last review" in answer
    assert "Eve of Deepavali" not in answer


def test_unsafe_eligibility_values_are_dropped():
    catalog = _catalog()
    meal = catalog["venues"][0]["eligibility"]["observed_meals"][0]
    meal["days_label"] = "Mon\nhttps://attacker.example"
    catalog["venues"][0]["eligibility"]["blackout_dates"][0]["reason"] = "x\ny"
    answer = tft_guide.handle_message("/venue Colony", catalog, NOW)
    assert "attacker.example" not in answer
    assert "Lunch:" not in answer


def _snapshot(slots: list[dict], meal: str) -> dict:
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": NOW.isoformat(),
        "venues": [{
            "id": "tft-colony",
            "project": "AMEXPlatSG",
            "status": "live_available",
            "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "meals": [{"meal": meal, "status": "available", "slots": slots}],
        }],
    }


def test_slots_flag_blackout_days_and_unusual_days():
    slots = [
        {"date": BLACKOUT.isoformat(), "time": "18:00", "max_seats": 2},
        {"date": FRIDAY.isoformat(), "time": "18:00", "max_seats": 2},
    ]
    end = max(BLACKOUT, FRIDAY).isoformat()
    answer = tft_guide.handle_message(
        f"/slots Colony | 2 | dinner | {TODAY.isoformat()}..{end}",
        _catalog(),
        NOW,
        slot_loader=lambda: _snapshot(slots, "Dinner"),
    )
    lines = {line for line in answer.splitlines() if line.startswith("• ")}
    blackout_line = next(line for line in lines if f"{BLACKOUT.day} {BLACKOUT:%b}" in line)
    friday_line = next(line for line in lines if f"{FRIDAY.day} {FRIDAY:%b}" in line)
    if BLACKOUT != FRIDAY:
        assert "Blackout day in the Amex terms (Eve of Deepavali)" in blackout_line
        assert "Not a day this venue usually offers Table for Two" in friday_line


def test_slots_without_eligibility_data_are_unflagged():
    catalog = copy.deepcopy(_catalog())
    del catalog["venues"][0]["eligibility"]
    slots = [{"date": FRIDAY.isoformat(), "time": "18:00", "max_seats": 2}]
    answer = tft_guide.handle_message(
        f"/slots Colony | 2 | dinner | {FRIDAY.isoformat()}",
        catalog,
        NOW,
        slot_loader=lambda: _snapshot(slots, "Dinner"),
    )
    assert "Open tables" in answer
    assert "Blackout" not in answer and "usually offers" not in answer


def test_venue_reply_leads_with_the_verdict():
    catalog = _catalog()
    catalog["venues"][0]["verdict"] = {
        "line": "Good value: extra diners pay S$128++ a head for this set, more than the usual S$100++.",
        "facts": ["Each of you gets a full set.", "bad\nfact"],
    }
    answer = tft_guide.handle_message("/venue Colony", catalog, NOW)
    assert answer.startswith("Colony\nGood value: extra diners pay S$128++")
    assert "• Each of you gets a full set." in answer
    assert "bad\nfact" not in answer
