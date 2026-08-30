#!/usr/bin/env python3

import importlib.util
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "source_change_alert.py"
SPEC = importlib.util.spec_from_file_location("source_change_alert", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


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

    def test_changed_record_exposes_only_user_relevant_fields(self):
        old = [{"id": "venue-1", "name": "Place", "address": "Old address", "lat": 1.0}]
        new = [{"id": "venue-1", "name": "Place", "address": "New address", "lat": 2.0}]

        events = MODULE.build_record_update_events(
            "Love Dining", old, new, {"manual_review_required": True}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["status"], "review_required")
        self.assertEqual(events[0]["changes"], [{"field": "Address", "before": "Old address", "after": "New address"}])

    def test_menu_hash_change_is_a_menu_update(self):
        old = [{"id": "venue-1", "name": "Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "a" * 64}}]
        new = [{"id": "venue-1", "name": "Place", "menu_pdf": {"filename": "menu.pdf", "sha256": "b" * 64}}]

        events = MODULE.build_record_update_events(
            "Table for Two", old, new, {"manual_review_required": True}, "2026-08-30T00:00:00Z"
        )

        self.assertEqual(events[0]["kind"], "menu_updated")
        self.assertEqual(events[0]["changes"][0]["field"], "Menu version")
        self.assertEqual(events[0]["changes"][0]["before"], "aaaaaaaaaaaa")
        self.assertEqual(events[0]["changes"][0]["after"], "bbbbbbbbbbbb")

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


if __name__ == "__main__":
    unittest.main()
