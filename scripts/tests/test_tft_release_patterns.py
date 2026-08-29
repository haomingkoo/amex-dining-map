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
