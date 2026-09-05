#!/usr/bin/env python3

import importlib.util
import copy
import json
import re
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reminders"))

from app.owner_alerts import OwnerAlertEvent  # noqa: E402

MODULE_PATH = Path(__file__).resolve().parents[1] / "source_change_alert.py"
SPEC = importlib.util.spec_from_file_location("source_change_alert", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

DISPATCH_PATH = Path(__file__).resolve().parents[1] / "dispatch_owner_updates.py"
DISPATCH_SPEC = importlib.util.spec_from_file_location("dispatch_owner_updates", DISPATCH_PATH)
DISPATCH = importlib.util.module_from_spec(DISPATCH_SPEC)
assert DISPATCH_SPEC.loader
DISPATCH_SPEC.loader.exec_module(DISPATCH)

APP_JS_PATH = ROOT / "web" / "app.js"

SOLLNER_MERCHANT_ID = "9f3c1a44-de2b-4f7e-8c11-6a0d2b5e9a77"


def _sollner_record(name: str, record_id: str) -> dict:
    """The Munich venue that DiningCity renamed on 2026-08-27, keyed by name slug."""
    return {
        "id": record_id,
        "name": name,
        "source_merchant_id": SOLLNER_MERCHANT_ID,
        "country": "Germany",
        "city": "München",
        "source_localized_address": "Herterichstraße 61, 81479 München",
        "source_url": "https://www.americanexpress.com/en-gb/benefits/global-dining-access",
    }


def _public_update_kinds_in_app_js() -> set[str]:
    source = APP_JS_PATH.read_text()
    start = source.index("const PUBLIC_UPDATE_KINDS = new Set([")
    end = source.index("]);", start)
    return set(re.findall(r'"([a-z][a-z0-9_]*)"', source[start:end]))


class SourceChangeUpdatesTest(unittest.TestCase):
    def test_added_record_has_explicit_before_and_after(self):
        events = MODULE.build_record_update_events(
            "Global Dining",
            [],
            [{"id": "venue-1", "name": "New Place", "city": "Singapore", "source_url": "https://example.com"}],
            {},
            "2026-08-30T00:00:00Z",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "added")
        self.assertEqual(events[0]["before"]["state"], "not_listed")
        self.assertEqual(events[0]["after"]["fields"]["Name"], "New Place")
        self.assertEqual(events[0]["changes"][0], {"field": "Listing", "before": "Not listed", "after": "Listed"})

    def test_tft_confirmed_membership_removal_has_before_and_after(self):
        old = [{
            "id": "tft-park90",
            "name": "Park90",
            "address": "10 Claymore Road",
            "dining_city_public_url": "https://www.diningcity.sg/singapore/park90",
            "booking_project_status": "active",
        }]
        new = [{**old[0], "booking_project_status": "not_listed"}]

        events = MODULE.build_record_update_events(
            "Table for Two", old, new, {
                "roster_source": {"review_required": False},
                "booking_project_source": {
                    "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants"
                },
            }, "2026-09-03T00:30:00Z"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "removed")
        self.assertEqual(events[0]["before"]["state"], "listed")
        self.assertEqual(events[0]["after"]["state"], "not_listed")
        self.assertEqual(events[0]["changes"], [{
            "field": "AMEXPlatSG booking-project membership",
            "before": "In project",
            "after": "Not in project",
        }])
        self.assertEqual(
            events[0]["source_url"],
            "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
        )

    def test_tft_confirmed_membership_reappearance_is_added_once(self):
        old = [{
            "id": "tft-park90",
            "name": "Park90",
            "dining_city_public_url": "https://www.diningcity.sg/singapore/park90",
            "booking_project_status": "not_listed",
        }]
        new = [{**old[0], "booking_project_status": "active"}]
        event = MODULE.build_record_update_events(
            "Table for Two", old, new, {"roster_source": {"review_required": False}}, "2026-09-03T01:00:00Z"
        )[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [event], event["detected_at"])
            MODULE.append_updates(path, [event], event["detected_at"])
            updates = json.loads(path.read_text())["updates"]

        self.assertEqual(event["kind"], "added")
        self.assertEqual(event["before"]["state"], "not_listed")
        self.assertEqual(event["after"]["state"], "listed")
        self.assertEqual(len(updates), 1)

    def test_changed_record_exposes_only_user_relevant_fields(self):
        old = [{"id": "venue-1", "name": "Place", "address": "Old address", "lat": 1.0}]
        new = [{"id": "venue-1", "name": "Place", "address": "New address", "lat": 2.0}]

        events = MODULE.build_record_update_events(
            "Love Dining", old, new, {"manual_review_required": True}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["status"], "review_required")
        self.assertEqual(events[0]["changes"], [{"field": "Address", "before": "Old address", "after": "New address"}])

    def test_rekeyed_outlet_is_one_before_after_correction(self):
        old = [{
            "id": "love-old-hotel-luce",
            "name": "LUCE",
            "hotel": "Wrong Hotel",
            "address": "80 Middle Road, Singapore 188966",
            "city": "Singapore",
            "country": "Singapore",
        }]
        new = [{
            "id": "love-frasers-house-luce",
            "name": "LUCE",
            "hotel": "Frasers House",
            "address": "80 Middle Road, Singapore 188966",
            "city": "Singapore",
            "country": "Singapore",
        }]

        events = MODULE.build_record_update_events(
            "Love Dining",
            old,
            new,
            {"manual_review_required": True},
            "2026-08-30T00:00:00Z",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "correction")
        self.assertEqual(events[0]["status"], "review_required")
        self.assertEqual(
            events[0]["changes"],
            [{"field": "Hotel", "before": "Wrong Hotel", "after": "Frasers House"}],
        )
        diff = MODULE.compare_records(old, new)
        self.assertEqual(diff, {"added": [], "removed": [], "changed": ["LUCE / Singapore"]})

        later = copy.deepcopy(new[0])
        later["notes"] = "Changed"
        ordinary = MODULE.build_record_update_events(
            "Love Dining",
            new,
            [later],
            {"manual_review_required": True},
            "2026-08-31T00:00:00Z",
        )[0]
        self.assertEqual(events[0]["stream_id"], ordinary["stream_id"])

        restored = MODULE.build_record_update_events(
            "Love Dining",
            [later],
            new,
            {"manual_review_required": True},
            "2026-09-01T00:00:00Z",
        )[0]
        recurring = MODULE.build_record_update_events(
            "Love Dining",
            new,
            [later],
            {"manual_review_required": True},
            "2026-09-02T00:00:00Z",
        )[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            for item in (events[0], ordinary, restored, recurring):
                MODULE.append_updates(path, [item], item["detected_at"])
            payload = json.loads(path.read_text())
        stream_events = [
            item
            for item in payload["updates"]
            if item["stream_id"] == events[0]["stream_id"]
        ]
        self.assertEqual(len(stream_events), 4)
        repeated = [
            item
            for item in stream_events
            if item["transition_id"] == ordinary["transition_id"]
        ]
        self.assertEqual([item["occurrence"] for item in repeated], [2, 1])

    def test_renamed_venue_is_one_event_not_a_removal_and_an_addition(self):
        old = [_sollner_record("Gäststätte Sollner Hof", "amex-global-germany-gaststatte-sollner-hof")]
        new = [_sollner_record("Gasthaus Sollner Hof", "amex-global-germany-gasthaus-sollner-hof")]

        events = MODULE.build_record_update_events(
            "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
        )

        self.assertEqual([event["kind"] for event in events], ["renamed"])
        self.assertEqual(events[0]["subject"], "Gasthaus Sollner Hof / München")
        self.assertEqual(events[0]["before"]["state"], "listed")
        self.assertEqual(events[0]["after"]["state"], "listed")
        self.assertEqual(
            events[0]["changes"],
            [{
                "field": "Name",
                "before": "Gäststätte Sollner Hof",
                "after": "Gasthaus Sollner Hof",
            }],
        )
        self.assertEqual(
            MODULE.compare_records(old, new),
            {"added": [], "removed": [], "changed": ["Gasthaus Sollner Hof / München"]},
        )

    def test_renamed_event_validates_against_the_owner_alert_schema(self):
        old = [_sollner_record("Gäststätte Sollner Hof", "amex-global-germany-gaststatte-sollner-hof")]
        new = [_sollner_record("Gasthaus Sollner Hof", "amex-global-germany-gasthaus-sollner-hof")]

        event = MODULE.build_record_update_events(
            "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
        )[0]

        validated = OwnerAlertEvent.model_validate(event)
        self.assertEqual(validated.kind, "renamed")
        self.assertEqual(validated.status, "published")

    def test_renamed_event_is_dispatched_alongside_other_owner_events(self):
        old = [_sollner_record("Gäststätte Sollner Hof", "amex-global-germany-gaststatte-sollner-hof")]
        new = [_sollner_record("Gasthaus Sollner Hof", "amex-global-germany-gasthaus-sollner-hof")]
        renamed = MODULE.build_record_update_events(
            "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
        )[0]
        added = MODULE.build_record_update_events(
            "Global Dining", [], [_sollner_record("Other Place", "amex-global-germany-other")], {}, "2026-08-27T00:56:00Z"
        )[0]

        selected, withheld = DISPATCH.select_owner_notifications([renamed, added])

        self.assertEqual([event["kind"] for event in selected], ["renamed", "added"])
        self.assertEqual(withheld, {})

    def test_every_record_update_kind_is_known_to_both_downstream_allowlists(self):
        old = [
            {"id": "gone", "name": "Closed Place", "city": "Berlin"},
            _sollner_record("Gäststätte Sollner Hof", "amex-global-germany-gaststatte-sollner-hof"),
            {"id": "luce-old", "name": "LUCE", "hotel": "Wrong Hotel", "city": "Singapore", "address": "80 Middle Road"},
            {"id": "stable", "name": "Stable Place", "notes": "Before"},
            {"id": "menu", "name": "Menu Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "a" * 64}},
        ]
        new = [
            {"id": "fresh", "name": "New Place", "city": "Berlin"},
            _sollner_record("Gasthaus Sollner Hof", "amex-global-germany-gasthaus-sollner-hof"),
            {"id": "luce-new", "name": "LUCE", "hotel": "Frasers House", "city": "Singapore", "address": "80 Middle Road"},
            {"id": "stable", "name": "Stable Place", "notes": "After"},
            {"id": "menu", "name": "Menu Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "b" * 64}},
        ]

        emitted = {
            event["kind"]
            for event in MODULE.build_record_update_events(
                "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
            )
        }

        self.assertEqual(
            emitted,
            {"added", "removed", "renamed", "correction", "details_updated", "menu_updated"},
        )
        self.assertLessEqual(
            emitted, DISPATCH.OWNER_ACTIONABLE_KINDS | DISPATCH.OWNER_NOISE_KINDS
        )
        self.assertLessEqual(emitted, _public_update_kinds_in_app_js())

    def test_records_without_a_source_identity_stay_removed_and_added(self):
        old = [{"id": "bistro-old", "name": "Old Bistro", "city": "Paris"}]
        new = [{"id": "bistro-new", "name": "New Bistro", "city": "Paris"}]

        events = MODULE.build_record_update_events(
            "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
        )

        self.assertEqual(sorted(event["kind"] for event in events), ["added", "removed"])

    def test_source_identity_shared_with_a_surviving_record_stays_removed_and_added(self):
        shared = {"source_merchant_id": "shared-merchant", "city": "Munich"}
        keeper = {"id": "keeper", "name": "Keeper", **shared}
        old = [{"id": "vanished", "name": "Vanished", **shared}, keeper]
        new = [{"id": "appeared", "name": "Appeared", **shared}, keeper]

        events = MODULE.build_record_update_events(
            "Global Dining", old, new, {}, "2026-08-27T00:56:00Z"
        )

        self.assertEqual(sorted(event["kind"] for event in events), ["added", "removed"])

    def test_menu_hash_change_is_a_menu_update(self):
        old = [{"id": "venue-1", "name": "Place", "menu_pdf": {"status": "published", "filename": "menu.pdf", "sha256": "a" * 64}}]
        new = [{"id": "venue-1", "name": "Place", "menu_pdf": {"status": "review_required", "filename": "menu.pdf", "sha256": "b" * 64}}]

        events = MODULE.build_record_update_events(
            "Table for Two", old, new, {"manual_review_required": False}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["kind"], "menu_updated")
        self.assertEqual(events[0]["status"], "review_required")
        self.assertEqual(events[0]["changes"][0]["field"], "Menu version")
        self.assertEqual(events[0]["changes"][0]["before"], "aaaaaaaaaaaa")
        self.assertEqual(events[0]["changes"][0]["after"], "bbbbbbbbbbbb")

    def test_faq_review_does_not_withhold_simultaneous_venue_detail_update(self):
        old_meta = {
            "manual_review_required": False,
            "roster_source": {"review_required": False},
            "source_documents": {"faq_sha256": "a" * 64},
            "document_reviews": {
                "tft-faq": {"status": "approved", "review_required": False}
            },
        }
        new_meta = {
            "manual_review_required": True,
            "roster_source": {"review_required": False},
            "source_documents": {"faq_sha256": "b" * 64},
            "document_reviews": {
                "tft-faq": {"status": "review_required", "review_required": True}
            },
        }
        old = [{"id": "venue-1", "name": "Place", "address": "Old address"}]
        new = [{"id": "venue-1", "name": "Place", "address": "New address"}]

        record_event = MODULE.build_record_update_events(
            "Table for Two", old, new, new_meta, "2026-08-30T00:00:00Z"
        )[0]
        meta_event = MODULE.build_meta_update_event(
            "Table for Two", old_meta, new_meta, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(record_event["kind"], "details_updated")
        self.assertEqual(record_event["status"], "published")
        self.assertIsNotNone(meta_event)
        self.assertEqual(meta_event["status"], "review_required")
        self.assertIn(
            "Table for Two FAQ PDF hash",
            [change["field"] for change in meta_event["changes"]],
        )

    def test_tft_roster_review_withholds_venue_detail_update(self):
        meta = {
            "manual_review_required": True,
            "roster_source": {"review_required": True},
        }
        old = [{"id": "venue-1", "name": "Place", "address": "Old address"}]
        new = [{"id": "venue-1", "name": "Place", "address": "New address"}]

        event = MODULE.build_record_update_events(
            "Table for Two", old, new, meta, "2026-08-30T00:00:00Z"
        )[0]

        self.assertEqual(event["status"], "review_required")

    def test_menu_review_queue_change_is_not_a_public_meta_event(self):
        old = {"menu_source": {"review_required": False, "review_queue_count": 0}}
        new = {"menu_source": {"review_required": True, "review_queue_count": 2}}

        event = MODULE.build_meta_update_event(
            "Table for Two", old, new, "2026-08-30T00:00:00Z"
        )

        self.assertIsNone(event)

    def test_booking_project_candidates_are_review_required(self):
        old = {
            "booking_project_source": {
                "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
                "observation_status": "success",
                "observed_count": 23,
                "observed_membership_sha256": "a" * 64,
                "added_vs_reviewed_roster": [],
                "missing_vs_reviewed_roster": [],
                "review_required": False,
            }
        }
        new = {
            "booking_project_source": {
                "source_url": "https://api.diningcity.asia/public/projects/AMEXPlatSG/restaurants",
                "observation_status": "success",
                "observed_count": 24,
                "observed_membership_sha256": "b" * 64,
                "added_vs_reviewed_roster": ["New Place"],
                "missing_vs_reviewed_roster": [],
                "review_required": True,
            }
        }

        event = MODULE.build_meta_update_event(
            "Table for Two", old, new, "2026-08-31T10:00:00Z"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["status"], "review_required")
        self.assertIn(
            "Booking-project candidates added",
            [change["field"] for change in event["changes"]],
        )
        self.assertEqual(
            event["source_url"],
            new["booking_project_source"].get("source_url"),
        )

    def test_same_count_menu_review_replacement_creates_review_event(self):
        old = {
            "menu_source": {
                "review_required": True,
                "review_queue_count": 1,
                "review_queue_sha256": "a" * 64,
            }
        }
        new = {
            "menu_source": {
                "review_required": True,
                "review_queue_count": 1,
                "review_queue_sha256": "b" * 64,
            }
        }

        event = MODULE.build_meta_update_event(
            "Table for Two", old, new, "2026-08-30T00:00:00Z"
        )

        self.assertIsNone(event)

    def test_cleared_menu_review_queue_is_not_a_public_meta_event(self):
        old = {
            "menu_source": {
                "review_required": True,
                "review_queue_count": 1,
                "review_queue_sha256": "a" * 64,
            }
        }
        new = {
            "menu_source": {
                "review_required": False,
                "review_queue_count": 0,
                "review_queue_sha256": "b" * 64,
            }
        }

        self.assertIsNone(
            MODULE.build_meta_update_event(
                "Table for Two", old, new, "2026-08-30T00:00:00Z"
            )
        )

    def test_append_updates_deduplicates_stable_events(self):
        event = {
            "id": "same-event",
            "transition_id": "a" * 20,
            "stream_id": "b" * 20,
            "occurrence": 1,
            "detected_at": "2026-08-30T00:00:00Z",
            "subject": "Place",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [event], "2026-08-30T00:00:00Z")
            MODULE.append_updates(path, [event], "2026-08-30T01:00:00Z")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["updates"]), 1)
        self.assertEqual(payload["updated_at"], "2026-08-30T00:00:00Z")

    def test_repeated_transition_after_inverse_gets_a_new_occurrence(self):
        meta = {"official_url": "https://www.americanexpress.com/example"}
        a = [{"id": "venue-1", "name": "Place", "address": "A"}]
        b = [{"id": "venue-1", "name": "Place", "address": "B"}]
        first = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-01T00:00:00Z"
        )[0]
        inverse = MODULE.build_record_update_events(
            "Table for Two", b, a, meta, "2026-08-15T00:00:00Z"
        )[0]
        recurring = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-30T00:00:00Z"
        )[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [first], "2026-08-01T00:00:00Z")
            MODULE.append_updates(path, [inverse], "2026-08-15T00:00:00Z")
            MODULE.append_updates(path, [recurring], "2026-08-30T00:00:00Z")
            payload = json.loads(path.read_text(encoding="utf-8"))

        forward = [
            event
            for event in payload["updates"]
            if event["transition_id"] == first["transition_id"]
        ]
        self.assertEqual([event["occurrence"] for event in forward], [2, 1])
        self.assertEqual(len({event["id"] for event in forward}), 2)
        self.assertEqual(forward[0]["stream_id"], forward[1]["stream_id"])

    def test_retry_after_same_transition_remains_idempotent(self):
        meta = {"official_url": "https://www.americanexpress.com/example"}
        a = [{"id": "venue-1", "name": "Place", "address": "A"}]
        b = [{"id": "venue-1", "name": "Place", "address": "B"}]
        first = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-01T00:00:00Z"
        )[0]
        retry = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-01T01:00:00Z"
        )[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [first], "2026-08-01T00:00:00Z")
            MODULE.append_updates(path, [retry], "2026-08-01T01:00:00Z")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["updates"]), 1)
        self.assertEqual(payload["updates"][0]["occurrence"], 1)
        self.assertEqual(payload["updated_at"], "2026-08-01T00:00:00Z")

    def test_identical_public_transitions_on_distinct_streams_have_distinct_ids(self):
        meta = {"official_url": "https://www.americanexpress.com/example"}
        first = MODULE.build_record_update_events(
            "Table for Two",
            [],
            [{"id": "venue-1", "name": "Place", "address": "A"}],
            meta,
            "2026-08-30T00:00:00Z",
        )[0]
        second = MODULE.build_record_update_events(
            "Table for Two",
            [],
            [{"id": "venue-2", "name": "Place", "address": "A"}],
            meta,
            "2026-08-30T00:00:00Z",
        )[0]

        self.assertEqual(first["transition_id"], second["transition_id"])
        self.assertNotEqual(first["stream_id"], second["stream_id"])
        self.assertNotEqual(first["id"], second["id"])

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [first, second], "2026-08-30T00:00:00Z")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["updates"]), 2)
        self.assertEqual(len({event["id"] for event in payload["updates"]}), 2)

    def test_recurrence_counter_survives_event_retention(self):
        meta = {"official_url": "https://www.americanexpress.com/example"}
        a = [{"id": "venue-1", "name": "Place", "address": "A"}]
        b = [{"id": "venue-1", "name": "Place", "address": "B"}]
        first = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-30T00:00:00Z"
        )[0]
        inverse = MODULE.build_record_update_events(
            "Table for Two", b, a, meta, "2026-08-30T01:00:00Z"
        )[0]
        first["owner_delivery_state"] = "sent"
        inverse["owner_delivery_state"] = "sent"
        fillers = [
            {
                "transition_id": f"{index + 10:020x}",
                "stream_id": f"{index + 1000:020x}",
                "occurrence": 1,
                "status": "published",
                "owner_delivery_state": "sent",
                "detected_at": "2026-08-30T02:00:00Z",
                "subject": f"Place {index}",
            }
            for index in range(499)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            MODULE.append_updates(path, [first], first["detected_at"])
            MODULE.append_updates(path, [inverse], inverse["detected_at"])
            MODULE.append_updates(path, fillers, "2026-08-30T02:00:00Z")
            pruned = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(first["id"], {event["id"] for event in pruned["updates"]})

            recurring = MODULE.build_record_update_events(
                "Table for Two", a, b, meta, "2026-08-30T03:00:00Z"
            )[0]
            MODULE.append_updates(path, [recurring], recurring["detected_at"])
            payload = json.loads(path.read_text(encoding="utf-8"))

        repeated = [
            event
            for event in payload["updates"]
            if event["transition_id"] == first["transition_id"]
        ]
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["occurrence"], 2)
        self.assertNotEqual(repeated[0]["id"], first["id"])
        state = payload["identity_state"]["streams"][first["stream_id"]]
        self.assertEqual(state["occurrences"][first["transition_id"]], 2)

    def test_legacy_stream_history_migrates_to_the_stable_entity_stream(self):
        meta = {"official_url": "https://www.americanexpress.com/example"}
        a = [{"id": "venue-1", "name": "Place", "address": "A"}]
        b = [{"id": "venue-1", "name": "Place", "address": "B"}]
        first = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-01T00:00:00Z"
        )[0]
        legacy = dict(first)
        legacy["id"] = "legacy-event-12345678"
        legacy.pop("transition_id")
        legacy.pop("stream_id")
        legacy.pop("occurrence")
        inverse = MODULE.build_record_update_events(
            "Table for Two", b, a, meta, "2026-08-15T00:00:00Z"
        )[0]
        recurring = MODULE.build_record_update_events(
            "Table for Two", a, b, meta, "2026-08-30T00:00:00Z"
        )[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            path.write_text(
                json.dumps({"schema_version": 1, "updates": [legacy]}),
                encoding="utf-8",
            )
            MODULE.append_updates(path, [inverse], inverse["detected_at"])
            MODULE.append_updates(path, [recurring], recurring["detected_at"])
            payload = json.loads(path.read_text(encoding="utf-8"))

        repeated = [
            event
            for event in payload["updates"]
            if event.get("transition_id") == first["transition_id"]
        ]
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["occurrence"], 2)
        self.assertEqual(repeated[0]["stream_id"], first["stream_id"])

    def test_review_and_undelivered_events_survive_resolved_retention(self):
        events = []
        for index in range(505):
            events.append(
                {
                    "id": f"resolved-{index:04d}",
                    "status": "published",
                    "owner_delivery_state": "sent",
                    "detected_at": f"2026-08-{(index % 28) + 1:02d}T00:00:00Z",
                }
            )
        review = {
            "id": "review-protected",
            "status": "review_required",
            "detected_at": "2026-01-01T00:00:00Z",
        }
        pending = {
            "id": "pending-protected",
            "status": "published",
            "detected_at": "2026-01-02T00:00:00Z",
        }

        retained = MODULE.retain_updates([*events, review, pending])
        retained_ids = {event["id"] for event in retained}

        self.assertEqual(len(retained), MODULE.MAX_RETAINED_RESOLVED_UPDATES)
        self.assertIn("review-protected", retained_ids)
        self.assertIn("pending-protected", retained_ids)
        self.assertEqual(
            len([event for event in retained if event.get("owner_delivery_state") == "sent"]),
            498,
        )

    def test_review_metadata_does_not_change_transition_identity(self):
        event = MODULE.build_meta_update_event(
            "Table for Two",
            {"source_documents": {"faq_sha256": "a" * 64}},
            {"source_documents": {"faq_sha256": "b" * 64}},
            "2026-08-30T00:00:00Z",
        )
        self.assertIsNotNone(event)
        before = MODULE.update_event_id(event)
        event["status"] = "published"
        event["reviewed_at"] = "2026-08-30T01:00:00Z"
        event["review_note"] = "Reviewed"
        self.assertEqual(MODULE.update_event_id(event), before)

    def test_retraction_metadata_does_not_change_transition_identity(self):
        event = MODULE.build_meta_update_event(
            "Table for Two",
            {"source_documents": {"faq_sha256": "a" * 64}},
            {"source_documents": {"faq_sha256": "b" * 64}},
            "2026-08-30T00:00:00Z",
        )
        self.assertIsNotNone(event)
        before = MODULE.update_event_id(event)
        event["status"] = "retracted"
        event["retracted_at"] = "2026-08-30T01:00:00Z"
        event["retraction_note"] = "Superseded by a reviewed correction"
        event["corrected_by"] = "correction-12345678"
        self.assertEqual(MODULE.update_event_id(event), before)

    def test_retracted_history_is_protected_from_retention(self):
        events = [
            {
                "id": f"sent-{index}",
                "status": "published",
                "owner_delivery_state": "sent",
                "detected_at": f"2026-08-{(index % 28) + 1:02d}T00:00:00Z",
            }
            for index in range(MODULE.MAX_RETAINED_RESOLVED_UPDATES + 5)
        ]
        retracted = {
            "id": "retracted-protected",
            "status": "retracted",
            "detected_at": "2026-01-01T00:00:00Z",
        }

        retained = MODULE.retain_updates([*events, retracted])

        self.assertIn("retracted-protected", {event["id"] for event in retained})

    def test_concurrent_ledger_appends_do_not_lose_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "updates.json"
            events = [
                {
                    "id": f"event-{index:08d}",
                    "transition_id": f"{index:020x}",
                    "stream_id": f"{index + 1000:020x}",
                    "occurrence": 1,
                    "status": "published",
                    "detected_at": f"2026-08-30T00:{index:02d}:00Z",
                    "subject": f"Place {index}",
                }
                for index in range(20)
            ]

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(
                    executor.map(
                        lambda event: MODULE.append_updates(
                            path, [event], event["detected_at"]
                        ),
                        events,
                    )
                )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["updates"]), 20)
        self.assertEqual(
            {event["transition_id"] for event in payload["updates"]},
            {event["transition_id"] for event in events},
        )

    def test_changelog_deduplicates_the_same_record_transition(self):
        diffs = [("data/table-for-two.json", {"added": ["Forage"], "removed": [], "changed": []})]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "changelog.md"
            MODULE.append_changelog(path, "Table for Two", diffs)
            first = path.read_text(encoding="utf-8")
            MODULE.append_changelog(path, "Table for Two", diffs)

            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertEqual(first.count("Forage"), 1)


if __name__ == "__main__":
    unittest.main()
