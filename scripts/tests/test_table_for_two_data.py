import json
import unittest
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "table-for-two.json"


class TableForTwoDataTests(unittest.TestCase):
    def test_every_venue_has_menu_metadata(self):
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        venues = payload.get("venues") or []

        self.assertTrue(venues)
        for venue in venues:
            with self.subTest(venue=venue.get("name")):
                self.assertIsInstance(venue.get("menu_pdfs"), dict)
                self.assertIn(
                    (venue.get("menu_pdf") or {}).get("status"),
                    {"published", "buffet_no_menu_expected", "no_pdf_found"},
                )

        published = [venue for venue in venues if (venue.get("menu_pdf") or {}).get("status") == "published"]
        self.assertTrue(published)
        for venue in published:
            self.assertTrue((venue.get("menu_pdf") or {}).get("url"))
            self.assertTrue(venue.get("menu_pdfs"))

        by_name = {venue["name"]: venue for venue in venues}
        for buffet in ("Colony", "Estate", "Peppermint", "Ginger"):
            self.assertEqual(
                by_name[buffet]["menu_pdf"]["status"],
                "buffet_no_menu_expected",
            )
        self.assertEqual(by_name["One-Ninety"]["menu_pdf"]["status"], "no_pdf_found")


if __name__ == "__main__":
    unittest.main()
