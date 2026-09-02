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
    def candidate(self):
        return {
            "id": "205196438",
            "name": "Park90",
            "status": "online",
            "availability_project": "AMEXPlatSG",
            "source_url": "https://www.diningcity.sg/singapore/park90",
            "address": "Pan Pacific Orchard, 10 Claymore Road, Singapore 229540",
            "lat": 1.307577,
            "lng": 103.8298732,
        }

    def source_with_streak(self, record, *, present=1, absent=0):
        observed = [record] if present else []
        return {
            "observation_status": "success",
            "checked_at": "2026-09-03T00:15:00Z",
            "observed_count": len(observed),
            "observed_venues": observed,
            "missing_vs_reviewed_roster": [],
            "membership_streaks": [{
                "id": record["id"],
                "name": record["name"],
                "record_sha256": scrape_table_for_two._membership_record_sha256(record),
                "state": "present" if present else "absent",
                "consecutive_present": present,
                "consecutive_absent": absent,
                "first_seen_at": "2026-09-03T00:00:00Z",
                "last_seen_at": "2026-09-03T00:15:00Z" if present else "2026-09-03T00:00:00Z",
            }],
        }

    def test_confirmed_booking_project_additions_publish_once_and_exclude_unknowns(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        observed = [
            {
                "id": venue["dining_city_id"],
                "name": venue["name"],
                "status": "online",
                "availability_project": "AMEXPlatSG",
                "source_url": venue["dining_city_public_url"],
                "address": venue["address"],
                "lat": venue["lat"],
                "lng": venue["lng"],
            }
            for venue in scrape_table_for_two.VENUES
            if venue.get("roster_basis") == "diningcity_booking_project_confirmed"
        ]
        observed.append({"id": "999", "name": "Unreviewed Place"})
        source = {
            "observation_status": "success",
            "checked_at": "2026-09-03T00:15:00Z",
            "observed_venues": observed,
            "membership_streaks": [
                {
                    "id": record["id"],
                    "record_sha256": scrape_table_for_two._membership_record_sha256(record),
                    "consecutive_present": 2,
                }
                for record in observed
            ],
            "missing_vs_reviewed_roster": [],
        }

        roster, annotated = scrape_table_for_two.current_published_roster(reviewed, source)

        self.assertEqual(len(roster), 7)
        self.assertEqual(len({venue["id"] for venue in roster}), 7)
        self.assertEqual(len({venue["dining_city_id"] for venue in roster}), 7)
        self.assertEqual(len(annotated["published_booking_project_additions"]), 6)
        self.assertEqual(annotated["unconfirmed_added_vs_reviewed_roster"], ["Unreviewed Place"])

    def test_confirmed_booking_project_merge_rejects_duplicate_diningcity_identity(self):
        reviewed = [
            {**scrape_table_for_two.VENUES[0], "dining_city_id": "205193590"},
        ]
        source = {"observed_venues": [{"id": "205193590", "name": "Forage"}]}

        roster, _ = scrape_table_for_two.current_published_roster(reviewed, source)

        self.assertEqual(len(roster), 1)

    def test_complete_candidate_waits_for_two_observations_then_auto_publishes(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()

        first, first_source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(candidate, present=1)
        )
        self.assertEqual([venue["name"] for venue in first], [reviewed[0]["name"]])
        self.assertEqual(first_source["pending_booking_project_additions"], [
            {"id": candidate["id"], "name": candidate["name"]}
        ])
        self.assertFalse(first_source["review_required"])

        second, second_source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(candidate, present=2)
        )
        self.assertEqual([venue["name"] for venue in second], [reviewed[0]["name"], "Park90"])
        published = second[1]
        self.assertEqual(published["roster_basis"], "diningcity_booking_project_confirmed")
        self.assertEqual(published["roster_evidence"]["confirmation_count"], 2)
        self.assertEqual(second_source["maintenance_summary"]["pending_addition_count"], 0)

    def test_incomplete_or_duplicate_candidate_stays_review_gated(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        incomplete = {**self.candidate(), "address": "", "lat": None}
        roster, source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(incomplete, present=3)
        )
        self.assertEqual(roster, reviewed)
        self.assertTrue(source["review_required"])
        self.assertEqual(source["unconfirmed_added_vs_reviewed_roster"], ["Park90"])
        self.assertIn("missing_address", source["booking_project_review_items"][0]["reasons"])

        duplicate = {**self.candidate(), "name": reviewed[0]["name"]}
        roster, source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(duplicate, present=3)
        )
        self.assertEqual(roster, reviewed)
        self.assertIn("duplicate_normalized_name", source["booking_project_review_items"][0]["reasons"])

    def test_booking_only_venue_survives_one_miss_and_is_removed_after_two(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        published = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )
        existing = {"venues": [*reviewed, published]}

        retained, first_source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(candidate, present=0, absent=1), existing
        )
        self.assertEqual([venue["name"] for venue in retained], [reviewed[0]["name"], "Park90"])
        self.assertEqual(first_source["pending_booking_project_removals"], [
            {"id": candidate["id"], "name": candidate["name"]}
        ])

        removed, second_source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(candidate, present=0, absent=2), existing
        )
        self.assertEqual(removed, reviewed)
        self.assertEqual(second_source["confirmed_booking_project_removals"], [
            {"id": candidate["id"], "name": candidate["name"]}
        ])

    def test_membership_sequence_requires_two_misses_and_two_hits_after_reappearance(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        present_twice = self.source_with_streak(candidate, present=2)
        published = scrape_table_for_two._auto_venue_from_membership(
            candidate, present_twice["membership_streaks"][0], present_twice["checked_at"]
        )
        existing = {"venues": [*reviewed, published], "booking_project_source": present_twice}

        first_streaks = scrape_table_for_two._membership_streaks(
            [], reviewed, present_twice, "2026-09-03T00:30:00Z"
        )
        self.assertEqual(first_streaks[0]["consecutive_absent"], 1)
        first_source = {
            **present_twice,
            "checked_at": "2026-09-03T00:30:00Z",
            "observed_venues": [],
            "membership_streaks": first_streaks,
        }
        retained, _ = scrape_table_for_two.current_published_roster(
            reviewed, first_source, existing
        )
        self.assertIn("Park90", [venue["name"] for venue in retained])

        second_streaks = scrape_table_for_two._membership_streaks(
            [], reviewed, first_source, "2026-09-03T00:45:00Z"
        )
        self.assertEqual(second_streaks[0]["consecutive_absent"], 2)
        second_source = {
            **first_source,
            "checked_at": "2026-09-03T00:45:00Z",
            "membership_streaks": second_streaks,
        }
        removed, _ = scrape_table_for_two.current_published_roster(
            reviewed, second_source, existing
        )
        self.assertNotIn("Park90", [venue["name"] for venue in removed])

        reappeared_once = scrape_table_for_two._membership_streaks(
            [candidate], reviewed, second_source, "2026-09-03T01:00:00Z"
        )
        self.assertEqual(reappeared_once[0]["consecutive_present"], 1)
        reappeared_source = {
            **second_source,
            "checked_at": "2026-09-03T01:00:00Z",
            "observed_venues": [candidate],
            "membership_streaks": reappeared_once,
        }
        pending, _ = scrape_table_for_two.current_published_roster(
            reviewed, reappeared_source, {"venues": reviewed}
        )
        self.assertNotIn("Park90", [venue["name"] for venue in pending])

        reappeared_twice = scrape_table_for_two._membership_streaks(
            [candidate], reviewed, reappeared_source, "2026-09-03T01:15:00Z"
        )
        self.assertEqual(reappeared_twice[0]["consecutive_present"], 2)

    def test_offline_existing_supplement_counts_as_absent(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        previous = self.source_with_streak(candidate, present=2)
        offline = {**candidate, "status": "offline"}

        streaks = scrape_table_for_two._membership_streaks(
            [offline], reviewed, previous, "2026-09-03T00:30:00Z"
        )

        self.assertEqual(streaks[0]["state"], "absent")
        self.assertEqual(streaks[0]["consecutive_absent"], 1)

    def test_configured_candidate_uses_curated_location_when_feed_row_is_sparse(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        configured = next(
            venue
            for venue in scrape_table_for_two.VENUES
            if venue.get("roster_basis") == "diningcity_booking_project_confirmed"
        )
        sparse = {
            "id": configured["dining_city_id"],
            "name": configured["name"],
            "status": "online",
            "availability_project": "AMEXPlatSG",
            "source_url": configured["dining_city_public_url"],
            "address": "",
            "lat": None,
            "lng": None,
        }

        roster, source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(sparse, present=2)
        )

        self.assertIn(configured["name"], [venue["name"] for venue in roster])
        self.assertEqual(source["booking_project_review_items"], [])

    def test_source_error_does_not_duplicate_supplement_absorbed_by_official_roster(self):
        official = {**scrape_table_for_two.VENUES[0], "id": "tft-park90", "dining_city_id": "205196438"}
        candidate = self.candidate()
        supplement = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )

        roster, _ = scrape_table_for_two.current_published_roster(
            [official], {"observation_status": "error"}, {"venues": [supplement]}
        )

        self.assertEqual(roster, [official])

    def test_reducer_rejects_duplicate_observed_and_existing_identities(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        duplicate_source = self.source_with_streak(candidate, present=2)
        duplicate_source["observed_venues"] = [candidate, candidate]
        with self.assertRaisesRegex(ValueError, "duplicate DiningCity IDs"):
            scrape_table_for_two.current_published_roster(reviewed, duplicate_source)

        supplement = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )
        with self.assertRaisesRegex(ValueError, "duplicate identities"):
            scrape_table_for_two.current_published_roster(
                reviewed,
                {"observation_status": "error"},
                {"venues": [supplement, supplement]},
            )

    def test_source_error_retains_existing_booking_only_venues(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        published = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )
        roster, source = scrape_table_for_two.current_published_roster(
            reviewed,
            {"observation_status": "error", "observation_error": "URLError"},
            {"venues": [*reviewed, published]},
        )
        self.assertEqual([venue["name"] for venue in roster], [reviewed[0]["name"], "Park90"])
        self.assertEqual(source["maintenance_summary"]["outcome"], "retained_after_source_error")

    def test_changed_auto_published_source_identity_is_retained_for_review(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        published = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )
        changed = {**candidate, "address": "Unexpected replacement address"}

        roster, source = scrape_table_for_two.current_published_roster(
            reviewed,
            self.source_with_streak(changed, present=3),
            {"venues": [*reviewed, published]},
        )

        retained = next(venue for venue in roster if venue["name"] == "Park90")
        self.assertEqual(retained["address"], candidate["address"])
        self.assertTrue(source["review_required"])
        self.assertEqual(source["identity_mismatch_count"], 1)
        self.assertEqual(
            source["booking_project_review_items"][0]["reasons"],
            ["published_source_record_changed"],
        )

    def test_legacy_supplement_hash_is_bootstrapped_only_from_unchanged_prior_record(self):
        reviewed = [scrape_table_for_two.VENUES[0]]
        candidate = self.candidate()
        legacy = scrape_table_for_two._auto_venue_from_membership(
            candidate,
            self.source_with_streak(candidate, present=2)["membership_streaks"][0],
            "2026-09-03T00:15:00Z",
        )
        legacy.pop("roster_evidence")
        existing = {
            "venues": [*reviewed, legacy],
            "booking_project_source": {"observed_venues": [candidate]},
        }

        roster, source = scrape_table_for_two.current_published_roster(
            reviewed, self.source_with_streak(candidate, present=3), existing
        )

        retained = next(venue for venue in roster if venue["name"] == "Park90")
        self.assertEqual(
            retained["roster_evidence"]["record_sha256"],
            scrape_table_for_two._membership_record_sha256(candidate),
        )
        self.assertEqual(source["booking_project_review_items"], [])

    def test_fast_refresh_uses_same_two_scan_reducer_and_preserves_menu_metadata(self):
        official = {
            **scrape_table_for_two.VENUES[0],
            "booking_project_status": "active",
            "menu_pdf": {"status": "published", "url": "https://www.americanexpress.com/menu.pdf"},
        }
        candidate = self.candidate()
        initial = {"venues": [official], "booking_project_source": {}}
        first_source = self.source_with_streak(candidate, present=1)
        second_source = self.source_with_streak(candidate, present=2)

        with (
            mock.patch.object(
                scrape_table_for_two,
                "fetch_booking_project_membership",
                side_effect=[first_source, second_source],
            ),
            mock.patch.object(scrape_table_for_two, "fetch_live_availability", return_value=({}, {})),
        ):
            first = scrape_table_for_two.refresh_availability_payload(initial)
            self.assertNotIn("Park90", [venue["name"] for venue in first["venues"]])
            second = scrape_table_for_two.refresh_availability_payload(first)

        park90 = next(venue for venue in second["venues"] if venue["name"] == "Park90")
        self.assertEqual(park90["booking_project_status"], "active")
        self.assertEqual(park90["roster_evidence"]["confirmation_count"], 2)
        self.assertEqual(second["venues"][0]["menu_pdf"], official["menu_pdf"])
        self.assertEqual(second["booking_project_source"]["maintenance_summary"]["outcome"], "success")

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

    def test_membership_streak_bootstraps_the_previous_legacy_snapshot(self):
        candidate = self.candidate()
        previous_record = {
            key: candidate[key]
            for key in ("id", "name", "status", "availability_project", "source_url")
        }
        payload = [{
            "status": candidate["status"],
            "availability_project": candidate["availability_project"],
            "restaurant": {
                "id": candidate["id"],
                "name": candidate["name"],
                "dirname": "park90",
                "address": candidate["address"],
                "lat": candidate["lat"],
                "lng": candidate["lng"],
            },
        }]
        previous = {
            "booking_project_source": {
                "observation_status": "success",
                "observed_venues": [previous_record],
            }
        }

        with mock.patch.object(scrape_table_for_two, "fetch_json", return_value=payload):
            result = scrape_table_for_two.fetch_booking_project_membership(
                [], "2026-09-03T00:15:00Z", previous
            )

        streak = next(item for item in result["membership_streaks"] if item["id"] == candidate["id"])
        self.assertEqual(streak["consecutive_present"], 2)

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

    def test_booking_project_membership_fails_closed_on_malformed_row(self):
        previous = {
            "booking_project_source": {
                "observed_count": 1,
                "observed_membership_sha256": "a" * 64,
                "observed_venues": [self.candidate()],
            }
        }
        with mock.patch.object(scrape_table_for_two, "fetch_json", return_value=[{"status": "online"}]):
            result = scrape_table_for_two.fetch_booking_project_membership(
                [], "2026-09-03T00:15:00Z", previous
            )
        self.assertEqual(result["observation_status"], "error")
        self.assertEqual(result["observation_error"], "ValueError")
        self.assertEqual(result["observed_count"], 1)

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
