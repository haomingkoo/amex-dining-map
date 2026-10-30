from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sync_plat_stay as MODULE

# pdftotext -layout excerpt of the October 2026 Plat Stay PDF, page 1.
PDF_TEXT = """ Participating        Current address            Eligible Room Type                Blackout Dates                       Reservation
 Properties                                                                        *Subject to Hotel's discretion       Email/Number

 Pan Pacific          10 Claymore Road,          Deluxe Room with a                •   2 – 13 October 2026              reserve.ppsor@panpa
 Orchard              Singapore 229540           complimentary bottle of wine,     •   18 – 19 November 2026            cific.com
 Singapore                                       inclusive of breakfast for two.   •   17 – 31 December 2026
                                                                                   •   5 – 13 February 2027
                                                 Eligible Card Members may
                                                 upgrade to the Club Room with a
                                                 complimentary champagne with a
                                                 S$100++ top-up.

                                                 Until 28 February 2027, enjoy a
                                                 S$100 nett credit for use at
                                                 Park90 Singapore.
 JW Marriott          30 Beach Road,             Studio Room                       •   8 – 11 October 2026              Reservations.Singapo
 Singapore South      Singapore 189763                                             •   31 December 2026                 re@jwmarriotthotels.c
 Beach                                           Room only, without breakfast.                                          om
                                                 Membership tier benefit is not
                                                 applicable.                                                            +65 6818 1888
Terms and Conditions
"""


def _parsed_blocks() -> dict:
    blocks = [MODULE.parse_block(block) for block in MODULE.split_property_blocks(PDF_TEXT)]
    return {block.name: block for block in blocks if block.name}


def test_split_property_blocks_continuation_after_blank_line_stays_with_property() -> None:
    blocks = _parsed_blocks()

    room = blocks["Pan Pacific Orchard Singapore"].eligible_room_type

    assert room.endswith("Until 28 February 2027, enjoy a S$100 nett credit for use at Park90 Singapore.")


def test_split_property_blocks_continuation_does_not_leak_into_next_property() -> None:
    blocks = _parsed_blocks()

    room = blocks["JW Marriott Singapore South Beach"].eligible_room_type

    assert "Park90" not in room


def test_breakfast_fields_singapore_room_with_breakfast_is_included() -> None:
    room = _parsed_blocks()["Pan Pacific Orchard Singapore"].eligible_room_type

    included, _ = MODULE.breakfast_fields("Singapore", room)

    assert included is True


def test_breakfast_fields_singapore_room_only_is_not_included() -> None:
    room = _parsed_blocks()["JW Marriott Singapore South Beach"].eligible_room_type

    included, _ = MODULE.breakfast_fields("Singapore", room)

    assert included is False


def test_collapse_blackout_items_subject_to_line_is_separate_note() -> None:
    items = MODULE.collapse_blackout_items(["• 31 December 2026", "Subject to hotel’s availability and", "confirmation"])

    assert items == ["• 31 December 2026", "Subject to hotel’s availability and confirmation"]


def test_yearless_range_is_annual_not_a_guessed_year() -> None:
    exact, note = MODULE.parse_blackout_item("• 7 November – 10 December")

    assert note is None
    assert exact == {
        "recurring": "annual",
        "start_month_day": "11-07",
        "end_month_day": "12-10",
        "label": "7 November - 10 December",
        "tentative": False,
    }


def test_yearless_same_month_and_new_year_ranges_parse() -> None:
    december, _ = MODULE.parse_blackout_item("• 27– 31 December")
    new_year, _ = MODULE.parse_blackout_item("28 December - 3 January")

    assert (december["start_month_day"], december["end_month_day"]) == ("12-27", "12-31")
    assert (new_year["start_month_day"], new_year["end_month_day"]) == ("12-28", "01-03")


def test_dated_range_keeps_its_stated_year() -> None:
    exact, _ = MODULE.parse_blackout_item("24 - 26 December 2027")

    assert (exact["start"], exact["end"]) == ("2027-12-24", "2027-12-26")
    assert "recurring" not in exact
    assert not hasattr(MODULE, "DEFAULT_BLACKOUT_YEAR")
