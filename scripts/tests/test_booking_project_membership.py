from __future__ import annotations

import pytest

from scripts import scrape_table_for_two as scraper


def project_row(name: str, restaurant_id: str, *, status: str = "online",
                availability_project: str = "AMEXPlatSG") -> dict:
    return {
        "id": 1,
        "restaurant_id": restaurant_id,
        "program_id": 253,
        "status": status,
        "availability_project": availability_project,
        "restaurant": {"id": restaurant_id, "name": name, "address": "1 Test Road"},
    }


@pytest.mark.parametrize("availability_project", ["AMEXPlatSG", "diningcity", "", None])
def test_slot_backend_does_not_decide_membership(availability_project: str | None) -> None:
    """DiningCity moved live venues to "diningcity" slot serving on 2026-09-02.

    Reading that as a removal deleted seven bookable venues from the roster.
    """
    record = scraper._booking_project_record(
        project_row("Estate", "205195358", availability_project=availability_project)
    )

    assert scraper._eligible_membership_record(record) is True


@pytest.mark.parametrize("status", ["offline", "archived", "hidden"])
def test_a_venue_that_is_not_online_is_not_a_member(status: str) -> None:
    record = scraper._booking_project_record(project_row("Gone", "1", status=status))

    assert scraper._eligible_membership_record(record) is False


def test_a_venue_listed_without_a_status_counts_as_a_member() -> None:
    record = scraper._booking_project_record(project_row("Quiet", "2", status=""))

    assert scraper._eligible_membership_record(record) is True


def test_membership_streak_keeps_a_venue_whose_slot_backend_changed() -> None:
    records = [
        scraper._booking_project_record(
            project_row("Estate", "205195358", availability_project="diningcity")
        )
    ]
    roster = [{"id": "tft-estate", "name": "Estate", "dining_city_id": "205195358"}]
    previous = {
        "observation_status": "success",
        "membership_streaks": [
            {"id": "205195358", "name": "Estate", "state": "present",
             "consecutive_present": 9, "consecutive_absent": 0},
        ],
    }

    streaks = scraper._membership_streaks(records, roster, previous, "2026-09-05T00:00:00Z")

    estate = next(s for s in streaks if s["id"] == "205195358")
    assert estate["state"] == "present"
    assert estate["consecutive_absent"] == 0


# --- card tiers ---------------------------------------------------------------

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc).replace(microsecond=0)
CHECKED_AT = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
SOON = (NOW + timedelta(days=3)).strftime("%Y-%m-%d")
ZYX = "205196578"


def fake_dc(routes: dict):
    calls = []

    def fetch(path, params=None, *, accept_version=True):
        calls.append((path, dict(params or {})))
        key = (path, (params or {}).get("project"))
        value = routes.get(key, routes.get(path))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected DiningCity call {key}")
        return value

    fetch.calls = calls
    return fetch


def zyx_platinum_record() -> dict:
    return scraper._booking_project_record(project_row("Zui Yu Xuan", ZYX))


def links(*codes: str) -> list[dict]:
    return [{"project": code} for code in codes]


def test_platinum_membership_output_is_unchanged(monkeypatch) -> None:
    fetch = fake_dc({"/projects/AMEXPlatSG/restaurants": [project_row("Estate", "205195358")]})
    monkeypatch.setattr(scraper, "fetch_json", fetch)

    result = scraper.fetch_booking_project_membership([], CHECKED_AT)

    assert result["project"] == "AMEXPlatSG"
    assert result["tier"] == "platinum"
    assert "membership" not in result["observed_venues"][0]
    assert "project_codes_by_id" not in result


def test_centurion_lists_its_own_project_and_previous_source(monkeypatch) -> None:
    fetch = fake_dc({"/projects/AMEXCentSG/restaurants": [
        project_row("JAAN By Kirk Westaway", "205189592", availability_project="AMEXCentSG")
    ]})
    monkeypatch.setattr(scraper, "fetch_json", fetch)
    existing = {"booking_project_sources": {"centurion": {
        "observation_status": "success",
        "observed_venues": [],
        "membership_streaks": [{"id": "205189592", "name": "JAAN By Kirk Westaway",
                                "state": "absent", "consecutive_present": 0,
                                "consecutive_absent": 1}],
    }}}

    result = scraper.fetch_booking_project_membership(
        [], CHECKED_AT, existing, tier="centurion", linked_candidates=[]
    )

    assert result["project"] == "AMEXCentSG" and result["tier"] == "centurion"
    assert fetch.calls[0][0] == "/projects/AMEXCentSG/restaurants"
    assert result["observed_venues"][0]["membership"] == "listed"
    jaan = next(s for s in result["membership_streaks"] if s["id"] == "205189592")
    assert jaan["consecutive_present"] == 1


def test_linked_only_admitted_with_dates_and_kept_without_dates() -> None:
    pae = f"/restaurants/{ZYX}/projects/program_and_event"
    dates = f"/restaurants/{ZYX}/dining_dates"

    run1 = fake_dc({pae: links("AMEXCentSG", "AMEXPlatSG"),
                    (dates, "AMEXCentSG"): [{"date": SOON, "available": True}]})
    records, codes = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), {}, fetch=run1
    )
    assert [r["membership"] for r in records] == ["linked_only"]
    assert records[0]["availability_project"] == "AMEXCentSG"
    assert codes == {ZYX: ["AMEXCentSG", "AMEXPlatSG"]}

    previous = {"observation_status": "success", "observed_venues": records}
    run2 = fake_dc({pae: links("AMEXCentSG"), (dates, "AMEXCentSG"): []})
    kept, _ = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), previous, fetch=run2
    )
    assert [r["id"] for r in kept] == [ZYX]

    run3 = fake_dc({pae: links("AMEXPlatSG")})
    gone, _ = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), previous, fetch=run3
    )
    assert gone == []


def test_linked_only_not_admitted_without_dates_first_time() -> None:
    fetch = fake_dc({f"/restaurants/{ZYX}/projects/program_and_event": links("AMEXCentSG"),
                     (f"/restaurants/{ZYX}/dining_dates", "AMEXCentSG"): []})

    records, _ = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), {}, fetch=fetch
    )

    assert records == []


def test_linked_only_skips_venues_already_listed() -> None:
    fetch = fake_dc({})

    records, codes = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", {ZYX}, {}, fetch=fetch
    )

    assert records == [] and codes == {} and fetch.calls == []


def test_linked_only_fetch_error_keeps_previous_record() -> None:
    previous_record = {**zyx_platinum_record(), "availability_project": "AMEXCentSG",
                       "membership": "linked_only"}
    previous = {"observation_status": "success", "observed_venues": [previous_record]}
    fetch = fake_dc({f"/restaurants/{ZYX}/projects/program_and_event": OSError("boom")})

    records, codes = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), previous, fetch=fetch
    )

    assert records == [previous_record]
    assert ZYX not in codes


def test_project_codes_collected_per_venue() -> None:
    fetch = fake_dc({f"/restaurants/{ZYX}/projects/program_and_event":
                     links("AMEXPlatSG", "asia_award_dining", "AMEXCentSG"),
                     (f"/restaurants/{ZYX}/dining_dates", "AMEXCentSG"): []})

    _, codes = scraper.linked_only_membership_records(
        [zyx_platinum_record()], "AMEXCentSG", set(), {}, fetch=fetch
    )

    assert codes == {ZYX: ["AMEXCentSG", "AMEXPlatSG", "asia_award_dining"]}


def test_centurion_fetch_appends_linked_only_records(monkeypatch) -> None:
    monkeypatch.setattr(scraper, "fetch_json", fake_dc({
        "/projects/AMEXCentSG/restaurants": [
            project_row("JAAN By Kirk Westaway", "205189592", availability_project="AMEXCentSG")
        ],
        f"/restaurants/{ZYX}/projects/program_and_event": links("AMEXCentSG", "AMEXPlatSG"),
        (f"/restaurants/{ZYX}/dining_dates", "AMEXCentSG"): [{"date": SOON, "available": True}],
    }))

    result = scraper.fetch_booking_project_membership(
        [], CHECKED_AT, {}, tier="centurion", linked_candidates=[zyx_platinum_record()]
    )

    by_id = {r["id"]: r for r in result["observed_venues"]}
    assert by_id[ZYX]["membership"] == "linked_only"
    assert result["project_codes_by_id"] == {ZYX: ["AMEXCentSG", "AMEXPlatSG"]}
    assert any(s["id"] == ZYX and s["state"] == "present" for s in result["membership_streaks"])
