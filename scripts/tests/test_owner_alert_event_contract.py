from __future__ import annotations

import importlib.util
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reminders"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.owner_alerts import OwnerAlertEvent
from scripts import source_health as SOURCE_HEALTH


SOURCE_ALERT_PATH = ROOT / "scripts" / "source_change_alert.py"
SPEC = importlib.util.spec_from_file_location("source_change_alert", SOURCE_ALERT_PATH)
SOURCE_ALERT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(SOURCE_ALERT)

def _load(name: str):
    return json.loads((ROOT / "data" / name).read_text())


def _programs():
    return [
        (
            "Global Dining",
            _load("global-restaurants.json")[0],
            _load("global-dining-source.json"),
        ),
        (
            "Japan Dining",
            _load("japan-restaurants.json")[0],
            _load("japan-dining-source.json"),
        ),
        (
            "Plat Stay",
            _load("plat-stays.json")[0],
            _load("plat-stay-source.json"),
        ),
        (
            "Love Dining",
            _load("love-dining.json")[0],
            _load("love-dining-source.json"),
        ),
        (
            "Table for Two",
            _load("table-for-two.json")["venues"][0],
            _load("table-for-two.json"),
        ),
    ]


def test_current_program_records_produce_valid_add_remove_and_detail_events():
    programs = _programs()

    for program, record, meta in programs:
        added = SOURCE_ALERT.build_record_update_events(
            program,
            [],
            [record],
            meta,
            "2026-08-30T00:00:00Z",
        )
        removed = SOURCE_ALERT.build_record_update_events(
            program,
            [record],
            [],
            meta,
            "2026-08-30T00:00:00Z",
        )
        changed_record = copy.deepcopy(record)
        changed_record["name"] = f"{record['name']} updated"
        changed = SOURCE_ALERT.build_record_update_events(
            program,
            [record],
            [changed_record],
            meta,
            "2026-08-30T00:00:00Z",
        )

        assert [len(added), len(removed), len(changed)] == [1, 1, 1]
        for event in [*added, *removed, *changed]:
            OwnerAlertEvent.model_validate(event)


def test_current_program_metadata_produces_valid_source_events():
    for program, _record, current_meta in _programs():
        old_meta = copy.deepcopy(current_meta)
        old_meta["record_count"] = -1

        event = SOURCE_ALERT.build_meta_update_event(
            program,
            old_meta,
            current_meta,
            "2026-08-30T00:00:00Z",
        )

        assert event is not None
        OwnerAlertEvent.model_validate(event)


def test_current_tft_menu_change_produces_valid_event():
    payload = _load("table-for-two.json")
    record = payload["venues"][0]
    changed_record = copy.deepcopy(record)
    changed_record["menu_pdf"]["sha256"] = "a" * 64

    event = SOURCE_ALERT.build_record_update_events(
        "Table for Two",
        [record],
        [changed_record],
        payload,
        "2026-08-30T00:00:00Z",
    )[0]

    validated = OwnerAlertEvent.model_validate(event)
    assert validated.kind == "menu_updated"


def test_current_list_valued_cuisines_are_preserved():
    record = _load("global-restaurants.json")[0]
    event = SOURCE_ALERT.build_record_update_events(
        "Global Dining",
        [],
        [record],
        _load("global-dining-source.json"),
        "2026-08-30T00:00:00Z",
    )[0]

    validated = OwnerAlertEvent.model_validate(event)

    assert validated.after.fields["Cuisine"] == record["cuisines"]


def test_coverage_health_transition_matches_owner_contract():
    base = {
        "id": "table-for-two-availability",
        "label": "Table for Two availability",
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": "#/table-for-two",
        "state": "current",
        "freshness_state": "current",
        "review_state": "clear",
        "failure_state": "clear",
        "stale_record_count": 0,
        "error_count": 0,
        "review_count": 0,
        "coverage": {"covered": 27, "total": 27, "unavailable": 0, "percent": 100.0},
        "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
    }
    changed = {
        **base,
        "coverage": {"covered": 26, "total": 27, "unavailable": 1, "percent": 96.3},
        "source_url": None,
    }

    event = SOURCE_HEALTH.build_transition_events(
        {"sources": [base]}, {"sources": [changed]}, "2026-09-03T00:00:00Z"
    )[0]

    OwnerAlertEvent.model_validate(event)
