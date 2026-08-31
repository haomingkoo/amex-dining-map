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

    def test_normalized_venues_marks_missing_project_member_not_listed(self):
        venue = scrape_table_for_two.VENUES[0]
        source = {
            "observation_status": "success",
            "checked_at": "2026-09-01T00:00:00Z",
            "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
            "observed_venues": [],
        }

        record = scrape_table_for_two.normalized_venues(
            roster=[venue], booking_project_source=source
        )[0]

        self.assertEqual(record["booking_project_status"], "not_listed")
        self.assertEqual(record["slot_source_status"], "not_currently_in_project")
        self.assertEqual(record["availability"]["status"], "not_currently_in_project")
        self.assertIn("not currently listed", record["availability"]["summary"])

    def test_normalized_venues_keeps_observed_project_member_active(self):
        venue = scrape_table_for_two.VENUES[0]
        source = {
            "observation_status": "success",
            "checked_at": "2026-09-01T00:00:00Z",
            "observed_venues": [{"id": venue["dining_city_id"], "name": venue["name"]}],
        }

        record = scrape_table_for_two.normalized_venues(
            roster=[venue], booking_project_source=source
        )[0]

        self.assertEqual(record["booking_project_status"], "active")
        self.assertNotEqual(record["availability"]["status"], "not_currently_in_project")

    def test_only_officially_sourced_capitol_closure_is_preserved(self):
        venues = [
            venue
            for venue in scrape_table_for_two.VENUES
            if venue["id"] in {"tft-capitol-bistro-bar-patisserie", "tft-osteria-mozza"}
        ]
        source = {
            "observation_status": "success",
            "checked_at": "2026-09-01T00:00:00Z",
            "observed_venues": [],
        }

        records = {
            record["id"]: record
            for record in scrape_table_for_two.normalized_venues(
                roster=venues, booking_project_source=source
            )
        }

        assert records["tft-capitol-bistro-bar-patisserie"]["operational_status"] == "permanently_closed"
        assert "operational_status" not in records["tft-osteria-mozza"]

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
