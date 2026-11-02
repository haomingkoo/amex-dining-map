from __future__ import annotations

from scripts.send_table_for_two_alerts import build_email, matching_slots, subscription_from_row
from scripts.tests.test_tft_live_availability import NOW, live_venue, roster, snapshot, subscription
from scripts.tft_live_availability import overlay_centurion, overlay_live_availability


def centurion_snapshot(*venues: dict) -> dict:
    payload = snapshot(*venues)
    payload["source_project"] = "AMEXCentSG"
    for venue in payload["venues"]:
        venue["project"] = "AMEXCentSG"
    return payload


def both_cards(platinum: dict, centurion: dict) -> list[dict]:
    payload = overlay_live_availability(roster(), platinum, NOW)
    return overlay_centurion(payload, centurion, NOW)["venues"]


def test_each_subscriber_matches_only_their_cards_seats() -> None:
    venues = both_cards(snapshot(), centurion_snapshot(live_venue("tft-a")))

    assert matching_slots(subscription(), venues) == []
    centurion = matching_slots(subscription(tier="centurion"), venues)
    assert [(m["venue_name"], m["time"]) for m in centurion] == [("Alpha", "12:00")]


def test_centurion_outage_sends_no_centurion_alerts() -> None:
    payload = overlay_live_availability(roster(), snapshot(live_venue("tft-a")), NOW)
    venues = overlay_centurion(payload, None, NOW)["venues"]

    assert matching_slots(subscription(tier="centurion"), venues) == []
    assert len(matching_slots(subscription(), venues)) == 1


def test_export_rows_carry_the_card_and_default_to_platinum() -> None:
    row = {"email": "a@example.com", "tier": "centurion"}
    assert subscription_from_row(row, {}, "t").tier == "centurion"
    assert subscription_from_row({"email": "a@example.com"}, {}, "t").tier == "platinum"


def test_centurion_email_names_the_card() -> None:
    venues = both_cards(snapshot(), centurion_snapshot(live_venue("tft-a")))
    sub = subscription(tier="centurion")
    message = build_email(sub, matching_slots(sub, venues), "from@example.com", "https://site")
    text = message.get_body(("plain",)).get_content()
    assert "Centurion" in text
