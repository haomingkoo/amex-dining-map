from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_roster_parity as parity
from scripts.scrape_table_for_two import AUTO_MEMBERSHIP_CONFIRMATIONS


ROOT = Path(__file__).resolve().parents[2]


def api_row(diningcity_id: str, name: str, *, status: str = "online",
            availability_project: str = "AMEXPlatSG") -> dict:
    return {
        "id": 1,
        "restaurant_id": diningcity_id,
        "program_id": 253,
        "status": status,
        "availability_project": availability_project,
        "restaurant": {"id": diningcity_id, "name": name, "address": "1 Test Road",
                       "lat": 1.3, "lng": 103.8},
    }


def roster(venues: list[dict], **source: object) -> dict:
    return {"venues": venues, "booking_project_source": source}


def venue(venue_id: str, diningcity_id: str, name: str, *, status: str = "active") -> dict:
    return {"id": venue_id, "name": name, "dining_city_id": diningcity_id,
            "booking_project_status": status}


def test_slot_backend_is_not_a_membership_signal() -> None:
    """The whole incident: these venues stayed online, only their slot backend moved."""
    rows = [api_row("1", "Estate", availability_project="diningcity")]

    assert parity.live_member_ids(rows) == {"1"}


def test_an_offline_row_is_not_a_member() -> None:
    assert parity.live_member_ids([api_row("1", "Gone", status="offline")]) == set()


def test_the_committed_roster_is_silent_against_its_own_observations() -> None:
    """The healthy case. If this ever fires, the gate is crying wolf."""
    payload = json.loads((ROOT / "data/table-for-two.json").read_text())
    observed = payload["booking_project_source"]["observed_venues"]
    rows = [api_row(o["id"], o["name"], status=o.get("status") or "online",
                    availability_project=o.get("availability_project") or "AMEXPlatSG")
            for o in observed]

    faults = parity.find_faults(payload, parity.live_member_ids(rows))

    assert faults == [], [str(f) for f in faults]


def test_the_2026_09_02_deletion_is_caught() -> None:
    """Six venues online in the project but published as not_listed, plus one dropped."""
    listed = [api_row(str(i), f"Venue {i}") for i in range(1, 8)]
    published = [venue(f"tft-{i}", str(i), f"Venue {i}", status="not_listed")
                 for i in range(1, 7)]

    faults = parity.find_faults(roster(published), parity.live_member_ids(listed))

    reasons = {f.reason for f in faults}
    assert len(faults) == 7
    assert any("published as not_listed" in r for r in reasons)
    assert any("absent from the roster" in r for r in reasons)


def test_a_venue_leaving_is_silent_inside_the_confirmation_window() -> None:
    """The scraper keeps publishing active until it has seen the absence twice."""
    published = [venue("tft-colony", "1", "Colony", status="active")]
    source = {"membership_streaks": [
        {"id": "1", "name": "Colony", "consecutive_present": 0, "consecutive_absent": 1},
    ]}

    faults = parity.find_faults(roster(published, **source), set())

    assert faults == []


def test_a_venue_rejoining_is_silent_inside_the_confirmation_window() -> None:
    published = [venue("tft-colony", "1", "Colony", status="not_listed")]
    source = {"membership_streaks": [
        {"id": "1", "name": "Colony", "consecutive_present": 1, "consecutive_absent": 0},
    ]}

    faults = parity.find_faults(roster(published, **source), {"1"})

    assert faults == []


def test_a_confirmed_absence_past_the_window_is_a_fault() -> None:
    """Once the scraper has had enough observations, disagreement is real."""
    published = [venue("tft-colony", "1", "Colony", status="active")]
    source = {"membership_streaks": [
        {"id": "1", "name": "Colony", "consecutive_present": 0,
         "consecutive_absent": AUTO_MEMBERSHIP_CONFIRMATIONS + 1},
    ]}

    faults = parity.find_faults(roster(published, **source), set())

    assert len(faults) == 1
    assert "no longer lists it" in faults[0].reason


@pytest.mark.parametrize(
    "key",
    ["pending_booking_project_additions", "pending_booking_project_removals",
     "booking_project_review_items"],
)
def test_a_disagreement_the_ledger_already_queued_is_silent(key: str) -> None:
    faults = parity.find_faults(roster([], **{key: [{"id": "1", "name": "New"}]}), {"1"})

    assert faults == []


def test_an_unqueued_absence_from_the_roster_is_a_fault() -> None:
    faults = parity.find_faults(roster([]), {"1"})

    assert len(faults) == 1
    assert "absent from the roster" in faults[0].reason


def test_the_two_legitimately_absent_venues_do_not_fault() -> None:
    """Osteria Mozza and Capitol Bistro are absent from the project and marked so."""
    payload = json.loads((ROOT / "data/table-for-two.json").read_text())
    hidden = [v for v in payload["venues"] if v.get("booking_project_status") == "not_listed"]
    observed = {str(o["id"]) for o in payload["booking_project_source"]["observed_venues"]}

    assert {v["name"] for v in hidden} == {"Osteria Mozza", "Capitol Bistro. Bar. Patisserie"}
    assert all(str(v["dining_city_id"]) not in observed for v in hidden)


def test_a_malformed_row_does_not_count_as_a_member() -> None:
    assert parity.live_member_ids([{"id": 1, "restaurant_id": "1"}]) == set()


def test_the_workflow_runs_the_gate_and_folds_it_into_the_failure_epilogue() -> None:
    workflow = (ROOT / ".github/workflows/refresh-table-for-two.yml").read_text()

    assert "scripts/check_roster_parity.py" in workflow
    assert "PARITY_OUTCOME: ${{ steps.roster_parity.outcome }}" in workflow
    # Without these the step either blocks the run or never reaches the epilogue.
    block = workflow[workflow.index("id: roster_parity"):]
    assert "continue-on-error: true" in block.split("- name:")[0]
    assert " PARITY " in workflow[workflow.index("for stage in"):workflow.index("do\n", workflow.index("for stage in"))]
