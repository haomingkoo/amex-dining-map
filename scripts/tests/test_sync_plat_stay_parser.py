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
