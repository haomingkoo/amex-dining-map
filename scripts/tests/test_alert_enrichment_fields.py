from scripts import source_change_alert


def test_rating_and_website_enrichment_do_not_change_the_record_hash():
    base = {"id": "r1", "name": "Venue", "external_signals": {"tabelog": {"score_raw": 3.5}}}
    rescored = {**base, "external_signals": {"tabelog": {"score_raw": 3.9}}}

    assert source_change_alert.stable_record_hash(base) == source_change_alert.stable_record_hash(rescored)


def test_source_fields_still_change_the_record_hash():
    base = {"id": "r1", "name": "Venue", "summary_official": "Old blurb"}

    assert source_change_alert.stable_record_hash(base) != source_change_alert.stable_record_hash(
        {**base, "summary_official": "New blurb"}
    )


def test_regeocoded_map_pin_does_not_change_the_record_hash():
    base = {"id": "r1", "name": "Venue", "coordinate_confidence": "approximate", "map_pin_note": "city centroid"}
    regeocoded = {**base, "coordinate_confidence": "exact", "map_pin_note": "street address", "coordinate_source": "nominatim"}

    assert source_change_alert.stable_record_hash(base) == source_change_alert.stable_record_hash(regeocoded)
