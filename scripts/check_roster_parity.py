#!/usr/bin/env python3
"""Fail when the published Table for Two roster disagrees with the live project.

On 2026-09-02 a misread field hid six venues and deleted Forage while all seven
stayed online in the AMEXPlatSG project. Nothing compared our output to the
source, so it went unnoticed for two days. This is that comparison.

The hard part is staying quiet. The scraper deliberately debounces membership
over AUTO_MEMBERSHIP_CONFIRMATIONS observations and parks incomplete venues in a
review queue, so a raw set difference reports faults on a perfectly healthy run.
Every disagreement the roster ledger already accounts for is expected; only an
unexplained one is the bug.

    python3 scripts/check_roster_parity.py
    python3 scripts/check_roster_parity.py --membership local.json   # no network
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.scrape_table_for_two import (
        AUTO_MEMBERSHIP_CONFIRMATIONS,
        DININGCITY_PROJECT,
        _booking_project_record,
        _eligible_membership_record,
        fetch_json,
    )
except ImportError:  # running as `python3 scripts/check_roster_parity.py`
    from scrape_table_for_two import (
        AUTO_MEMBERSHIP_CONFIRMATIONS,
        DININGCITY_PROJECT,
        _booking_project_record,
        _eligible_membership_record,
        fetch_json,
    )

DEFAULT_ROSTER = Path("data/table-for-two.json")
PROJECT_PAGE_SIZE = 100


@dataclass(frozen=True)
class Fault:
    venue_id: str
    name: str
    reason: str

    def __str__(self) -> str:
        return f"{self.name} ({self.venue_id}): {self.reason}"


def live_member_ids(rows: list) -> set[str]:
    """DiningCity ids that count as project membership, by the scraper's own rule."""
    members = set()
    for row in rows:
        try:
            record = _booking_project_record(row)
        except ValueError:
            # A malformed row is the scraper's problem to report, not a parity fault.
            continue
        if _eligible_membership_record(record):
            members.add(record["id"])
    return members


def _accounted_for(source: dict) -> set[str]:
    """DiningCity ids the roster ledger already explains a disagreement for."""
    accounted: set[str] = set()
    for key in (
        "pending_booking_project_additions",
        "pending_booking_project_removals",
        "booking_project_review_items",
    ):
        for entry in source.get(key) or []:
            if entry.get("id"):
                accounted.add(str(entry["id"]))
    # A venue inside the confirmation window has not been decided yet either way.
    for streak in source.get("membership_streaks") or []:
        present = int(streak.get("consecutive_present") or 0)
        absent = int(streak.get("consecutive_absent") or 0)
        if 0 < present < AUTO_MEMBERSHIP_CONFIRMATIONS or 0 < absent < AUTO_MEMBERSHIP_CONFIRMATIONS:
            if streak.get("id"):
                accounted.add(str(streak["id"]))
    return accounted


def find_faults(payload: dict, members: set[str]) -> list[Fault]:
    """Unexplained disagreements between what we publish and what the project lists."""
    source = payload.get("booking_project_source") or {}
    excused = _accounted_for(source)
    faults = []

    published_ids = set()
    for venue in payload.get("venues") or []:
        diningcity_id = str(venue.get("dining_city_id") or "")
        if not diningcity_id:
            continue
        published_ids.add(diningcity_id)
        if diningcity_id in excused:
            continue
        hidden = venue.get("booking_project_status") == "not_listed"
        listed = diningcity_id in members
        if listed and hidden:
            faults.append(Fault(str(venue.get("id")), str(venue.get("name")),
                                f"listed in {DININGCITY_PROJECT} but published as not_listed"))
        elif not listed and not hidden:
            faults.append(Fault(str(venue.get("id")), str(venue.get("name")),
                                f"published as active but {DININGCITY_PROJECT} no longer lists it"))

    for diningcity_id in sorted(members - published_ids - excused):
        faults.append(Fault(diningcity_id, diningcity_id,
                            f"listed in {DININGCITY_PROJECT} but absent from the roster"))
    return faults


def fetch_membership() -> list:
    rows = fetch_json(
        f"/projects/{DININGCITY_PROJECT}/restaurants", {"per_page": PROJECT_PAGE_SIZE}
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("booking project membership is empty or not a list")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--membership", type=Path, help="read the live rows from a file instead")
    args = parser.parse_args(argv)

    payload = json.loads(args.roster.read_text(encoding="utf-8"))
    rows = (
        json.loads(args.membership.read_text(encoding="utf-8"))
        if args.membership
        else fetch_membership()
    )
    members = live_member_ids(rows)
    faults = find_faults(payload, members)

    print(f"roster parity: {len(payload.get('venues') or [])} published, {len(members)} listed live")
    if not faults:
        print("roster parity: OK")
        return 0
    for fault in faults:
        print(f"::error::roster parity: {fault}", file=sys.stderr)
    print(f"roster parity: {len(faults)} unexplained disagreement(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
