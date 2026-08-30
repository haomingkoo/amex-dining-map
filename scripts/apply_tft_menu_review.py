#!/usr/bin/env python3
"""Apply one manifest-driven TFT menu candidate decision."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reminders.app.owner_alerts import OwnerAlertEvent
from scripts import build_tft_guide_catalog, source_change_alert, tft_menu_reviews


DEFAULT_DATA = Path("data/table-for-two.json")
DEFAULT_UPDATES = Path("data/updates.json")
DEFAULT_CATALOG = Path("reminders/app/tft_guide_catalog.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog(payload: dict) -> dict:
    release_history = _load(build_tft_guide_catalog.DEFAULT_RELEASE_HISTORY)
    return build_tft_guide_catalog.build_catalog(payload, release_history)


def _receipt(payload: dict, manifest: dict) -> dict:
    digest = tft_menu_reviews.manifest_sha256(manifest)
    matches = [
        entry
        for entry in (payload.get("menu_source") or {}).get("review_decisions") or []
        if entry.get("candidate_id") == manifest.get("candidate_id")
        and entry.get("manifest_sha256") == digest
    ]
    if len(matches) != 1:
        raise ValueError("exact TFT menu decision receipt is missing or duplicated")
    return matches[0]


def _expected_event(payload: dict, receipt: dict) -> dict | None:
    stored = receipt.get("owner_event")
    if stored is None:
        return None
    candidate = receipt.get("candidate") or {}
    venue = next(
        (
            item
            for item in payload.get("venues") or []
            if item.get("id") == candidate.get("venue_id")
        ),
        None,
    )
    active = ((venue or {}).get("menu_pdfs") or {}).get(candidate.get("card")) or {}
    if active.get("review_manifest_sha256") != receipt.get("manifest_sha256"):
        return None
    event = copy.deepcopy(stored)
    entity_key = event.pop("entity_key")
    source_change_alert.assign_event_identity(event, entity_key)
    OwnerAlertEvent.model_validate(event)
    return event


def _event_is_present(ledger: dict, expected: dict) -> bool:
    for event in ledger.get("updates") or []:
        occurrence = event.get("occurrence")
        if not isinstance(occurrence, int) or occurrence < 1:
            continue
        if any(
            event.get(key) != value
            for key, value in expected.items()
            if key not in {"id", "occurrence"}
        ):
            continue
        if (
            source_change_alert.update_event_id(event) != expected["transition_id"]
            or event.get("id")
            != source_change_alert._occurrence_id(
                expected["stream_id"], expected["transition_id"], occurrence
            )
        ):
            continue
        try:
            OwnerAlertEvent.model_validate(event)
        except ValueError:
            continue
        return True
    return False


def _load_ledger(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {"schema_version": 1, "updates": []}
    return _load(path)


def _reconcile_owner_event(path: Path, expected: dict, reviewed_at: str) -> None:
    with source_change_alert._ledger_lock(path):
        ledger = _load_ledger(path)
        if _event_is_present(ledger, expected):
            return
        ledger["identity_state"] = source_change_alert.rebuild_identity_state(
            ledger.get("updates") or []
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        source_change_alert._atomic_write_json(path, ledger)
    source_change_alert.append_updates(path, [expected], reviewed_at)


def _queue_event_is_open(event: dict) -> bool:
    queue_fields = {
        "Menu review flag",
        "Menu review queue count",
        "Menu review queue fingerprint",
    }
    changes = event.get("changes") or []
    return (
        event.get("program_id") == "table-for-two"
        and event.get("subject") == "Table for Two source"
        and event.get("status") == "review_required"
        and event.get("stream_id")
        == source_change_alert.update_stream_id("table-for-two", "meta")
        and event.get("transition_id") == source_change_alert.update_event_id(event)
        and bool(changes)
        and all(change.get("field") in queue_fields for change in changes)
    )


def _resolve_queue_events(path: Path, reviewed_at: str) -> None:
    if not path.exists():
        return
    with source_change_alert._ledger_lock(path):
        ledger = _load_ledger(path)
        changed = False
        for event in ledger.get("updates") or []:
            if not _queue_event_is_open(event):
                continue
            event["status"] = "rejected"
            event["reviewed_at"] = reviewed_at
            event["review_note"] = "Menu review queue resolved."
            changed = True
        if changed:
            ledger["updated_at"] = reviewed_at
            ledger["identity_state"] = source_change_alert.rebuild_identity_state(
                ledger.get("updates") or []
            )
            source_change_alert._atomic_write_json(path, ledger)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--updates", type=Path, default=DEFAULT_UPDATES)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    with source_change_alert._ledger_lock(args.data):
        payload = _load(args.data)
        manifest = _load(args.manifest)
        pdf_bytes = args.pdf.read_bytes() if args.pdf else None
        updated, event = tft_menu_reviews.apply_review(
            payload, manifest, pdf_bytes=pdf_bytes
        )
        tft_menu_reviews.verify_decision_receipts(updated)
        receipt = _receipt(updated, manifest)
        expected_event = _expected_event(updated, receipt)
        expected_catalog = _catalog(updated)
        rendered_catalog = json.dumps(
            expected_catalog, ensure_ascii=False, indent=2
        ) + "\n"
        if args.check:
            ledger = _load_ledger(args.updates)
            event_missing = expected_event is not None and not _event_is_present(
                ledger, expected_event
            )
            queue_event_open = not updated["menu_source"]["review_queue"] and any(
                _queue_event_is_open(item) for item in ledger.get("updates") or []
            )
            if (
                updated != payload
                or event_missing
                or queue_event_open
                or not args.catalog.exists()
                or args.catalog.read_text(encoding="utf-8") != rendered_catalog
            ):
                raise SystemExit("TFT menu review has not been fully applied")
            print("TFT menu review is current")
            return 0
        if updated != payload:
            source_change_alert._atomic_write_json(args.data, updated)
        if expected_event is not None:
            _reconcile_owner_event(
                args.updates, expected_event, manifest["reviewed_at"]
            )
        if not updated["menu_source"]["review_queue"]:
            _resolve_queue_events(args.updates, manifest["reviewed_at"])
        args.catalog.parent.mkdir(parents=True, exist_ok=True)
        source_change_alert._atomic_write_json(args.catalog, expected_catalog)
    print(
        f"{'Reconciled' if updated == payload else 'Applied'} TFT menu decision: "
        f"{manifest['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
