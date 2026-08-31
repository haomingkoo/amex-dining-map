import json
import urllib.error
import unittest
from unittest import mock

from scripts import scrape_table_for_two


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"data": []}).encode("utf-8")


class TableForTwoReliabilityTests(unittest.TestCase):
    def test_booking_project_membership_exposes_early_candidates(self):
        reviewed = [
            {"name": "Known Place", "dining_city_id": "10"},
            {"name": "Dropped Place", "dining_city_id": "20"},
        ]
        payload = [
            {
                "status": "online",
                "availability_project": "AMEXPlatSG",
                "restaurant": {"id": 10, "name": "Known Place", "dirname": "known"},
            },
            {
                "status": "online",
                "availability_project": "AMEXPlatSG",
                "restaurant": {"id": 30, "name": "New Place", "dirname": "new"},
            },
        ]
        with mock.patch.object(scrape_table_for_two, "fetch_json", return_value=payload):
            result = scrape_table_for_two.fetch_booking_project_membership(
                reviewed,
                "2026-08-31T10:00:00Z",
            )

        self.assertEqual(result["observation_status"], "success")
        self.assertEqual(result["observed_count"], 2)
        self.assertEqual(result["added_vs_reviewed_roster"], ["New Place"])
        self.assertEqual(result["missing_vs_reviewed_roster"], ["Dropped Place"])
        self.assertTrue(result["review_required"])

    def test_booking_project_membership_retains_last_good_snapshot_on_error(self):
        previous = {
            "booking_project_source": {
                "observed_count": 27,
                "observed_membership_sha256": "a" * 64,
                "observed_venues": [{"id": "10", "name": "Known Place"}],
            }
        }
        with mock.patch.object(
            scrape_table_for_two,
            "fetch_json",
            side_effect=urllib.error.URLError("temporary"),
        ):
            result = scrape_table_for_two.fetch_booking_project_membership(
                [],
                "2026-08-31T10:00:00Z",
                previous,
            )

        self.assertEqual(result["observation_status"], "error")
        self.assertEqual(result["observation_error"], "URLError")
        self.assertEqual(result["observed_count"], 27)
        self.assertEqual(result["observed_membership_sha256"], "a" * 64)

    def test_fetch_json_retries_transient_network_error(self):
        with (
            mock.patch.object(
                scrape_table_for_two.urllib.request,
                "urlopen",
                side_effect=[urllib.error.URLError("temporary"), FakeResponse()],
            ) as urlopen,
            mock.patch.object(scrape_table_for_two.time, "sleep") as sleep,
        ):
            self.assertEqual(scrape_table_for_two.fetch_json("/test"), {"data": []})

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_live_availability_reports_fallback_failure(self):
        venue = {"id": "test", "dining_city_id": "123"}
        with (
            mock.patch.object(scrape_table_for_two, "has_project", return_value=True),
            mock.patch.object(scrape_table_for_two, "fetch_json", return_value={"data": []}),
            mock.patch.object(
                scrape_table_for_two,
                "fetch_available_dates",
                side_effect=urllib.error.URLError("temporary"),
            ),
        ):
            availability, error = scrape_table_for_two.live_availability_for_venue(
                venue,
                "2026-07-18T00:00:00Z",
            )

        self.assertIsNone(availability)
        self.assertEqual(error, "fallback_URLError: <urlopen error temporary>")

    def test_normalized_venues_preserves_menu_metadata(self):
        venue = scrape_table_for_two.VENUES[0]
        existing = {
            venue["id"]: {
                "menu_pdfs": {"platinum": {"status": "published", "url": "https://example.test/menu.pdf"}},
                "menu_pdf": {"status": "published", "url": "https://example.test/menu.pdf"},
            },
        }

        record = scrape_table_for_two.normalized_venues(existing_by_id=existing)[0]

        self.assertEqual(record["menu_pdfs"], existing[venue["id"]]["menu_pdfs"])
        self.assertEqual(record["menu_pdf"], existing[venue["id"]]["menu_pdf"])


if __name__ == "__main__":
    unittest.main()
