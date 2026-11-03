"""Tier changes reach the owner; tier rollout and Centurion-only venues stay quiet elsewhere."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from scripts import check_roster_parity as parity

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("source_change_alert_tiers", ROOT / "scripts/source_change_alert.py")
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)

JAAN, ZYX, ISABEL = "205189592", "205196578", "205194422"


def test_unknown_amex_project_raises_one_signal_then_none() -> None:
    before = {"booking_project_codes": {"known": ["AMEXPlatSG"], "unknown_amex": []}}
    after = {"booking_project_codes": {"known": ["AMEXPlatSG"], "unknown_amex": ["AMEXNewSG"]}}

    first = alerts.meta_change_reasons(before, after)
    again = alerts.meta_change_reasons(after, after)

    assert [r for r in first if r.startswith("Unknown Amex booking projects")] == [
        "Unknown Amex booking projects: `[]` → `['AMEXNewSG']`"
    ]
    assert again == []


def test_centurion_source_changes_are_labelled() -> None:
    before = {"booking_project_sources": {"centurion": {"observed_count": 39}}}
    after = {"booking_project_sources": {"centurion": {"observed_count": 40}}}

    assert alerts.meta_change_reasons(before, after) == ["Centurion booking-project venue count: `39` → `40`"]


def test_gaining_a_tier_is_a_card_change_but_first_tiers_are_not() -> None:
    base = {"id": "tft-vue", "name": "VUE"}

    assert alerts.public_field_changes(base, {**base, "tiers": ["platinum", "centurion"]}) == []
    assert alerts.public_field_changes(
        {**base, "tiers": ["platinum"]}, {**base, "tiers": ["platinum", "centurion"]}
    ) == [{"field": "Cards", "before": ["platinum"], "after": ["platinum", "centurion"]}]


def centurion_payload(venues: list[dict], source: dict | None = None) -> dict:
    return {"venues": venues, "booking_project_sources": {"centurion": source or {}}}


def tier_venue(name: str, diningcity_id: str, centurion: str, membership: str | None = None) -> dict:
    record = {"id": f"tft-{name.lower()}", "name": name, "dining_city_id": diningcity_id,
              "booking_project_status": "active",
              "booking_project_statuses": {"platinum": "active", "centurion": centurion}}
    if membership:
        record["tier_membership"] = {"centurion": membership}
    return record


def test_centurion_parity_excuses_linked_only_and_flags_missing() -> None:
    payload = centurion_payload([
        tier_venue("JAAN", JAAN, "active", "listed"),
        tier_venue("ZYX", ZYX, "active", "linked_only"),
    ])

    faults = parity.find_faults(payload, {JAAN, ISABEL}, tier="centurion")

    assert [str(f) for f in faults] == [
        f"{ISABEL} ({ISABEL}): listed in AMEXCentSG but absent from the roster"
    ]


def test_centurion_parity_flags_published_active_but_unlisted() -> None:
    payload = centurion_payload([tier_venue("JAAN", JAAN, "active", "listed")])

    faults = parity.find_faults(payload, set(), tier="centurion")

    assert [f.reason for f in faults] == ["published as active but AMEXCentSG no longer lists it"]


def test_platinum_parity_is_unchanged_by_default() -> None:
    payload = {"venues": [tier_venue("JAAN", JAAN, "active")], "booking_project_source": {}}

    assert parity.find_faults(payload, {JAAN}) == []


def test_centurion_only_venues_stay_out_of_guide_catalog_and_slot_snapshot() -> None:
    payload = json.loads((ROOT / "data/table-for-two.json").read_text(encoding="utf-8"))
    # The real JAAN record carries its own menu receipt, so a copy is built only when it is absent.
    jaan = next((v for v in payload["venues"] if v["id"] == "tft-jaan-by-kirk-westaway"), None)
    if jaan is None:
        jaan = {**payload["venues"][0], "id": "tft-jaan-by-kirk-westaway", "name": "JAAN By Kirk Westaway",
                "dining_city_id": JAAN, "booking_project_status": "not_listed", "tiers": ["centurion"]}
        payload["venues"].append(jaan)
    assert jaan["tiers"] == ["centurion"] and jaan["booking_project_status"] == "not_listed"

    from scripts import build_tft_guide_catalog, build_tft_slot_snapshot

    catalog = build_tft_guide_catalog.build_catalog(payload)
    snapshot = build_tft_slot_snapshot.build_snapshot(payload)

    assert "tft-jaan-by-kirk-westaway" not in {v["id"] for v in catalog["venues"]}
    assert "tft-jaan-by-kirk-westaway" not in {v["id"] for v in snapshot["venues"]}
