from scripts.scrape_google_ratings_playwright import (
    candidate_targets,
    classify_maps_url,
    distance_km,
    make_target,
    match_problem,
    page_status,
    parse_place_coords,
)

PLACE_URL = (
    "https://www.google.com/maps/place/Farina/@19.4182778,-99.2149583,17z/data=!3m1!4b1!4m6!3m5"
    "!1s0x85d2018d83205eff:0xd30bcc8c4e603695!8m2!3d19.4182778!4d-99.2149583!16s%2Fg%2F1ptynpw4k"
)
EMPTY_PLACE_URL = "https://www.google.com/maps/place//@1.3565952,103.7631488,15z/data=!3m1!4b1"
SEARCH_URL = "https://www.google.com/maps/search/Parole+Tulum/@20.1827849,-87.4640265,13z"


def farina(**overrides):
    record = {
        "id": "amex-global-mexico-farina-lomas",
        "name": "Farina Lomas",
        "city": "Ciudad de México",
        "country": "Mexico",
        "lat": 19.4182778,
        "lng": -99.2149583,
        "source_google_map_url": "https://www.google.com/maps/search/Farina+Lomas/@19.41,-99.21",
    }
    record.update(overrides)
    return record


def test_japan_query_includes_district_when_present():
    record = {"name": "Yonehachi", "district": "Gokushomachi", "city": "Fukuoka", "prefecture": "Fukuoka"}
    assert make_target(record, "japan") == "Yonehachi Gokushomachi Fukuoka Japan"


def test_japan_query_without_district_is_unchanged():
    assert make_target({"name": "kun", "city": "Tokyo"}, "japan") == "kun Tokyo Japan"


def test_global_tries_source_map_then_text_fallback():
    record = farina()
    assert candidate_targets(record, "global") == [
        record["source_google_map_url"],
        "Farina Lomas Ciudad de México Mexico",
    ]


def test_global_skips_g_page_links():
    record = farina(source_google_map_url="https://g.page/jipinxinyi?share")
    assert candidate_targets(record, "global") == ["Farina Lomas Ciudad de México Mexico"]


def test_fallback_does_not_repeat_city_state_names():
    record = farina(name="Odette", city="Singapore", country="Singapore")
    assert candidate_targets(record, "global")[-1] == "Odette Singapore"


def test_other_datasets_use_a_single_query():
    assert candidate_targets({"name": "kun", "city": "Tokyo"}, "japan") == ["kun Tokyo Japan"]


def test_classify_maps_url():
    assert classify_maps_url(PLACE_URL) == "place"
    assert classify_maps_url(EMPTY_PLACE_URL) == "empty_place"
    assert classify_maps_url(SEARCH_URL) == "search"
    assert classify_maps_url("https://www.google.com/maps/dir/Tulum+Beach/Taboo/@20.1,-87.4") == "directions"
    assert classify_maps_url("https://www.google.com/sorry/index?continue=x") == "blocked"


def test_place_coords_prefer_data_pin_over_viewport():
    url = "https://www.google.com/maps/place/X/@1.0,2.0,17z/data=!3m1!8m2!3d19.5!4d-99.25"
    assert parse_place_coords(url) == (19.5, -99.25)


def test_place_coords_fall_back_to_place_viewport():
    assert parse_place_coords("https://www.google.com/maps/place/X/@19.41,-99.21,17z") == (19.41, -99.21)


def test_search_and_empty_place_viewports_are_not_place_coords():
    assert parse_place_coords(SEARCH_URL) is None
    assert parse_place_coords(EMPTY_PLACE_URL) is None
    assert parse_place_coords(None) is None


def test_distance_km():
    assert distance_km((0.0, 0.0), (0.0, 0.0)) == 0
    assert 110 < distance_km((0.0, 0.0), (1.0, 0.0)) < 112


def test_match_accepts_nearby_place():
    assert match_problem({"maps_url": PLACE_URL, "status": None}, farina()) is None


def test_match_rejects_distant_place():
    record = farina(lat=20.149496, lng=-87.4592208)
    problem = match_problem({"maps_url": PLACE_URL, "status": None}, record)
    assert problem is not None and "km from the record" in problem


def test_match_rejects_result_without_place_coordinates():
    problem = match_problem({"maps_url": SEARCH_URL, "status": None}, farina())
    assert problem is not None and "no place coordinates" in problem


def test_match_without_record_coordinates_is_unguarded():
    record = farina(lat=None, lng=None)
    assert match_problem({"maps_url": SEARCH_URL, "status": None}, record) is None


def test_closed_status_needs_a_tighter_match():
    # Yonehachi's closed Tenjin store sits 1.6 km from the open venue.
    record = farina(lat=19.4182778 + 0.009, lng=-99.2149583)
    assert match_problem({"maps_url": PLACE_URL, "status": None}, record) is None
    problem = match_problem({"maps_url": PLACE_URL, "status": "permanently_closed"}, record)
    assert problem is not None and "closed" in problem


def test_page_status_reads_permanent_closure_only_on_place_pages():
    assert page_status("place", "Blanco Bistró\n4.2\nPermanently closed") == "permanently_closed"
    assert page_status("place", "Parole Cancun\nTemporarily closed") is None
    assert page_status("search", "Some other result · Permanently closed") is None
