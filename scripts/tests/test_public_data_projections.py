import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_public_data_projections as projections


ROOT = Path(__file__).resolve().parents[2]


class PublicDataProjectionTests(unittest.TestCase):
    def test_tft_ratings_contains_only_exact_venue_ids(self):
        table_for_two = {"venues": [{"id": "tft-a"}, {"id": "tft-b"}]}
        ratings = {
            "tft-a": {"rating": 4.1},
            "tft-b": {"rating": 4.8},
            "unrelated": {"rating": 5.0},
        }

        self.assertEqual(
            projections.tft_ratings_projection(table_for_two, ratings),
            {"tft-a": {"rating": 4.1}, "tft-b": {"rating": 4.8}},
        )

    def test_tft_ratings_fails_closed_when_a_venue_is_missing(self):
        with self.assertRaisesRegex(ValueError, "tft-b"):
            projections.tft_ratings_projection(
                {"venues": [{"id": "tft-a"}, {"id": "tft-b"}]},
                {"tft-a": {"rating": 4.1}},
            )

    def test_release_summary_excludes_raw_observations(self):
        history = {
            "schema_version": 1,
            "source_project": "AMEXPlatSG",
            "updated_at": "2026-08-30T00:00:00Z",
            "patterns": [{"venue_id": "tft-a"}],
            "observations": [{"large": "internal history"}],
        }

        result = projections.release_history_summary(history)

        self.assertEqual(list(result), list(projections.RELEASE_SUMMARY_KEYS))
        self.assertNotIn("observations", result)

    def test_current_data_builds_expected_bounded_outputs(self):
        table_for_two = projections.load_json(ROOT / "data/table-for-two.json")
        ratings = projections.load_json(ROOT / "data/google-maps-ratings.json")
        history = projections.load_json(ROOT / "data/table-for-two-release-history.json")

        tft_ratings = projections.tft_ratings_projection(table_for_two, ratings)
        summary = projections.release_history_summary(history)

        self.assertEqual(len(tft_ratings), 23)
        self.assertEqual(set(tft_ratings), {venue["id"] for venue in table_for_two["venues"]})
        self.assertEqual(len(summary["patterns"]), len(history["patterns"]))
        self.assertNotIn("observations", summary)

    def test_cli_writes_both_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {
                "tft.json": {"venues": [{"id": "tft-a"}]},
                "ratings.json": {"tft-a": {"rating": 4.5}},
                "history.json": {
                    "schema_version": 1,
                    "source_project": "AMEXPlatSG",
                    "updated_at": "2026-08-30T00:00:00Z",
                    "patterns": [],
                    "observations": [{"unused": True}],
                },
            }
            for name, payload in inputs.items():
                (root / name).write_text(json.dumps(payload), encoding="utf-8")

            ratings_output = root / "site/data/tft-ratings.json"
            summary_output = root / "site/data/release-summary.json"
            original_argv = __import__("sys").argv
            try:
                __import__("sys").argv = [
                    "build_public_data_projections.py",
                    "--table-for-two", str(root / "tft.json"),
                    "--ratings", str(root / "ratings.json"),
                    "--release-history", str(root / "history.json"),
                    "--tft-ratings-output", str(ratings_output),
                    "--release-summary-output", str(summary_output),
                ]
                self.assertEqual(projections.main(), 0)
            finally:
                __import__("sys").argv = original_argv

            self.assertEqual(json.loads(ratings_output.read_text()), {"tft-a": {"rating": 4.5}})
            self.assertNotIn("observations", json.loads(summary_output.read_text()))


if __name__ == "__main__":
    unittest.main()
