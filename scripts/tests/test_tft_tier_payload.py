"""Every venue records which card tiers can book it; Platinum fields keep their meaning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import scrape_table_for_two as scraper
from scripts import tft_roster_reviews

NOW = datetime.now(timezone.utc).replace(microsecond=0)
SOON = (NOW + timedelta(days=3)).strftime("%Y-%m-%d")
SHARED, PLAT_ONLY, JAAN, ZYX = "1", "2", "205189592", "205196578"


def row(name: str, restaurant_id: str, project: str) -> dict:
    return {
        "restaurant_id": restaurant_id,
        "status": "online",
        "availability_project": project,
        "restaurant": {"id": restaurant_id, "name": name, "address": f"{restaurant_id} Road, Singapore",
                       "lat": 1.29, "lng": 103.85, "dirname": name.replace(" ", "_")},
    }


def venue(name: str, diningcity_id: str) -> dict:
    return {"id": f"tft-{name.lower().replace(' ', '-')}", "name": name, "category": "restaurant",
            "dining_city_id": diningcity_id, "address": f"{diningcity_id} Road, Singapore",
            "lat": 1.29, "lng": 103.85}


def fake_dc(routes: dict):
    def fetch(path, params=None, *, accept_version=True):
        key = (path, (params or {}).get("project"))
        value = routes.get(key, routes.get(path))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected DiningCity call {key}")
        return value
    return fetch


def routes(extra_codes: tuple[str, ...] = ()) -> dict:
    plat = [row("Shared", SHARED, "AMEXPlatSG"), row("PlatOnly", PLAT_ONLY, "AMEXPlatSG"),
            row("Zui Yu Xuan", ZYX, "AMEXPlatSG")]
    cent = [row("Shared", SHARED, "AMEXCentSG"),
            row("JAAN By Kirk Westaway", JAAN, "AMEXCentSG")]
    r = {
        "/projects/AMEXPlatSG/restaurants": plat,
        "/projects/AMEXCentSG/restaurants": cent,
        (f"/restaurants/{ZYX}/dining_dates", "AMEXCentSG"): [{"date": SOON, "available": True}],
    }
    for rid, codes in {
        SHARED: ("AMEXPlatSG", "AMEXCentSG"),
        PLAT_ONLY: ("AMEXPlatSG", "mastercardAsia"),
        ZYX: ("AMEXCentSG", "AMEXPlatSG"),
        JAAN: ("AMEXCentSG", "asia_award_dining"),
    }.items():
        r[f"/restaurants/{rid}/projects/program_and_event"] = [
            {"project": code} for code in (*codes, *extra_codes)
        ]
    return r


@pytest.fixture
def no_slots(monkeypatch):
    seen = []

    def fake_live(venues, checked_at):
        seen.extend(v["name"] for v in venues)
        return {}, {}

    monkeypatch.setattr(scraper, "fetch_live_availability", fake_live)
    return seen


def refresh_twice(monkeypatch, extra_codes=()) -> dict:
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(routes(extra_codes)))
    payload = {"venues": [venue("Shared", SHARED), venue("PlatOnly", PLAT_ONLY), venue("Zui Yu Xuan", ZYX)]}
    for _ in range(2):
        payload = scraper.refresh_availability_payload(payload)
    return payload


def by_name(payload: dict) -> dict:
    return {v["name"]: v for v in payload["venues"]}


def test_payload_tiers_for_shared_platinum_only_and_centurion_only(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch)
    venues = by_name(payload)

    assert venues["Shared"]["tiers"] == ["platinum", "centurion"]
    assert venues["Shared"]["tier_membership"] == {"centurion": "listed"}
    assert venues["PlatOnly"]["tiers"] == ["platinum"]
    assert venues["PlatOnly"]["booking_project_statuses"] == {"platinum": "active", "centurion": "not_listed"}
    assert "tier_membership" not in venues["PlatOnly"]
    jaan = venues["JAAN By Kirk Westaway"]
    assert jaan["tiers"] == ["centurion"]
    assert jaan["booking_project_status"] == "not_listed"
    assert jaan["roster_basis"] == "diningcity_centurion_project_confirmed"
    assert venues["Zui Yu Xuan"]["tiers"] == ["platinum", "centurion"]
    assert venues["Zui Yu Xuan"]["tier_membership"] == {"centurion": "linked_only"}
    assert payload["booking_project_source"]["project"] == "AMEXPlatSG"
    assert payload["booking_project_sources"]["centurion"]["project"] == "AMEXCentSG"


def test_known_and_unknown_amex_projects_are_reported(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch, extra_codes=("AMEXNewSG",))

    codes = payload["booking_project_codes"]
    assert codes["unknown_amex"] == ["AMEXNewSG"]
    assert codes["known"] == ["AMEXCentSG", "AMEXPlatSG"]


def test_no_unknown_projects_without_new_amex_codes(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch)

    assert payload["booking_project_codes"]["unknown_amex"] == []


def test_centurion_only_venue_gets_no_platinum_slot_fetch(monkeypatch, no_slots) -> None:
    refresh_twice(monkeypatch)

    assert "JAAN By Kirk Westaway" not in no_slots
    assert "Shared" in no_slots


def test_centurion_listing_error_keeps_platinum_and_centurion_supplements(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch)
    broken = routes()
    broken["/projects/AMEXCentSG/restaurants"] = OSError("DiningCity 503")
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(broken))

    after = by_name(scraper.refresh_availability_payload(payload))

    assert after["JAAN By Kirk Westaway"]["tiers"] == ["centurion"]
    assert after["Shared"]["tiers"] == ["platinum", "centurion"]
    assert after["PlatOnly"]["booking_project_statuses"]["platinum"] == "active"


def test_tier_fields_are_runtime_not_manifest_owned() -> None:
    record = {**venue("Shared", SHARED), "tiers": ["platinum"],
              "booking_project_statuses": {"platinum": "active"},
              "tier_membership": {"centurion": "listed"}}

    stable = tft_roster_reviews.stable_venue(record)

    assert not {"tiers", "booking_project_statuses", "tier_membership"} & set(stable)


# --- final review fixes ------------------------------------------------------

def test_same_name_under_new_platinum_id_becomes_review_item_not_crash(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch)
    r = routes()
    r["/projects/AMEXPlatSG/restaurants"] = [*r["/projects/AMEXPlatSG/restaurants"],
                                             row("JAAN By Kirk Westaway", "999", "AMEXPlatSG")]
    r["/restaurants/999/projects/program_and_event"] = [{"project": "AMEXPlatSG"}]
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(r))

    for _ in range(3):
        payload = scraper.refresh_availability_payload(payload)

    jaans = [v for v in payload["venues"] if v["name"] == "JAAN By Kirk Westaway"]
    assert len(jaans) == 1 and jaans[0]["dining_city_id"] == JAAN
    reasons = {reason for item in payload["booking_project_source"]["booking_project_review_items"]
               for reason in item["reasons"]}
    assert "duplicate_normalized_name" in reasons


def test_centurion_pass_failure_never_stops_platinum(monkeypatch, no_slots) -> None:
    payload = refresh_twice(monkeypatch)

    def boom(*_args, **_kwargs):
        raise ValueError("published Table for Two roster has missing or duplicate venue IDs")

    monkeypatch.setattr(scraper, "current_published_roster",
                        lambda roster, source, existing=None, *, tier="platinum":
                        boom() if tier == "centurion" else ORIGINAL_ROSTER(roster, source, existing, tier=tier))
    after = scraper.refresh_availability_payload(payload)

    venues = by_name(after)
    assert venues["PlatOnly"]["booking_project_statuses"]["platinum"] == "active"
    assert venues["JAAN By Kirk Westaway"]["tiers"] == ["centurion"]
    assert after["booking_project_sources"]["centurion"]["observation_status"] == "error"


ORIGINAL_ROSTER = scraper.current_published_roster


def test_platinum_error_keeps_centurion_only_venue_out_of_platinum_consumers(monkeypatch, no_slots) -> None:
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(routes()))
    payload = {"venues": [venue("Shared", SHARED), venue("PlatOnly", PLAT_ONLY), venue("Zui Yu Xuan", ZYX)]}
    payload = scraper.refresh_availability_payload(payload)
    broken = routes()
    broken["/projects/AMEXPlatSG/restaurants"] = OSError("DiningCity 503")
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(broken))
    no_slots.clear()

    after = by_name(scraper.refresh_availability_payload(payload))

    jaan = after["JAAN By Kirk Westaway"]
    assert jaan["booking_project_status"] == "not_listed"
    assert jaan["tiers"] == ["centurion"]
    assert "JAAN By Kirk Westaway" not in no_slots


def test_unknown_centurion_status_on_first_run_does_not_write_platinum_only(monkeypatch, no_slots) -> None:
    broken = routes()
    broken["/projects/AMEXCentSG/restaurants"] = OSError("DiningCity 503")
    monkeypatch.setattr(scraper, "fetch_json", fake_dc(broken))
    payload = {"venues": [venue("Shared", SHARED), venue("PlatOnly", PLAT_ONLY)]}

    first = by_name(scraper.refresh_availability_payload(payload))

    assert first["Shared"]["booking_project_statuses"]["centurion"] == "unknown"
    assert "tiers" not in first["Shared"]


def test_unknown_tier_keeps_previous_tiers() -> None:
    venue_record = venue("Shared", SHARED)
    existing = {"tiers": ["platinum", "centurion"],
                "booking_project_statuses": {"platinum": "active", "centurion": "active"}}

    fields = scraper.tier_fields(venue_record, "active", {"observation_status": "error"}, existing)

    assert fields["tiers"] == ["platinum", "centurion"]


def test_unknown_amex_project_stays_reported_when_its_venue_fails_once() -> None:
    previous = {"known": ["AMEXPlatSG"], "unknown_amex": ["AMEXNewSG"]}

    codes = scraper.summarize_project_codes({SHARED: ["AMEXPlatSG"]}, previous)

    assert codes["unknown_amex"] == ["AMEXNewSG"]


def test_platinum_supplement_still_gets_its_centurion_tier() -> None:
    madame = {**venue("Madame Fan", "2055296"), "roster_basis": "diningcity_booking_project_confirmed"}
    centurion = {"observation_status": "success",
                 "observed_venues": [{"id": "2055296", "name": "Madame Fan", "status": "online"}],
                 "membership_streaks": [{"id": "2055296", "state": "present", "consecutive_present": 5}]}

    status = scraper.booking_project_status_for_venue(madame, centurion, {}, tier="centurion")

    assert status == "active"


def test_unreviewed_roster_image_keeps_supplements_out_of_the_reviewed_roster():
    from scripts import tft_roster_reviews

    existing = {
        "venues": [
            {"id": "tft-vue", "name": "VUE", "roster_basis": "official_image"},
            {"id": "tft-jaan", "name": "JAAN", "roster_basis": "diningcity_centurion_project_confirmed"},
            {"id": "tft-madame-fan", "name": "Madame Fan", "roster_basis": "diningcity_booking_project_confirmed"},
        ],
        "roster_source": {"approved_participating_sha256": "a" * 64},
    }
    roster, source = tft_roster_reviews.review_state("b" * 64, "https://example.test/x.png", "2026-11-03T00:00:00Z", existing)

    assert source["review_required"] is True
    assert [record["id"] for record in roster] == ["tft-vue"]
