import json
import unittest
from pathlib import Path

from scripts import scrape_table_for_two


DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "table-for-two.json"


class TableForTwoDataTests(unittest.TestCase):
    # Deploy gate: assert the review invariant, never that no review is pending.
    def test_unrecognized_faq_raises_global_review_flag(self):
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))

        self.assertIsInstance(payload["manual_review_required"], bool)
        if payload["source_documents"]["faq_sha256"] != scrape_table_for_two.KNOWN_FAQ_SHA256:
            self.assertTrue(payload["manual_review_required"])

    def test_every_venue_has_menu_metadata(self):
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        venues = payload.get("venues") or []

        self.assertTrue(venues)
        for venue in venues:
            with self.subTest(venue=venue.get("name")):
                self.assertIsInstance(venue.get("menu_pdfs"), dict)
                self.assertIn(
                    (venue.get("menu_pdf") or {}).get("status"),
                    {"published", "buffet_no_menu_expected", "no_pdf_found", "review_required"},
                )

        published = [venue for venue in venues if (venue.get("menu_pdf") or {}).get("status") == "published"]
        self.assertTrue(published)
        for venue in published:
            self.assertTrue((venue.get("menu_pdf") or {}).get("url"))
            self.assertTrue(venue.get("menu_pdfs"))

        by_name = {venue["name"]: venue for venue in venues}
        # Roster churn must not fail the deploy gate, so only check venues still listed.
        expected = {
            "Colony": "buffet_no_menu_expected",
            "Estate": "buffet_no_menu_expected",
            "Peppermint": "buffet_no_menu_expected",
            "Ginger": "buffet_no_menu_expected",
            "One-Ninety": "buffet_no_menu_expected",
        }
        for name, status in expected.items():
            if name in by_name:
                self.assertEqual(by_name[name]["menu_pdf"]["status"], status)


if __name__ == "__main__":
    unittest.main()
