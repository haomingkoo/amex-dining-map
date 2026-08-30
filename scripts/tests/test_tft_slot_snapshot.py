from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "build_tft_slot_snapshot.py"
SPEC = importlib.util.spec_from_file_location("build_tft_slot_snapshot", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _source() -> dict:
    return json.loads((ROOT / "data" / "table-for-two.json").read_text())


def test_projection_matches_current_source_and_is_bounded():
    projected = MODULE.build_snapshot(_source())
    stored = json.loads((ROOT / "data" / "table-for-two-slots.json").read_text())

    assert projected == stored
    assert projected["source_project"] == "AMEXPlatSG"
    assert len(projected["venues"]) == 23
    assert len(json.dumps(projected, separators=(",", ":")).encode()) < 1_000_000


def test_vue_projection_preserves_exact_slot_facts():
    source = _source()
    projected = MODULE.build_snapshot(source)
    source_vue = next(venue for venue in source["venues"] if venue["id"] == "tft-vue")
    source_availability = source_vue["availability"]
    vue = next(venue for venue in projected["venues"] if venue["id"] == "tft-vue")

    assert vue["project"] == "AMEXPlatSG"
    assert vue["status"] == "live_available"
    assert vue["checked_at"] == source_availability["checked_at"]
    assert vue["meals"] == [
        {
            "meal": meal["meal"],
            "status": meal["status"],
            "slots": [
                {
                    "date": slot["date"],
                    "time": slot["time"],
                    "max_seats": slot["max_seats"],
                }
                for slot in meal["slots"]
            ],
        }
        for meal in source_availability["meals"]
    ]


def test_wrong_top_level_project_fails_closed():
    source = _source()
    source["availability_source"]["project"] = "GenericDiningCity"

    with pytest.raises(ValueError, match="AMEXPlatSG"):
        MODULE.build_snapshot(source)


def test_per_venue_project_is_not_laundered():
    source = _source()
    vue = next(venue for venue in source["venues"] if venue["id"] == "tft-vue")
    vue["availability"]["project"] = "GenericDiningCity"

    projected = MODULE.build_snapshot(source)
    stored = next(venue for venue in projected["venues"] if venue["id"] == "tft-vue")

    assert stored["project"] == "GenericDiningCity"
