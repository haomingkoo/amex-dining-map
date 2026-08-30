from __future__ import annotations

import importlib.util
import json
import pytest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scrape_love_dining.py"
SPEC = importlib.util.spec_from_file_location("scrape_love_dining", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _outlet(name: str, cuisine: str, address: str) -> str:
    return f"""{name}
Details
Cuisine: {cuisine}
Address:
{address}
Find on map
Terms and Conditions"""


def test_new_hotel_heading_does_not_inherit_previous_hotel():
    page = f"""Love Dining @ Hotels Partners
The Capitol Kempinski Hotel Singapore
15 Stamford Road, Singapore 178906
European hospitality.
{_outlet("Capitol Bistro", "International", "13 Stamford Road, Singapore 178905")}
Frasers House, a Luxury Collection Hotel, Singapore
80 Middle Road, Singapore 188966
Three dining concepts.
{_outlet("LUCE", "Italian", "80 Middle Road, Level 1, Singapore 188966")}
{_outlet("Man Fu Yuan", "Cantonese", "80 Middle Road, Level 2, Singapore 188966")}
{_outlet("The Lobby Lounge", "All-Day Dining", "80 Middle Road, Level 1, Singapore 188966")}
GET AN AMERICAN EXPRESS CARD"""

    records = MODULE.parse_hotels(page)

    by_name = {record["name"]: record for record in records}
    assert by_name["Capitol Bistro"]["hotel"] == "The Capitol Kempinski Hotel Singapore"
    for name in ("LUCE", "Man Fu Yuan", "The Lobby Lounge"):
        assert by_name[name]["hotel"] == "Frasers House, a Luxury Collection Hotel, Singapore"
        assert by_name[name]["id"].startswith("love-frasers-house-a-luxury-collection-hotel-singapore-")


def test_renamed_hotel_heading_owns_its_outlets():
    page = f"""Love Dining @ Hotels Partners
Orchard Hotel Singapore
442 Orchard Road, Singapore 238879
Orchard dining concepts.
{_outlet("Bar Intermezzo", "Bar", "442 Orchard Road, Singapore 238879")}
Paradox Singapore
20 Merchant Road, Singapore 058281
Riverside dining concepts.
{_outlet("Blue Potato", "Western", "20 Merchant Road, Singapore 058281")}
{_outlet("Ellenborough Market Café", "Buffet", "20 Merchant Road, Singapore 058281")}
{_outlet("Crossroads Bar", "Bar", "20 Merchant Road, Singapore 058281")}
GET AN AMERICAN EXPRESS CARD"""

    records = MODULE.parse_hotels(page)

    by_name = {record["name"]: record for record in records}
    assert by_name["Bar Intermezzo"]["hotel"] == "Orchard Hotel Singapore"
    for name in ("Blue Potato", "Ellenborough Market Café", "Crossroads Bar"):
        assert by_name[name]["hotel"] == "Paradox Singapore"
        assert by_name[name]["id"].startswith("love-paradox-singapore-")


def test_rekeyed_outlet_preserves_coordinates_by_unique_name_and_address(tmp_path, monkeypatch):
    source = tmp_path / "love-dining.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "love-old-hotel-luce",
                    "name": "LUCE",
                    "address": "80 Middle Road, Level 1, Singapore 188966",
                    "lat": 1.298,
                    "lng": 103.855,
                }
            ]
        )
    )
    monkeypatch.setattr(MODULE, "OUTPUT_PATH", source)
    corrected = [
        {
            "id": "love-frasers-house-a-luxury-collection-hotel-singapore-luce",
            "name": "LUCE",
            "address": "80 Middle Road, Level 1, Singapore 188966",
        }
    ]

    enriched = MODULE.preserve_existing_enrichment(corrected)

    assert enriched[0]["lat"] == 1.298
    assert enriched[0]["lng"] == 103.855


def test_orphan_outlet_fails_closed():
    page = f"""Love Dining @ Hotels Partners
{_outlet("Orphan Outlet", "Asian", "1 Example Road, Singapore 123456")}
GET AN AMERICAN EXPRESS CARD"""

    with pytest.raises(ValueError, match="before a hotel heading"):
        MODULE.parse_hotels(page)


def test_record_review_does_not_approve_changed_terms(tmp_path, monkeypatch):
    meta_path = tmp_path / "source.json"
    monkeypatch.setattr(MODULE, "META_PATH", meta_path)
    monkeypatch.setattr(MODULE, "fetch_bytes", lambda url: url.encode())
    records = [{"id": "one", "name": "One", "type": "hotel"}]
    previous = MODULE.build_meta(records, "2026-08-01T00:00:00Z", mark_reviewed=True)
    meta_path.write_text(json.dumps(previous))
    monkeypatch.setattr(MODULE, "fetch_bytes", lambda url: (url + "changed").encode())

    reviewed = MODULE.build_meta(
        records,
        "2026-08-30T00:00:00Z",
        mark_records_reviewed=True,
    )

    assert reviewed["reviewed_records_sha256"] == reviewed["records_sha256"]
    assert reviewed["reviewed_terms_hashes"] == previous["terms_hashes"]
    assert reviewed["terms_hashes"] != reviewed["reviewed_terms_hashes"]
    assert reviewed["manual_review_required"] is True
