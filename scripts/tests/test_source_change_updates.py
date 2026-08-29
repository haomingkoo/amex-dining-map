#!/usr/bin/env python3

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "source_change_alert.py"
SPEC = importlib.util.spec_from_file_location("source_change_alert", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SourceChangeUpdatesTest(unittest.TestCase):
    def test_added_record_has_explicit_before_and_after(self):
        events = MODULE.build_record_update_events(
            "Global Dining",
            [],
            [{"id": "venue-1", "name": "New Place", "city": "Singapore", "source_url": "https://example.com"}],
            {},
            "2026-08-30T00:00:00Z",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "added")
        self.assertEqual(events[0]["before"]["state"], "not_listed")
        self.assertEqual(events[0]["after"]["fields"]["Name"], "New Place")
        self.assertEqual(events[0]["changes"][0], {"field": "Listing", "before": "Not listed", "after": "Listed"})

    def test_changed_record_exposes_only_user_relevant_fields(self):
        old = [{"id": "venue-1", "name": "Place", "address": "Old address", "lat": 1.0}]
        new = [{"id": "venue-1", "name": "Place", "address": "New address", "lat": 2.0}]

        events = MODULE.build_record_update_events(
            "Love Dining", old, new, {"manual_review_required": True}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["status"], "review_required")
        self.assertEqual(events[0]["changes"], [{"field": "Address", "before": "Old address", "after": "New address"}])

    def test_menu_hash_change_is_a_menu_update(self):
        old = [{"id": "venue-1", "name": "Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "a" * 64}}]
        new = [{"id": "venue-1", "name": "Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "b" * 64}}]

        events = MODULE.build_record_update_events(
            "Table for Two", old, new, {"manual_review_required": True}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["kind"], "menu_updated")
        self.assertEqual(events[0]["changes"][0]["field"], "Menu version")
        self.assertEqual(events[0]["changes"][0]["before"], "aaaaaaaaaaaa")
        self.assertEqual(events[0]["changes"][0]["after"], "bbbbbbbbbbbb")

    def test_append_updates_deduplicates_stable_events(self):
        event = {
            "id": "same-event",
            "detected_at": "2026-08-30T00:00:00Z",
            "subject": "Place",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [event], "2026-08-30T00:00:00Z")
            MODULE.append_updates(path, [event], "2026-08-30T01:00:00Z")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["updates"]), 1)
        self.assertEqual(payload["updated_at"], "2026-08-30T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
