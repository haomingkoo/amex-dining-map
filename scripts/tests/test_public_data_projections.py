import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_public_data_projections as projections


ROOT = Path(__file__).resolve().parents[2]

# Observed ~4.7KB/venue. Generous enough for real growth, tight enough that a
# projection leaking bulk back in still trips it.
MAX_CATALOG_BYTES_PER_VENUE = 12_000


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

    def test_tft_ratings_omits_a_venue_that_has_no_rating_yet(self):
        """A newly listed venue must not block the whole site from deploying.

        Ratings are a weekly enrichment, so every roster addition spends up to a
        week unrated. Demanding full coverage here blocked 22 Deploy Pages runs
        over two days when Xing Yue Xuan joined. The frontend already renders a
        missing rating as null, love-dining already ships unrated venues, and
        source health already reports ratings coverage.
        """
        projected = projections.tft_ratings_projection(
            {"venues": [{"id": "tft-a"}, {"id": "tft-b"}]},
            {"tft-a": {"rating": 4.1}},
        )

        self.assertEqual(projected, {"tft-a": {"rating": 4.1}})

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

    def test_tft_catalog_moves_availability_out_of_venue_records(self):
        source = {
            "dataset": "table_for_two",
            "venues": [
                {
                    "id": "tft-a",
                    "name": "A",
                    "dining_city_id": "1",
                    "menu_pdfs": {"platinum": {"status": "published"}},
                    "availability": {"meals": [{"slots": [{"date": "2026-09-03"}]}]},
                }
            ],
        }

        result = projections.tft_catalog_projection(source)

        self.assertEqual(result["dataset"], "table_for_two")
        self.assertEqual(result["venues"][0]["menu_pdfs"], source["venues"][0]["menu_pdfs"])
        self.assertNotIn("availability", result["venues"][0])
        self.assertIn("availability", source["venues"][0])

    def test_tft_catalog_rejects_duplicate_diningcity_ids(self):
        with self.assertRaisesRegex(ValueError, "DiningCity"):
            projections.tft_catalog_projection({
                "venues": [
                    {"id": "tft-a", "dining_city_id": "1"},
                    {"id": "tft-b", "dining_city_id": "1"},
                ]
            })

    def test_current_data_builds_expected_bounded_outputs(self):
        table_for_two = projections.load_json(ROOT / "data/table-for-two.json")
        ratings = projections.load_json(ROOT / "data/google-maps-ratings.json")
        history = projections.load_json(ROOT / "data/table-for-two-release-history.json")

        tft_ratings = projections.tft_ratings_projection(table_for_two, ratings)
        catalog = projections.tft_catalog_projection(table_for_two)
        summary = projections.release_history_summary(history)

        # Bounded by the roster, not equal to it: a venue listed since the last
        # weekly ratings run is legitimately unrated and must not fail the build.
        roster_ids = {venue["id"] for venue in table_for_two["venues"]}
        self.assertTrue(set(tft_ratings).issubset(roster_ids))
        self.assertTrue(tft_ratings)
        self.assertEqual(len(summary["patterns"]), len(history["patterns"]))
        self.assertNotIn("observations", summary)
        self.assertTrue(all("availability" not in venue for venue in catalog["venues"]))
        # Per venue, not total. A fixed ceiling on a growing roster is a timer:
        # this one sat at 56% and would have blocked every deploy about 23
        # venues from now, the same way one unrated venue blocked them for two
        # days on 2026-09-11. Per-venue still catches the regression that
        # matters, a projection that starts carrying slots or other bulk again.
        catalog_bytes = len(json.dumps(catalog, separators=(",", ":")).encode())
        self.assertLess(catalog_bytes / len(catalog["venues"]), MAX_CATALOG_BYTES_PER_VENUE)

    def test_cli_writes_both_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {
                "tft.json": {"venues": [{"id": "tft-a", "dining_city_id": "1"}]},
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
            catalog_output = root / "site/data/tft-catalog.json"
            summary_output = root / "site/data/release-summary.json"
            original_argv = __import__("sys").argv
            try:
                __import__("sys").argv = [
                    "build_public_data_projections.py",
                    "--table-for-two", str(root / "tft.json"),
                    "--ratings", str(root / "ratings.json"),
                    "--release-history", str(root / "history.json"),
                    "--tft-catalog-output", str(catalog_output),
                    "--tft-ratings-output", str(ratings_output),
                    "--release-summary-output", str(summary_output),
                ]
                self.assertEqual(projections.main(), 0)
            finally:
                __import__("sys").argv = original_argv

            self.assertEqual(json.loads(ratings_output.read_text()), {"tft-a": {"rating": 4.5}})
            self.assertNotIn("availability", json.loads(catalog_output.read_text())["venues"][0])
            self.assertNotIn("observations", json.loads(summary_output.read_text()))


if __name__ == "__main__":
    unittest.main()
