#!/usr/bin/env python3

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("source_health", SCRIPTS / "source_health.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


class SourceHealthTest(unittest.TestCase):
    def write(self, root, name, payload):
        (root / name).write_text(json.dumps(payload), encoding="utf-8")

    def fixture(self, root):
        current = "2026-08-30T11:00:00Z"
        self.write(root, "global-dining-source.json", {"fetched_at": current, "record_count": 2, "failed_count": 0})
        self.write(root, "japan-dining-source.json", {"fetched_at": current, "record_count": 2})
        self.write(root, "plat-stay-source.json", {"fetched_at": current, "record_count": 2})
        self.write(root, "love-dining-source.json", {"last_checked_at": current, "record_count": 2, "official_pages": {"a": "https://example.com"}})
        self.write(root, "global-restaurants.json", [{"id": "global-1"}, {"id": "global-2"}])
        self.write(root, "japan-restaurants.json", [{"id": "japan-1", "external_signals": {"tabelog": {"last_checked_at": "2026-08-30"}}}, {"id": "japan-2"}])
        self.write(root, "love-dining.json", [{"id": "love-1"}, {"id": "love-2"}])
        self.write(root, "plat-stays.json", [{"id": "stay-1"}, {"id": "stay-2"}])
        self.write(root, "table-for-two.json", {"last_verified_at": current, "official_url": "https://example.com/tft", "venues": [{"id": "tft-1"}, {"id": "tft-2"}], "menu_source": {"checked_at": current, "venues_matched": 2}})
        self.write(root, "table-for-two-slots.json", {"venues": [{"id": "tft-1", "checked_at": current, "status": "live_available"}, {"id": "tft-2", "checked_at": current, "status": "live_no_seats"}]})
        self.write(root, "google-maps-ratings.json", {"a": {"scraped_at": "2026-08-30"}})
        self.write(root, "restaurant-quality-signals.json", {})

    def test_builds_all_primary_and_enrichment_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            payload = MODULE.build_source_health(root, NOW)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["sources"]), 9)
        self.assertEqual([s["kind"] for s in payload["sources"]].count("primary"), 6)
        self.assertEqual([s["kind"] for s in payload["sources"]].count("enrichment"), 3)
        self.assertTrue(all(
            s["freshness_state"] == "current"
            for s in payload["sources"]
            if s["id"] not in {"google-maps-ratings", "table-for-two-availability"}
        ))

    def test_review_failure_and_mixed_age_remain_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.write(root, "global-dining-source.json", {
                "fetched_at": "2026-08-28T00:00:00Z", "record_count": 20,
                "failed_count": 2, "manual_review_required": True,
            })
            payload = MODULE.build_source_health(root, NOW)

        source = next(item for item in payload["sources"] if item["id"] == "global-dining")
        self.assertEqual(source["freshness_state"], "stale")
        self.assertEqual(source["review_state"], "required")
        self.assertEqual(source["failure_state"], "partial_failure")
        self.assertEqual(source["state"], "partial_failure")

    def test_aggregates_expose_oldest_and_mixed_age(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.write(root, "google-maps-ratings.json", {
                "global-1": {"scraped_at": "2026-04-10"},
                "global-2": {"scraped_at": "2026-08-30"},
            })
            payload = MODULE.build_source_health(root, NOW)

        source = next(item for item in payload["sources"] if item["id"] == "google-maps-ratings")
        self.assertEqual(source["freshness_state"], "mixed_age")
        self.assertEqual(source["stale_record_count"], 1)
        self.assertEqual(source["oldest_checked_at"], "2026-04-10T00:00:00Z")
        self.assertEqual(source["checked_at"], "2026-08-30T00:00:00Z")
        self.assertEqual(source["coverage"], {"covered": 2, "total": 10, "unavailable": 8, "percent": 20.0})

    def test_availability_missing_project_is_unavailable_coverage_not_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            tft = json.loads((root / "table-for-two.json").read_text())
            tft["availability_source"] = {
                "api_base": "https://example.com/api", "error_count": 1,
                "errors": {"tft-2": "missing_amex_platinum_project"},
            }
            self.write(root, "table-for-two.json", tft)
            payload = MODULE.build_source_health(root, NOW)

        source = next(item for item in payload["sources"] if item["id"] == "table-for-two-availability")
        self.assertEqual(source["failure_state"], "clear")
        self.assertEqual(source["coverage"]["unavailable"], 1)
        self.assertEqual(source["coverage"]["covered"], 1)
        self.assertEqual(source["tier"], "enrichment")
        self.assertEqual(source["stale_after_minutes"], 30)

    def test_transition_events_include_exact_before_after(self):
        old = {"sources": [{
            "id": "global-dining", "label": "Global Dining", "program": "Global Dining",
            "program_id": "global-dining", "route": "#/dining/world", "state": "current",
            "freshness_state": "current", "review_state": "clear", "failure_state": "clear",
            "stale_record_count": 0, "error_count": 0, "review_required": False,
            "source_url": "https://example.com",
        }]}
        new = {"sources": [{**old["sources"][0], "state": "stale", "freshness_state": "stale", "stale_record_count": 1}]}

        events = MODULE.build_transition_events(old, new, "2026-08-30T12:00:00Z")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "source_stale")
        self.assertEqual(events[0]["before"]["state"], "current")
        self.assertEqual(events[0]["after"]["state"], "stale")
        self.assertIn({"field": "Freshness", "before": "current", "after": "stale"}, events[0]["changes"])
        self.assertTrue(events[0]["stream_id"])

    def test_coverage_transition_is_scalar_and_retains_previous_source_url(self):
        base = {
            "id": "table-for-two-availability", "label": "Table for Two availability",
            "program": "Table for Two", "program_id": "table-for-two",
            "route": "#/table-for-two", "state": "current", "freshness_state": "current",
            "review_state": "clear", "failure_state": "clear", "stale_record_count": 0,
            "error_count": 0, "review_count": 0,
            "coverage": {"covered": 27, "total": 27, "unavailable": 0, "percent": 100.0},
            "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
        }
        changed = {
            **base,
            "coverage": {"covered": 26, "total": 27, "unavailable": 1, "percent": 96.3},
            "source_url": None,
        }

        event = MODULE.build_transition_events(
            {"sources": [base]}, {"sources": [changed]}, "2026-09-03T00:00:00Z"
        )[0]

        coverage = next(change for change in event["changes"] if change["field"] == "Coverage")
        self.assertEqual(coverage["before"], "27/27 (100%), 0 unavailable")
        self.assertEqual(coverage["after"], "26/27 (96.3%), 1 unavailable")
        self.assertEqual(event["source_url"], base["source_url"])

    def test_review_transition_is_dispatchable_operational_fact(self):
        base = {
            "id": "table-for-two-menus", "label": "Table for Two menus",
            "program": "Table for Two", "program_id": "table-for-two",
            "route": "#/table-for-two", "state": "current", "freshness_state": "current",
            "review_state": "clear", "failure_state": "clear", "stale_record_count": 0,
            "error_count": 0, "review_count": 0, "coverage": {"covered": 2, "total": 2, "unavailable": 0, "percent": 100.0},
            "review_required": False, "snapshot_state": "current", "source_url": "https://example.com",
        }
        changed = {**base, "state": "review_required", "review_state": "required", "review_required": True, "review_count": 1}

        event = MODULE.build_transition_events(
            {"sources": [base]}, {"sources": [changed]}, "2026-08-30T12:00:00Z"
        )[0]

        self.assertEqual(event["kind"], "source_review_required")
        self.assertEqual(event["status"], "published")
        self.assertIn({"field": "Review", "before": "clear", "after": "required"}, event["changes"])

    def test_initial_build_has_no_owner_event_and_second_identical_build_is_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            output = root / "source-health.json"
            updates = root / "updates.json"
            first, first_events = MODULE.update_source_health(root, output, updates, NOW)
            rendered = output.read_bytes()
            second, second_events = MODULE.update_source_health(root, output, updates, NOW)

        self.assertEqual(first, second)
        self.assertEqual(rendered, json.dumps(second, ensure_ascii=False, indent=2).encode() + b"\n")
        self.assertEqual(first_events, [])
        self.assertEqual(second_events, [])
        self.assertFalse(updates.exists())

    def test_failed_attempt_retains_last_success_then_success_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            output = root / "source-health.json"
            updates = root / "updates.json"
            MODULE.update_source_health(root, output, updates, NOW, {"global-dining": "success"})
            later = datetime(2026, 8, 30, 13, tzinfo=timezone.utc)
            failed, failed_events = MODULE.update_source_health(
                root, output, updates, later, {"global-dining": "failure"}
            )
            failed_twice, second_failed_events = MODULE.update_source_health(
                root, output, updates, datetime(2026, 8, 30, 13, 30, tzinfo=timezone.utc),
                {"global-dining": "failure"},
            )
            recovered, recovered_events = MODULE.update_source_health(
                root, output, updates, datetime(2026, 8, 30, 14, tzinfo=timezone.utc),
                {"global-dining": "success"},
            )

        failure = next(item for item in failed["sources"] if item["id"] == "global-dining")
        recovery = next(item for item in recovered["sources"] if item["id"] == "global-dining")
        self.assertEqual(failure["last_success_at"], "2026-08-30T11:00:00Z")
        self.assertEqual(failure["snapshot_state"], "retained")
        self.assertEqual(failure["consecutive_failures"], 1)
        self.assertEqual(failed_events[0]["kind"], "source_health_changed")
        second_failure = next(
            item for item in failed_twice["sources"] if item["id"] == "global-dining"
        )
        self.assertEqual(second_failure["consecutive_failures"], 2)
        self.assertEqual(second_failed_events[0]["kind"], "source_failed")
        self.assertEqual(recovery["last_success_at"], "2026-08-30T11:00:00Z")
        self.assertEqual(recovery["last_attempt_at"], "2026-08-30T14:00:00Z")
        self.assertEqual(recovery["consecutive_failures"], 0)
        self.assertEqual(recovered_events[0]["kind"], "source_recovered")

    def test_booking_project_candidate_is_exposed_as_roster_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            tft = json.loads((root / "table-for-two.json").read_text())
            tft["booking_project_source"] = {
                "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
                "booking_project_review_items": [
                    {"id": "new", "name": "Needs review", "reasons": ["missing_address"]}
                ],
            }
            self.write(root, "table-for-two.json", tft)

            payload = MODULE.build_source_health(root, NOW)

        roster = next(
            item for item in payload["sources"] if item["id"] == "table-for-two-roster"
        )
        self.assertEqual(roster["review_state"], "required")
        self.assertEqual(roster["review_count"], 1)
        self.assertEqual(
            roster["source_url"],
            "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
        )

    def test_unknown_attempt_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "unknown source id"):
                MODULE.update_source_health(
                    root, root / "health.json", None, NOW, {"not-real": "failure"}
                )

    def test_missing_source_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = MODULE.build_source_health(Path(temp), NOW)

        self.assertTrue(all(item["freshness_state"] == "unavailable" for item in payload["sources"]))
        self.assertTrue(all(item["failure_state"] == "clear" for item in payload["sources"]))
        self.assertTrue(all(item["state"] == "unavailable" for item in payload["sources"]))


if __name__ == "__main__":
    unittest.main()
