from scripts.scrape_table_for_two import booking_project_status_for_venue


def test_venue_without_diningcity_listing_is_not_listed_even_when_membership_is_unknown():
    venue = {"id": "tft-zui-yu-xuan", "dining_city_id": None, "dining_city_listing": "not_on_diningcity"}

    assert booking_project_status_for_venue(venue, None) == "not_listed"


def test_venue_missing_an_id_without_the_marker_stays_unknown():
    assert booking_project_status_for_venue({"id": "tft-x", "dining_city_id": None}, None) == "unknown"
