#!/usr/bin/env python3

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "track_table_for_two_releases.py"
SPEC = importlib.util.spec_from_file_location("track_table_for_two_releases", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ReleasePatternTest(unittest.TestCase):
    def test_only_amex_platinum_project_is_recorded(self):
        payload = {
            "availability_source": {"project": "AMEXPlatSG"},
            "availability_last_checked_at": "2026-08-30T01:00:00Z",
            "venues": [
                {
                    "id": "venue-1",
                    "name": "Venue",
                    "availability": {
                        "project": "GenericDiningCity",
                        "meals": [{"meal": "Dinner", "dates": ["2026-09-30"]}],
                    },
                },
                {
                    "id": "venue-2",
                    "name": "Venue 2",
                    "availability": {
                        "project": "AMEXPlatSG",
                        "meals": [{"meal": "Dinner", "dates": ["2026-09-30"]}],
                    },
                },
            ],
        }
        history = {"schema_version": 1, "observations": []}

        self.assertEqual(MODULE.append_current(payload, history), 1)
        self.assertEqual(history["source_project"], "AMEXPlatSG")
        self.assertEqual(history["observations"][0]["venue_id"], "venue-2")

    def test_generic_top_level_project_is_rejected(self):
        payload = {
            "availability_source": {"project": "GenericDiningCity"},
            "availability_last_checked_at": "2026-08-30T01:00:00Z",
            "venues": [],
        }

        with self.assertRaisesRegex(ValueError, "AMEXPlatSG"):
            MODULE.append_current(payload, {"observations": []})

    def test_nonempty_history_without_provenance_cannot_be_relabelled(self):
        payload = {
            "availability_source": {"project": "AMEXPlatSG"},
            "availability_last_checked_at": "2026-08-30T01:00:00Z",
            "venues": [],
        }
        history = {"observations": [{"id": "untrusted-old-row"}]}

        with self.assertRaisesRegex(ValueError, "existing release history"):
            MODULE.append_current(payload, history)

        self.assertNotIn("source_project", history)

    def test_nonempty_history_with_wrong_provenance_cannot_be_relabelled(self):
        payload = {
            "availability_source": {"project": "AMEXPlatSG"},
            "availability_last_checked_at": "2026-08-30T01:00:00Z",
            "venues": [],
        }
        history = {
            "source_project": "GenericDiningCity",
            "observations": [{"id": "untrusted-old-row"}],
        }

        with self.assertRaisesRegex(ValueError, "existing release history"):
            MODULE.append_current(payload, history)

        self.assertEqual(history["source_project"], "GenericDiningCity")

    def test_observation_records_lead_time(self):
        item = MODULE.build_observation(
            ("venue-1", "Venue", "Dinner", "2026-09-30"),
            datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(item["lead_days"], 31)
        self.assertEqual(item["first_seen_sgt"], "2026-08-30 09:00")

    def test_pattern_requires_three_non_baseline_observations(self):
        observations = [
            {
                "venue_id": "venue-1",
                "venue_name": "Venue",
                "meal": "Dinner",
                "lead_days": 30,
                "first_seen_sgt": f"2026-08-{day:02d} 10:05",
            }
            for day in (1, 2, 3)
        ]
        patterns = MODULE.build_patterns(observations)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["median_lead_days"], 30.0)
        self.assertEqual(patterns[0]["typical_first_seen_sgt"], "10:00")
        self.assertEqual(patterns[0]["confidence"], "early")

    def test_inconsistent_check_times_are_not_presented_as_release_time(self):
        observations = [
            {
                "venue_id": "venue-1",
                "venue_name": "Venue",
                "meal": "Dinner",
                "lead_days": 30,
                "first_seen_sgt": value,
            }
            for value in ("2026-08-01 01:05", "2026-08-02 02:05", "2026-08-03 03:05")
        ]
        patterns = MODULE.build_patterns(observations)
        self.assertIsNone(patterns[0]["typical_first_seen_sgt"])


if __name__ == "__main__":
    unittest.main()
