from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECORDS = json.loads((ROOT / "data/love-dining.json").read_text())
RATINGS = json.loads((ROOT / "data/google-maps-ratings.json").read_text())
APP_SOURCE = (ROOT / "web/app.js").read_text()


EXPECTED_HOTELS = {
    "LUCE": "Frasers House, a Luxury Collection Hotel, Singapore",
    "Man Fu Yuan": "Frasers House, a Luxury Collection Hotel, Singapore",
    "The Lobby Lounge": "Frasers House, a Luxury Collection Hotel, Singapore",
    "Blue Potato": "Paradox Singapore",
    "Ellenborough Market Café": "Paradox Singapore",
    "Crossroads Bar": "Paradox Singapore",
}


def test_corrected_outlets_have_exact_hotel_and_unique_ids():
    corrected = [
        record
        for record in RECORDS
        if record.get("name") in EXPECTED_HOTELS
        and record.get("address", "").startswith(("80 Middle Road", "20 Merchant Rd"))
    ]

    assert len(corrected) == 6
    assert len({record["id"] for record in corrected}) == 6
    for record in corrected:
        assert record["hotel"] == EXPECTED_HOTELS[record["name"]]
        assert record.get("lat") is not None
        assert record.get("lng") is not None


def test_corrected_rating_keys_do_not_reuse_wrong_hotel_results():
    forbidden = {
        "love-orchard-hotel-singapore-blue-potato",
        "love-orchard-hotel-singapore-ellenborough-market-caf",
        "love-orchard-hotel-singapore-crossroads-bar",
        "love-the-capitol-kempinski-hotel-singapore-luce",
        "love-the-capitol-kempinski-hotel-singapore-man-fu-yuan",
        "love-the-capitol-kempinski-hotel-singapore-the-lobby-lounge",
    }
    assert forbidden.isdisjoint(RATINGS)
    for record_id in (
        "love-paradox-singapore-blue-potato",
        "love-paradox-singapore-ellenborough-market-caf",
        "love-paradox-singapore-crossroads-bar",
        "love-frasers-house-a-luxury-collection-hotel-singapore-man-fu-yuan",
    ):
        assert record_id in RATINGS


def test_crossroads_fixed_twenty_rule_uses_current_id():
    assert '"love-paradox-singapore-crossroads-bar"' in APP_SOURCE
    assert '"love-paradox-singapore-merchant-court-crossroads-bar"' not in APP_SOURCE


def test_chifa_is_structurally_ineligible_from_august_first():
    chifa = next(record for record in RECORDS if record["id"] == "love-resorts-world-sentosa-chifa")
    assert chifa["eligibility_status"] == "ineligible"
    assert chifa["eligibility_effective_from"] == "2026-08-01"
    assert "permanently closed" in chifa["notes"]
