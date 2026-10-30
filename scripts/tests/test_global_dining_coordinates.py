from scripts import scrape_global_dining as scraper


def _chin_chin(region, address, lat, lng, merchant_id):
    return {
        "id": "amex-global-australia-chin-chin",
        "country": "Australia",
        "region": region,
        "city": region,
        "name": "Chin Chin",
        "source_localized_address": address,
        "source_google_map_url": f"https://www.google.com/maps/search/Chin+Chin/@{lat},{lng}",
        "source_url": "https://www.americanexpress.com/en-sg/benefits/diningbenefit/",
        "source_merchant_id": merchant_id,
        "lat": lat,
        "lng": lng,
    }


def _rating(address, lat, lng):
    return {
        "google_name": "Chin Chin",
        "google_address": address,
        "maps_url": f"https://www.google.com/maps/place/Chin+Chin/@{lat},{lng},17z",
    }


def test_coordinates_are_checked_against_the_venue_own_google_place():
    surry_hills = _chin_chin(
        "New South Wales", "69 Commonwealth St, Surry Hills, New South Wales, 2020, Australia",
        -33.8789358, 151.2107284, "233e141a",
    )
    melbourne = _chin_chin(
        "Victoria", "125 Flinders Ln, Melbourne, Victoria, 3000, Australia",
        -37.815614, 144.970377, "5283821e",
    )
    # Ratings are keyed by final ids; a stale shared-id entry points at the other branch.
    ratings = {
        "amex-global-australia-chin-chin": _rating("125 Flinders Ln, Melbourne VIC 3000, Australia", -37.815614, 144.970377),
        "amex-global-australia-chin-chin-new-s-wales": _rating(
            "69 Commonwealth St, Surry Hills NSW 2010, Australia", -33.8789358, 151.2107284
        ),
    }

    stats = scraper.assign_ids_and_validate_coordinates([surry_hills, melbourne], {}, ratings)

    assert surry_hills["id"] == "amex-global-australia-chin-chin-new-s-wales"
    assert surry_hills["coordinate_confidence"] == "google_place_verified"
    assert (surry_hills["lat"], surry_hills["lng"]) == (-33.8789358, 151.2107284)
    assert melbourne["lat"] is not None
    assert stats["reassigned_ids"] == 2
    assert stats["hidden"] == 0


def _venue(record_id, name, address, amex_lat, amex_lng):
    return {
        "id": record_id,
        "country": "United Kingdom" if "London" in address else "Mexico",
        "region": "London" if "London" in address else "Ciudad de México",
        "city": "London" if "London" in address else "Ciudad de México",
        "name": name,
        "source_localized_address": address,
        "source_google_map_url": f"https://www.google.com/maps/search/{name}/@{amex_lat},{amex_lng}",
        "lat": amex_lat,
        "lng": amex_lng,
    }


def test_google_place_at_the_same_street_number_wins_over_an_offset_amex_pin():
    # Amex's map link for Bar des Prés points near Piccadilly, about 700 m from South Audley St.
    venue = _venue("bar-des-pres", "Bar Des Pres", "41a S Audley St, London, W1K 2PS, United Kingdom", 51.5093262, -0.1418747)
    ratings = {"bar-des-pres": {
        "google_name": "Bar des Prés",
        "google_address": "41a S Audley St, London W1K 2PS, United Kingdom",
        "maps_url": "https://www.google.com/maps/place/Bar+des+Pr%C3%A9s/@51.5099521,-0.1517276,17z",
    }}
    scraper.validate_record_coordinates(venue, {}, ratings)
    assert venue["coordinate_confidence"] == "google_place_verified"
    assert (venue["lat"], venue["lng"]) == (51.5099521, -0.1517276)


def test_google_place_at_another_street_number_stays_hidden():
    # Google matched another Loretta branch; only district and city words overlap.
    venue = _venue(
        "loretta", "Loretta Chic Bistrot",
        "Av. Revolución No. 1426, Guadalupe Inn, Ciudad de México, 01020, Mexico", 19.3556012, -99.1897105,
    )
    ratings = {"loretta": {
        "google_name": "Loretta Chic Bistrot",
        "google_address": "dentro de la plaza alma, Av. P.º de la Reforma 2620, Lomas Altas, Ciudad de México, CDMX, Mexico",
        "maps_url": "https://www.google.com/maps/place/Loretta/@19.4254832,-99.1696632,17z",
    }}
    scraper.validate_record_coordinates(venue, {}, ratings)
    assert venue["coordinate_confidence"] == "location_conflict"
    assert venue["lat"] is None


def test_street_number_comes_from_the_street_part_not_the_postcode():
    assert scraper.same_street_number("No. 796, Zhonghua Rd., Tainan", "No. 796號, Zhonghua Rd, Tainan")
    assert not scraper.same_street_number(
        "Queens Wharf, Wellington Central, Wellington, 6011, New Zealand",
        "3 Queens Wharf, Wellington Central, Wellington 6011, New Zealand",
    )
