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
