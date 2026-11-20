from __future__ import annotations

import json
import pytest

from scripts import scrape_love_dining as MODULE


STANDARD_TERMS = "Qualifying Food Items: À la carte menu only. Love Dining privileges apply to total food bill."


def _outlet(name: str, cuisine: str, address: str, terms: str = STANDARD_TERMS) -> str:
    return f"""{name}
Details
Cuisine: {cuisine}
Address:
{address}
Find on map
Terms and Conditions
{terms}"""


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
    previous["reviewed_terms_manifest_sha256"] = {
        "restaurants": "a" * 64,
        "hotels": "b" * 64,
    }
    meta_path.write_text(json.dumps(previous))
    monkeypatch.setattr(MODULE, "fetch_bytes", lambda url: (url + "changed").encode())

    reviewed = MODULE.build_meta(
        records,
        "2026-08-30T00:00:00Z",
        mark_records_reviewed=True,
    )

    assert reviewed["reviewed_records_sha256"] == reviewed["records_sha256"]
    assert reviewed["reviewed_terms_hashes"] == previous["terms_hashes"]
    assert reviewed["terms_reviewed_at_by_document"] == previous[
        "terms_reviewed_at_by_document"
    ]
    assert reviewed["reviewed_terms_manifest_sha256"] == previous[
        "reviewed_terms_manifest_sha256"
    ]
    assert reviewed["terms_hashes"] != reviewed["reviewed_terms_hashes"]
    assert reviewed["manual_review_required"] is True


def test_fixed_rate_comes_from_the_outlet_terms():
    page = f"""Love Dining @ Hotels Partners
Paradox Singapore
20 Merchant Road, Singapore 058281
Riverside dining concepts.
{_outlet("Crossroads Bar", "Bar", "20 Merchant Road, Singapore 058281", "Enjoy 20% off your total bill for a maximum of 10 person party, per visit, per bill.")}
{_outlet("Blue Potato", "Western", "20 Merchant Road, Singapore 058281")}
Orchard Hotel Singapore
442 Orchard Road, Singapore 238879
Orchard dining concepts.
{_outlet("Hua Ting Restaurant", "Cantonese", "442 Orchard Road, Singapore 238879", "Enjoy 35% off your total food bill only from the à la carte menu.")}
GET AN AMERICAN EXPRESS CARD"""

    by_name = {record["name"]: record for record in MODULE.parse_hotels(page)}

    assert by_name["Crossroads Bar"]["fixed_discount_percent"] == 20
    assert by_name["Hua Ting Restaurant"]["fixed_discount_percent"] == 35
    assert "fixed_discount_percent" not in by_name["Blue Potato"]
    assert "Enjoy" not in by_name["Crossroads Bar"]["notes"]


def test_fixed_rate_is_read_from_terms_split_across_lines():
    page = f"""Love Dining @ Hotels Partners
Paradox Singapore
20 Merchant Road, Singapore 058281
{_outlet("Crossroads Bar", "Bar", "20 Merchant Road, Singapore 058281", "Enjoy 15% off your total\nbill for a party of 10.")}
GET AN AMERICAN EXPRESS CARD"""

    assert MODULE.parse_hotels(page)[0]["fixed_discount_percent"] == 15


def test_outlet_without_terms_text_fails_closed():
    page = f"""Love Dining @ Hotels Partners
Paradox Singapore
20 Merchant Road, Singapore 058281
{_outlet("Crossroads Bar", "Bar", "20 Merchant Road, Singapore 058281", "")}
GET AN AMERICAN EXPRESS CARD"""

    with pytest.raises(ValueError, match="terms text missing for Crossroads Bar"):
        MODULE.parse_hotels(page)


def test_refresh_that_drops_most_records_is_refused():
    with pytest.raises(SystemExit, match="Refusing to write: scrape found 9 records, previous file has 77"):
        MODULE.check_record_retention(9, 77)


def test_refresh_keeping_seventy_percent_of_records_is_allowed():
    MODULE.check_record_retention(53, 77)
    MODULE.check_record_retention(82, 77)
    with pytest.raises(SystemExit, match=r"found 52 records, previous file has 77 \(minimum 53\)\. Likely a page layout change or partial load; inspect"):
        MODULE.check_record_retention(52, 77)


def test_dom_text_collapses_blank_lines_between_nodes():
    raw = "Gupshup\n      \n   Details\n\n\nAddress:\xa0\n  1 Road"

    assert MODULE.page_text_from_dom(raw) == "Gupshup\nDetails\nAddress:\n1 Road"


RESTAURANT_PAGE = """Skip This
Details
Love Dining @ Restaurants Partners
Uncategorised
Details
Terms and Conditions
Asian
Quenino
Details
Reservations recommended.
Details
Walk-ins welcome.
*Not valid on public holidays
Cuisine: Italian
Address:
1 Raffles Place,
#01-01, Singapore 048616
Find on map
Tel: +65 6111 1111
Tel (Bar): +65 6111 2222 (ext: 12)
Visit Website
Opening Hours:
Mon-Fri 12pm-3pm
Sat 6pm-10pm
Terms and Conditions
Love Dining @ Restaurants Partners
Western
(Two Tables!)
Details
Opening Hours:
Daily 11am-10pm
Address:
2 Bridge Road Singapore 000002
Tel: +65 6222 2222
Terms and Conditions
Contemporary
Third Place
Details
Address:
3 Hill Street
Opening Hours: see website
Cuisine: Modern
Your Love Dining Benefits
Footer Card
Details
Your Love Dining Benefits"""


def _restaurant(**fields) -> dict:
    return {
        "type": "restaurant",
        "cuisine": "",
        "address": "",
        "city": "Singapore",
        "country": "Singapore",
        "phone": "",
        "opening_hours": "",
        "notes": "",
        "source": "Amex Love Dining",
        "source_url": MODULE.RESTAURANTS_URL,
        "terms_url": MODULE.RESTAURANTS_TNC_URL,
        **fields,
    }


def test_restaurant_cards_between_the_partners_heading_and_the_footer_are_parsed():
    assert MODULE.parse_restaurants(RESTAURANT_PAGE) == [
        _restaurant(id="love-uncategorised", name="Uncategorised", cuisine_category=""),
        _restaurant(
            id="love-quenino",
            name="Quenino",
            cuisine_category="Asian",
            cuisine="Italian",
            address="1 Raffles Place, #01-01, Singapore 048616",
            phone="+65 6111 1111 / +65 6111 2222 (ext: 12)",
            opening_hours="Mon-Fri 12pm-3pm; Sat 6pm-10pm",
            notes="Reservations recommended. Walk-ins welcome.",
            closing_note="Permanently closed from 1 May 2026",
        ),
        _restaurant(
            id="love-two-tables",
            name="(Two Tables!)",
            cuisine_category="Western",
            address="2 Bridge Road Singapore 000002",
            phone="+65 6222 2222",
            opening_hours="Daily 11am-10pm",
        ),
        _restaurant(
            id="love-third-place",
            name="Third Place",
            cuisine_category="Contemporary",
            cuisine="Modern",
            address="3 Hill Street",
            notes="Opening Hours: see website",
        ),
    ]


@pytest.mark.parametrize("stop", ["Find on map", "Tel:", "Visit Website", "Terms and Conditions", "Cuisine:", "Address:"])
def test_restaurant_address_ends_at_the_next_field_label(stop):
    page = f"A Place\nDetails\nAddress:\n9 Main Road\n{stop}\nTerms and Conditions"
    assert MODULE.parse_restaurants(page)[0]["address"] == "9 Main Road"


@pytest.mark.parametrize(
    ("body", "field", "value"),
    [("Address:\n9 Main Road", "address", "9 Main Road"), ("Opening Hours:\nDaily", "opening_hours", "Daily"), ("", "name", "A Place")],
)
def test_restaurant_card_cut_off_at_the_end_of_the_page_is_kept(body, field, value):
    assert MODULE.parse_restaurants(f"A Place\nDetails\n{body}")[0][field] == value


@pytest.mark.parametrize("stop", ["Address:", "Tel:", "Find on map", "Visit Website", "Terms and Conditions", "Cuisine:"])
def test_restaurant_opening_hours_end_at_the_next_field_label(stop):
    page = f"A Place\nDetails\nOpening Hours:\nDaily\n{stop}\nTerms and Conditions"
    assert MODULE.parse_restaurants(page)[0]["opening_hours"] == "Daily"



HOTEL_PAGE = """Old Promo Hotel
1 Old Road, Singapore 111111
Promo Bar
Details
Terms and Conditions
Up to 50% off.
Love Dining @ Hotels Partners
Grand Hotel
1 Grand Road, Singapore 222222
Lobby Lounge!
Details
Afternoon tea daily.
Details
High tea on weekends.
Cuisine: International
Opening Hours:
Mon-Sun 10am-10pm
Late bar Fri
Address:
Level 2,
1 Grand Road, Singapore 222222
Tel: +65 6333 3333
Tel (Events): +65 6333 4444 (ext: 5)
Find on map
Visit Website
Terms and Conditions
Enjoy 15% off your total food bill.
Valid for dine-in only.
Garden Grill
Details
Terms and Conditions
Up to 50% off.
Harbour Hotel
9 Harbour Way, Singapore 333333
Pier Bar
Details
Terms and Conditions
Up to 50% off.
Love Dining @ Hotels Partners
GET AN AMERICAN EXPRESS CARD
Footer Hotel
4 Footer Road, Singapore 444444
Footer Outlet
Details
Terms and Conditions
Up to 50% off.
GET AN AMERICAN EXPRESS CARD"""


def _hotel_outlet(**fields) -> dict:
    return {
        "type": "hotel",
        "cuisine": "",
        "city": "Singapore",
        "country": "Singapore",
        "phone": "",
        "opening_hours": "",
        "notes": "",
        "source": "Amex Love Dining",
        "source_url": MODULE.HOTELS_URL,
        "terms_url": MODULE.HOTELS_TNC_URL,
        **fields,
    }


def test_hotel_outlets_take_their_hotel_its_address_and_their_own_terms():
    assert MODULE.parse_hotels(HOTEL_PAGE) == [
        _hotel_outlet(
            id="love-grand-hotel-lobby-lounge",
            name="Lobby Lounge!",
            hotel="Grand Hotel",
            cuisine="International",
            address="Level 2, 1 Grand Road, Singapore 222222",
            phone="+65 6333 3333 / +65 6333 4444 (ext: 5)",
            opening_hours="Mon-Sun 10am-10pm; Late bar Fri",
            notes="Afternoon tea daily. High tea on weekends.",
            fixed_discount_percent=15,
        ),
        _hotel_outlet(
            id="love-grand-hotel-garden-grill",
            name="Garden Grill",
            hotel="Grand Hotel",
            address="1 Grand Road, Singapore 222222",
        ),
        _hotel_outlet(
            id="love-harbour-hotel-pier-bar",
            name="Pier Bar",
            hotel="Harbour Hotel",
            address="9 Harbour Way, Singapore 333333",
        ),
    ]


def _one_outlet(body: str) -> dict:
    page = f"Grand Hotel\n1 Grand Road, Singapore 222222\nBar\nDetails\n{body}\nTerms and Conditions\nUp to 50% off."
    return MODULE.parse_hotels(page)[0]


@pytest.mark.parametrize(
    "stop",
    ["Find on map", "Tel:", "Visit Website", "Cuisine:", "Address:", "Opening Hours:", "Tel: +65 6000 0000", "Opening Hours: 24h"],
)
def test_hotel_address_ends_at_the_next_field_label(stop):
    assert _one_outlet(f"Address:\nLevel 3\n{stop}")["address"] == "Level 3"


def test_hotel_address_ends_at_the_terms():
    page = "Grand Hotel\n1 Grand Road, Singapore 222222\nBar\nDetails\nAddress:\nLevel 3\nTerms and Conditions\nUp to 50% off."
    assert MODULE.parse_hotels(page)[0]["address"] == "Level 3"


@pytest.mark.parametrize("stop", ["Address:", "Tel:", "Find on map", "Visit Website", "Cuisine:"])
def test_hotel_opening_hours_end_at_the_next_field_label(stop):
    assert _one_outlet(f"Opening Hours:\nDaily\n{stop}")["opening_hours"] == "Daily"


def test_hotel_opening_hours_end_at_the_terms():
    page = "Grand Hotel\n1 Grand Road, Singapore 222222\nBar\nDetails\nOpening Hours:\nDaily\nTerms and Conditions\nUp to 50% off."
    assert MODULE.parse_hotels(page)[0]["opening_hours"] == "Daily"


def test_hotel_page_ending_after_a_heading_has_no_outlets():
    assert MODULE.parse_hotels("Grand Hotel\n1 Grand Road, Singapore 222222\nNew outlets coming soon") == []


@pytest.mark.parametrize("tail", ["", "\nCuisine: Bar", "\nAddress:\nLevel 3", "\nOpening Hours:\nDaily"])
def test_hotel_outlet_cut_off_before_its_terms_fails_closed(tail):
    page = f"Grand Hotel\n1 Grand Road, Singapore 222222\nBar\nDetails\nTerms and Conditions\nUp to 50% off.\nCafe\nDetails{tail}"
    with pytest.raises(ValueError, match="terms text missing for Cafe"):
        MODULE.parse_hotels(page)
