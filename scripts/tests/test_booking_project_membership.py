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
