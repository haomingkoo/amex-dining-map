#!/usr/bin/env python3
"""Build a GitHub Actions alert body when source-backed data changes.

Compares current files against HEAD so refresh workflows can open/update a
GitHub issue only when source hashes, counts, or official records move.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IGNORED_RECORD_FIELDS = {
    "lat",
    "lon",
    "lng",
    "search_text",
    "summary_ai",
    "last_synced_at",
    "last_verified_at",
    "availability",
    "slot_source_status",
}

# Nested keys (under any dict, at any depth) that flip every scrape but do not
# represent a real change to the venue. Stripped before hashing.
IGNORED_NESTED_KEYS = {
    "captured_at",
    "checked_at",
    "fetched_at",
    "last_checked_at",
    "last_synced_at",
    "last_verified_at",
}

META_FIELD_LABELS = {
    "record_count": "Record count",
    "mapped_count": "Mapped count",
    "city_count": "City count",
    "restaurant_count": "Restaurant count",
    "hotel_outlet_count": "Hotel outlet count",
    "page_count": "Source page count",
    "sha256": "Source SHA-256",
    "records_sha256": "Official records SHA-256",
    "manual_review_required": "Manual review flag",
    "menu_source.review_required": "Menu review flag",
    "menu_source.review_queue_count": "Menu review queue count",
    "menu_source.review_queue_sha256": "Menu review queue fingerprint",
    "source_images.participating_merchants_sha256": "Participating merchants image hash",
    "roster_source.status": "Roster review status",
    "roster_source.observed_participating_sha256": "Observed roster image hash",
    "roster_source.approved_participating_sha256": "Approved roster image hash",
    "roster_source.review_item.kind": "Roster review item",
    "booking_project_source.observation_status": "Booking-project observation",
    "booking_project_source.observed_count": "Booking-project venue count",
    "booking_project_source.observed_membership_sha256": "Booking-project membership fingerprint",
    "booking_project_source.added_vs_reviewed_roster": "Booking-project candidates added",
    "booking_project_source.missing_vs_reviewed_roster": "Reviewed venues missing from booking project",
    "booking_project_source.identity_mismatch_count": "Booking-project identity conflicts",
    "source_images.voucher_cycles_sha256": "Voucher cycles image hash",
    "source_documents.terms_sha256": "Table for Two T&C PDF hash",
    "source_documents.faq_sha256": "Table for Two FAQ PDF hash",
    "document_reviews.tft-terms.status": "T&C review status",
    "document_reviews.tft-terms.observed_sha256": "Observed T&C PDF hash",
    "document_reviews.tft-terms.approved_sha256": "Approved T&C PDF hash",
    "document_reviews.tft-terms.review_item.kind": "T&C review item",
    "document_reviews.tft-faq.status": "FAQ review status",
    "document_reviews.tft-faq.observed_sha256": "Observed FAQ PDF hash",
    "document_reviews.tft-faq.approved_sha256": "Approved FAQ PDF hash",
    "document_reviews.tft-faq.review_item.kind": "FAQ review item",
    "terms_hashes.restaurants": "Restaurant T&C PDF hash",
    "terms_hashes.hotels": "Hotel T&C PDF hash",
    "terms_hashes.global_dining_credit": "Global Dining Credit T&C text hash",
    "terms_hashes.global_dining_credit_pdf": "Global Dining Credit T&C PDF hash",
}

PROGRAM_UPDATE_CONFIG = {
    "Global Dining": {"id": "global-dining", "route": "#/dining/world"},
    "Japan Dining": {"id": "japan-dining", "route": "#/dining/japan/top"},
    "Plat Stay": {"id": "plat-stay", "route": "#/stays"},
    "Love Dining": {"id": "love-dining", "route": "#/love-dining"},
    "Table for Two": {"id": "table-for-two", "route": "#/table-for-two"},
}

PUBLIC_RECORD_FIELDS = {
    "name": "Name",
    "hotel": "Hotel",
    "type": "Type",
    "category": "Category",
    "country": "Country",
    "region": "Region",
    "city": "City",
    "district": "District",
    "app_area": "Area",
    "address": "Address",
    "source_localized_address": "Address",
    "cuisines": "Cuisine",
    "cuisine": "Cuisine",
    "cuisine_category": "Cuisine category",
    "eligible_room_type": "Eligible room",
    "breakfast_included": "Breakfast included",
    "blackout_raw": "Blackout dates",
    "reservation_raw": "Reservations",
    "booking_channel": "Booking channel",
    "notes": "Notes",
    "opening_hours": "Opening hours",
    "menu_pdf.filename": "Menu file",
    "menu_pdf.sha256": "Menu version",
    "menu_pdfs.platinum.filename": "Platinum menu file",
    "menu_pdfs.platinum.sha256": "Platinum menu version",
    "menu_pdfs.centurion.filename": "Centurion menu file",
    "menu_pdfs.centurion.sha256": "Centurion menu version",
}

PUBLIC_META_FIELDS = {
    key: label
    for key, label in META_FIELD_LABELS.items()
    if key
    not in {
        "manual_review_required",
        "menu_source.review_required",
        "menu_source.review_queue_count",
        "menu_source.review_queue_sha256",
    }
}

MAX_RETAINED_RESOLVED_UPDATES = 500
TERMINAL_OWNER_DELIVERY_STATES = {
    "sent",
    "before_activation",
    "withheld",
    "unknown",
    "dead",
    "schema_rejected",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_show_json(path: str) -> Any | None:
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw)


def nested_get(payload: Any, dotted_path: str) -> Any:
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "records", "restaurants", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    return []


def record_key(record: dict[str, Any]) -> str:
    return str(
        record.get("id")
        or record.get("source_merchant_id")
        or "|".join(str(record.get(field, "")) for field in ("country", "city", "name", "address"))
    )


def record_location_identity(record: dict[str, Any]) -> str | None:
    name = " ".join(str(record.get("name") or "").casefold().split())
    address = " ".join(str(record.get("address") or "").casefold().split())
    if not name or not address:
        return None
    country = " ".join(str(record.get("country") or "").casefold().split())
    city = " ".join(str(record.get("city") or "").casefold().split())
    return json.dumps([country, city, name, address], ensure_ascii=False, separators=(",", ":"))


def record_source_identity(record: dict[str, Any]) -> str | None:
    """Identity the source assigns, which survives a venue being renamed."""
    for field in ("source_merchant_id", "dining_city_id"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return f"{field}:{value.strip()}"
    return None


def _index_by_identity(
    records_by_key: dict[str, dict[str, Any]],
    identity_of: Callable[[dict[str, Any]], str | None],
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for key, record in records_by_key.items():
        identity = identity_of(record)
        if identity:
            index.setdefault(identity, []).append(key)
    return index


def match_rekeyed_records(
    old_by_key: dict[str, dict[str, Any]],
    new_by_key: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    """Pair disappeared with appeared records that are the same venue re-keyed.

    Matches on location, then on the source-assigned id. An identity that is
    missing, or shared by more than one record on either side, is left alone so
    the caller falls back to reporting a removal plus an addition.
    """
    old_only = set(old_by_key) - set(new_by_key)
    new_only = set(new_by_key) - set(old_by_key)
    rekeyed: list[tuple[str, str]] = []
    for identity_of in (record_location_identity, record_source_identity):
        old_index = _index_by_identity(old_by_key, identity_of)
        new_index = _index_by_identity(new_by_key, identity_of)
        for identity in sorted(set(old_index) & set(new_index)):
            old_keys = old_index[identity]
            new_keys = new_index[identity]
            if len(old_keys) != 1 or len(new_keys) != 1:
                continue
            old_key, new_key = old_keys[0], new_keys[0]
            if old_key not in old_only or new_key not in new_only:
                continue
            old_only.remove(old_key)
            new_only.remove(new_key)
            rekeyed.append((old_key, new_key))
    return rekeyed


def record_label(record: dict[str, Any]) -> str:
    parts = [
        record.get("name") or record.get("app_name") or record.get("hotel") or "Unknown",
        record.get("city") or record.get("app_area") or record.get("country"),
    ]
    return " / ".join(str(part) for part in parts if part)


def display_value(path: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, str) and (
        path.endswith("sha256")
        or (len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value))
    ):
        return value[:12]
    return value


def public_record_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for path, label in PUBLIC_RECORD_FIELDS.items():
        value = display_value(path, nested_get(record, path))
        if value is not None and label not in fields:
            fields[label] = value
    return fields


def public_field_changes(old_record: dict[str, Any], new_record: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for path, label in PUBLIC_RECORD_FIELDS.items():
        old_value = display_value(path, nested_get(old_record, path))
        new_value = display_value(path, nested_get(new_record, path))
        if old_value == new_value or label in seen_labels:
            continue
        seen_labels.add(label)
        changes.append({"field": label, "before": old_value, "after": new_value})
    return changes


def record_source_url(record: dict[str, Any] | None, meta: dict[str, Any]) -> str | None:
    record = record or {}
    for path in (
        "menu_pdf.url",
        "source_url",
        "source_document_url",
        "terms_url",
        "website_url",
        "dining_city_public_url",
    ):
        value = nested_get(record, path)
        if value:
            return str(value)
    for key in (
        "source_url",
        "official_url",
        "canonical_url",
        "resolved_url",
        "terms_url",
        "faq_url",
    ):
        if meta.get(key):
            return str(meta[key])
    official_pages = meta.get("official_pages")
    if isinstance(official_pages, dict) and official_pages:
        return str(next(iter(official_pages.values())))
    return None


def update_event_id(payload: dict[str, Any]) -> str:
    ignored = {
        "detected_at",
        "id",
        "transition_id",
        "stream_id",
        "occurrence",
        "status",
        "reviewed_at",
        "review_note",
        "owner_delivery_state",
        "owner_delivery_recorded_at",
        "retracted_at",
        "retraction_note",
        "corrected_by",
        "corrects",
    }
    stable = {key: value for key, value in payload.items() if key not in ignored}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def update_stream_id(program_id: str, entity_key: str) -> str:
    raw = json.dumps([program_id, entity_key], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _occurrence_id(stream_id: str, transition_id: str, occurrence: int) -> str:
    raw = f"{stream_id}:{transition_id}:{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def assign_event_identity(event: dict[str, Any], entity_key: str) -> None:
    event["transition_id"] = update_event_id(event)
    event["stream_id"] = update_stream_id(str(event["program_id"]), entity_key)
    event["occurrence"] = 1
    event["id"] = _occurrence_id(event["stream_id"], event["transition_id"], 1)


def _menu_review_required(record: dict[str, Any]) -> bool:
    return (record.get("menu_pdf") or {}).get("status") == "review_required" or any(
        menu.get("status") == "review_required"
        for menu in (record.get("menu_pdfs") or {}).values()
        if isinstance(menu, dict)
    )


def _record_review_required(program: str, meta: dict[str, Any]) -> bool:
    if program == "Table for Two":
        return bool((meta.get("roster_source") or {}).get("review_required"))
    return bool(meta.get("manual_review_required"))


def build_record_update_events(
    program: str,
    old_payload: Any,
    new_payload: Any,
    meta: dict[str, Any],
    detected_at: str,
) -> list[dict[str, Any]]:
    config = PROGRAM_UPDATE_CONFIG.get(program, {"id": program.lower().replace(" ", "-"), "route": "#/alerts"})
    status = "review_required" if _record_review_required(program, meta) else "published"
    old_by_key = {record_key(record): record for record in records_from_payload(old_payload)}
    new_by_key = {record_key(record): record for record in records_from_payload(new_payload)}
    events: list[dict[str, Any]] = []

    rekeyed = match_rekeyed_records(old_by_key, new_by_key)
    old_only = set(old_by_key) - set(new_by_key) - {old_key for old_key, _ in rekeyed}
    new_only = set(new_by_key) - set(old_by_key) - {new_key for _, new_key in rekeyed}

    for key in sorted(new_only):
        record = new_by_key[key]
        event = {
            "program": program,
            "program_id": config["id"],
            "route": config["route"],
            "kind": "added",
            "subject": record_label(record),
            "detected_at": detected_at,
            "status": "review_required" if _menu_review_required(record) else status,
            "before": {"state": "not_listed", "fields": {}},
            "after": {"state": "listed", "fields": public_record_fields(record)},
            "changes": [{"field": "Listing", "before": "Not listed", "after": "Listed"}],
            "source_url": record_source_url(record, meta),
        }
        assign_event_identity(event, f"record:{key}")
        events.append(event)

    for key in sorted(old_only):
        record = old_by_key[key]
        event = {
            "program": program,
            "program_id": config["id"],
            "route": config["route"],
            "kind": "removed",
            "subject": record_label(record),
            "detected_at": detected_at,
            "status": status,
            "before": {"state": "listed", "fields": public_record_fields(record)},
            "after": {"state": "not_listed", "fields": {}},
            "changes": [{"field": "Listing", "before": "Listed", "after": "Not listed"}],
            "source_url": record_source_url(record, meta),
        }
        assign_event_identity(event, f"record:{key}")
        events.append(event)

    record_pairs = [
        (key, old_by_key[key], new_by_key[key], f"record:{key}", False)
        for key in sorted(set(old_by_key) & set(new_by_key))
    ]
    record_pairs.extend(
        (
            new_key,
            old_by_key[old_key],
            new_by_key[new_key],
            f"record:{new_key}",
            True,
        )
        for old_key, new_key in rekeyed
    )
    for key, old_record, new_record, entity_key, is_rekeyed in record_pairs:
        old_listed = old_record.get("booking_project_status") != "not_listed"
        new_listed = new_record.get("booking_project_status") != "not_listed"
        if program == "Table for Two" and old_listed != new_listed:
            kind = "added" if new_listed else "removed"
            membership_source_url = (
                (meta.get("booking_project_source") or {}).get("source_url")
                or record_source_url(new_record, meta)
            )
            event = {
                "program": program,
                "program_id": config["id"],
                "route": config["route"],
                "kind": kind,
                "subject": record_label(new_record if new_listed else old_record),
                "detected_at": detected_at,
                "status": status,
                "before": {
                    "state": "not_listed" if new_listed else "listed",
                    "fields": {} if new_listed else public_record_fields(old_record),
                },
                "after": {
                    "state": "listed" if new_listed else "not_listed",
                    "fields": public_record_fields(new_record) if new_listed else {},
                },
                "changes": [
                    {
                        "field": "AMEXPlatSG booking-project membership",
                        "before": "Not in project" if new_listed else "In project",
                        "after": "In project" if new_listed else "Not in project",
                    }
                ],
                "source_url": membership_source_url,
            }
            assign_event_identity(event, entity_key)
            events.append(event)
            continue
        if stable_record_hash(old_record) == stable_record_hash(new_record):
            continue
        changes = public_field_changes(old_record, new_record)
        if not changes:
            continue
        menu_change = any("menu" in change["field"].lower() for change in changes)
        menu_review_required = menu_change and _menu_review_required(new_record)
        source_identity = record_source_identity(old_record)
        renamed = (
            is_rekeyed
            and source_identity is not None
            and source_identity == record_source_identity(new_record)
            and old_record.get("name") != new_record.get("name")
        )
        event = {
            "program": program,
            "program_id": config["id"],
            "route": config["route"],
            "kind": (
                "menu_updated"
                if menu_change
                else "renamed"
                if renamed
                else "correction"
                if is_rekeyed
                else "details_updated"
            ),
            "subject": record_label(new_record),
            "detected_at": detected_at,
            "status": "review_required" if menu_review_required else status,
            "before": {"state": "listed", "fields": public_record_fields(old_record)},
            "after": {"state": "listed", "fields": public_record_fields(new_record)},
            "changes": changes,
            "source_url": record_source_url(new_record, meta),
        }
        assign_event_identity(event, entity_key)
        events.append(event)

    return events


def build_meta_update_event(
    program: str,
    old_meta: dict[str, Any],
    new_meta: dict[str, Any],
    detected_at: str,
) -> dict[str, Any] | None:
    changes = []
    for path, label in PUBLIC_META_FIELDS.items():
        old_value = display_value(path, nested_get(old_meta, path))
        new_value = display_value(path, nested_get(new_meta, path))
        if old_value != new_value:
            changes.append({"field": label, "before": old_value, "after": new_value})
    if not changes:
        return None
    config = PROGRAM_UPDATE_CONFIG.get(program, {"id": program.lower().replace(" ", "-"), "route": "#/alerts"})
    booking_project_change = any(
        change["field"].startswith("Booking-project")
        or change["field"].startswith("Reviewed venues missing from booking project")
        for change in changes
    )
    booking_project_url = (
        (new_meta.get("booking_project_source") or {}).get("source_url")
        if booking_project_change
        else None
    )
    event = {
        "program": program,
        "program_id": config["id"],
        "route": config["route"],
        "kind": "source_updated",
        "subject": f"{program} source",
        "detected_at": detected_at,
        "status": (
            "review_required"
            if new_meta.get("manual_review_required")
            or (new_meta.get("menu_source") or {}).get("review_required")
            or (new_meta.get("roster_source") or {}).get("review_required")
            or (new_meta.get("booking_project_source") or {}).get("review_required")
            or any(
                isinstance(review, dict) and review.get("review_required")
                for review in (new_meta.get("document_reviews") or {}).values()
            )
            else "published"
        ),
        "before": {"state": "available", "fields": {item["field"]: item["before"] for item in changes}},
        "after": {"state": "available", "fields": {item["field"]: item["after"] for item in changes}},
        "changes": changes,
        "source_url": booking_project_url or record_source_url(None, new_meta),
    }
    assign_event_identity(event, "meta")
    return event


def _event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return event.get("detected_at") or "", event.get("id") or ""


def _legacy_stream_id(event: dict[str, Any]) -> str:
    return update_stream_id(
        str(event.get("program_id") or event.get("program") or "unknown"),
        f"legacy:{event.get('subject') or event.get('kind') or 'unknown'}",
    )


def _identity(event: dict[str, Any]) -> tuple[str, str, int]:
    transition_id = str(event.get("transition_id") or update_event_id(event))
    stream_id = str(event.get("stream_id") or _legacy_stream_id(event))
    try:
        occurrence = max(1, int(event.get("occurrence") or 1))
    except (TypeError, ValueError):
        occurrence = 1
    return transition_id, stream_id, occurrence


def _identity_state(
    payload: dict[str, Any], ordered_existing: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[tuple[str, str], int]]:
    latest_by_stream: dict[str, str] = {}
    max_occurrence: dict[tuple[str, str], int] = {}
    for event in ordered_existing:
        transition_id, stream_id, occurrence = _identity(event)
        latest_by_stream.setdefault(stream_id, transition_id)
        key = (stream_id, transition_id)
        max_occurrence[key] = max(max_occurrence.get(key, 0), occurrence)

    streams = payload.get("identity_state", {}).get("streams", {})
    if not isinstance(streams, dict):
        return latest_by_stream, max_occurrence
    for stream_id, state in streams.items():
        if not isinstance(stream_id, str) or not isinstance(state, dict):
            continue
        latest = state.get("latest_transition_id")
        if isinstance(latest, str):
            latest_by_stream[stream_id] = latest
        occurrences = state.get("occurrences")
        if not isinstance(occurrences, dict):
            continue
        for transition_id, occurrence in occurrences.items():
            try:
                value = max(1, int(occurrence))
            except (TypeError, ValueError):
                continue
            key = (stream_id, str(transition_id))
            max_occurrence[key] = max(max_occurrence.get(key, 0), value)
    return latest_by_stream, max_occurrence


def _render_identity_state(
    latest_by_stream: dict[str, str],
    max_occurrence: dict[tuple[str, str], int],
) -> dict[str, Any]:
    streams: dict[str, dict[str, Any]] = {}
    for stream_id in sorted(latest_by_stream):
        streams[stream_id] = {
            "latest_transition_id": latest_by_stream[stream_id],
            "occurrences": {
                transition_id: occurrence
                for (candidate_stream, transition_id), occurrence in sorted(
                    max_occurrence.items()
                )
                if candidate_stream == stream_id
            },
        }
    return {"streams": streams}


def rebuild_identity_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(events, key=_event_sort_key, reverse=True)
    latest_by_stream, max_occurrence = _identity_state({}, ordered)
    return _render_identity_state(latest_by_stream, max_occurrence)


def _migrate_legacy_stream(
    event: dict[str, Any],
    stream_id: str,
    latest_by_stream: dict[str, str],
    max_occurrence: dict[tuple[str, str], int],
) -> None:
    if stream_id in latest_by_stream:
        return
    legacy_stream_id = _legacy_stream_id(event)
    latest = latest_by_stream.get(legacy_stream_id)
    if latest is None or legacy_stream_id == stream_id:
        return
    latest_by_stream[stream_id] = latest
    for (candidate_stream, transition_id), occurrence in list(max_occurrence.items()):
        if candidate_stream == legacy_stream_id:
            key = (stream_id, transition_id)
            max_occurrence[key] = max(max_occurrence.get(key, 0), occurrence)


@contextmanager
def _ledger_lock(path: Path):
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"amex-owner-ledger-{digest}.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def retain_updates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=_event_sort_key, reverse=True)
    protected = []
    resolved = []
    for event in ordered:
        delivery_state = event.get("owner_delivery_state")
        if event.get("status") in {"review_required", "retracted"} or (
            event.get("status") == "published"
            and delivery_state not in TERMINAL_OWNER_DELIVERY_STATES
        ):
            protected.append(event)
        else:
            resolved.append(event)
    resolved_budget = max(0, MAX_RETAINED_RESOLVED_UPDATES - len(protected))
    return sorted(
        [*protected, *resolved[:resolved_budget]],
        key=_event_sort_key,
        reverse=True,
    )


def append_updates(path: Path, events: list[dict[str, Any]], updated_at: str) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(path):
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        payload = json.loads(raw) if raw.strip() else {"schema_version": 1, "updates": []}
        existing = payload.get("updates") if isinstance(payload, dict) else []
        existing = existing if isinstance(existing, list) else []
        existing = [event for event in existing if isinstance(event, dict)]
        ordered_existing = sorted(existing, key=_event_sort_key, reverse=True)
        latest_by_stream, max_occurrence = _identity_state(payload, ordered_existing)
        known_ids = {event.get("id") for event in ordered_existing}

        additions = []
        for incoming in events:
            event = dict(incoming)
            transition_id, stream_id, _occurrence = _identity(event)
            _migrate_legacy_stream(
                event, stream_id, latest_by_stream, max_occurrence
            )
            latest = latest_by_stream.get(stream_id)
            if latest == transition_id:
                continue
            occurrence = max_occurrence.get((stream_id, transition_id), 0) + 1
            event["transition_id"] = transition_id
            event["stream_id"] = stream_id
            event["occurrence"] = occurrence
            event["id"] = _occurrence_id(stream_id, transition_id, occurrence)
            if event["id"] in known_ids:
                continue
            additions.append(event)
            known_ids.add(event["id"])
            latest_by_stream[stream_id] = transition_id
            max_occurrence[(stream_id, transition_id)] = occurrence
        if not additions:
            return
        payload["schema_version"] = 1
        payload["updated_at"] = updated_at
        payload["identity_state"] = _render_identity_state(
            latest_by_stream, max_occurrence
        )
        payload["updates"] = retain_updates([*additions, *existing])
        _atomic_write_json(path, payload)


def record_owner_delivery_states(
    path: Path, outcomes: dict[str, str], recorded_at: str
) -> int:
    if not outcomes or not path.exists():
        return 0
    with _ledger_lock(path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        for event in payload.get("updates") or []:
            state = outcomes.get(str(event.get("id")))
            if state is None or event.get("owner_delivery_state") == state:
                continue
            event["owner_delivery_state"] = state
            event["owner_delivery_recorded_at"] = recorded_at
            changed += 1
        if not changed:
            return 0
        payload["updated_at"] = recorded_at
        payload["updates"] = retain_updates(payload.get("updates") or [])
        _atomic_write_json(path, payload)
        return changed


def _strip_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_nested(sub)
            for key, sub in value.items()
            if key not in IGNORED_NESTED_KEYS
        }
    if isinstance(value, list):
        return [_strip_nested(item) for item in value]
    return value


def stable_record_hash(record: dict[str, Any]) -> str:
    cleaned = {
        key: _strip_nested(value)
        for key, value in record.items()
        if key not in IGNORED_RECORD_FIELDS
    }
    raw = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compare_records(old_payload: Any | None, new_payload: Any | None) -> dict[str, list[str]]:
    old_records = records_from_payload(old_payload) if old_payload is not None else []
    new_records = records_from_payload(new_payload) if new_payload is not None else []
    old_by_key = {record_key(record): record for record in old_records}
    new_by_key = {record_key(record): record for record in new_records}
    rekeyed = match_rekeyed_records(old_by_key, new_by_key)
    old_only = set(old_by_key) - set(new_by_key) - {old_key for old_key, _ in rekeyed}
    new_only = set(new_by_key) - set(old_by_key) - {new_key for _, new_key in rekeyed}

    added = sorted(record_label(new_by_key[key]) for key in new_only)
    removed = sorted(record_label(old_by_key[key]) for key in old_only)
    changed_pairs = [
        (old_by_key[key], new_by_key[key])
        for key in set(old_by_key) & set(new_by_key)
    ] + [(old_by_key[old_key], new_by_key[new_key]) for old_key, new_key in rekeyed]
    changed = sorted(
        record_label(new_record)
        for old_record, new_record in changed_pairs
        if stable_record_hash(old_record) != stable_record_hash(new_record)
    )
    return {"added": added, "removed": removed, "changed": changed}


def append_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"{name}={value}")
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def format_limited(items: list[str], limit: int = 12) -> list[str]:
    if len(items) <= limit:
        return items
    return items[:limit] + [f"... and {len(items) - limit} more"]


def append_changelog(
    changelog_path: Path,
    program: str,
    record_diffs: list[tuple[str, dict[str, list[str]]]],
) -> None:
    """Append a dated entry to the per-program changelog.

    Only logs additions and removals — those are the interesting events
    (new venues, dropped venues). Field-level changes are intentionally
    omitted; they're noisy and most useful in the issue body, not a
    permanent log.
    """
    has_changes = any(diff["added"] or diff["removed"] for _, diff in record_diffs)
    if not has_changes:
        return

    change_fingerprint = hashlib.sha256(
        json.dumps(record_diffs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    marker = f"<!-- source-change:{change_fingerprint} -->"
    if changelog_path.exists() and marker in changelog_path.read_text(encoding="utf-8"):
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [marker, f"## {timestamp} — {program}", ""]
    for data_path, diff in record_diffs:
        if not (diff["added"] or diff["removed"]):
            continue
        lines.append(f"Source: `{data_path}`")
        lines.append("")
        for key, title in (("added", "Added"), ("removed", "Removed")):
            items = diff[key]
            if not items:
                continue
            lines.append(f"- **{title} ({len(items)})**")
            lines.extend(f"  - {item}" for item in format_limited(items, limit=50))
        lines.append("")

    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8").rstrip() + "\n\n"
    else:
        existing = f"# {program} change log\n\n"
    changelog_path.write_text(existing + "\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--data", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--changelog",
        help="Append a dated entry to this changelog file when records changed.",
    )
    parser.add_argument(
        "--updates",
        help="Append structured before-and-after records to this update ledger.",
    )
    args = parser.parse_args()

    current_meta = load_json(args.meta)
    previous_meta = git_show_json(args.meta)
    reasons: list[str] = []

    if previous_meta is not None:
        for path, label in META_FIELD_LABELS.items():
            old_value = nested_get(previous_meta, path)
            new_value = nested_get(current_meta, path)
            if old_value != new_value:
                reasons.append(f"{label}: `{old_value}` → `{new_value}`")
    elif Path(args.meta).exists():
        append_output("alert_required", "false")
        Path(args.output).write_text(
            f"# {args.program} source snapshot initialized\n\nNo previous `{args.meta}` exists in HEAD, so this run establishes the baseline.\n",
            encoding="utf-8",
        )
        return 0

    if current_meta.get("manual_review_required"):
        for reason in current_meta.get("major_change_reasons") or ["Manual source review is required."]:
            if reason not in reasons:
                reasons.append(str(reason))

    detected_at = now_iso()
    record_diffs: list[tuple[str, dict[str, list[str]]]] = []
    update_events: list[dict[str, Any]] = []
    for data_path in args.data:
        previous_data = git_show_json(data_path)
        current_data = load_json(data_path)
        diff = compare_records(previous_data, current_data)
        if diff["added"] or diff["removed"] or diff["changed"]:
            record_diffs.append((data_path, diff))
        if previous_data is not None:
            update_events.extend(
                build_record_update_events(
                    args.program,
                    previous_data,
                    current_data,
                    current_meta,
                    detected_at,
                )
            )

    if previous_meta is not None:
        meta_event = build_meta_update_event(args.program, previous_meta, current_meta, detected_at)
        if meta_event:
            update_events.append(meta_event)

    if args.updates:
        append_updates(Path(args.updates), update_events, detected_at)

    alert_required = bool(reasons or record_diffs)
    append_output("alert_required", "true" if alert_required else "false")

    if args.changelog:
        append_changelog(Path(args.changelog), args.program, record_diffs)

    lines = [
        f"# {args.program} source changed" if alert_required else f"# {args.program} source unchanged",
        "",
        f"- Checked at: `{detected_at}`",
        f"- Metadata file: `{args.meta}`",
    ]
    if current_meta.get("last_checked_at") or current_meta.get("fetched_at"):
        lines.append(f"- Source cache time: `{current_meta.get('last_checked_at') or current_meta.get('fetched_at')}`")
    if current_meta.get("record_count") is not None:
        lines.append(f"- Current record count: `{current_meta.get('record_count')}`")
    lines.append("")

    source_links: list[tuple[str, str]] = []
    if isinstance(current_meta.get("official_pages"), dict):
        source_links.extend((f"official page: {key}", value) for key, value in current_meta["official_pages"].items())
    if isinstance(current_meta.get("terms"), dict):
        source_links.extend((f"terms: {key}", value) for key, value in current_meta["terms"].items())
    if current_meta.get("official_url"):
        source_links.append(("official page", current_meta["official_url"]))
    if current_meta.get("terms_url"):
        source_links.append(("terms", current_meta["terms_url"]))
    if current_meta.get("faq_url"):
        source_links.append(("FAQ", current_meta["faq_url"]))
    if current_meta.get("canonical_url"):
        source_links.append(("canonical source", current_meta["canonical_url"]))
    if current_meta.get("resolved_url"):
        source_links.append(("resolved source", current_meta["resolved_url"]))
    booking_project_source = current_meta.get("booking_project_source") or {}
    if booking_project_source.get("source_url"):
        source_links.append(
            (
                "current booking-project membership",
                booking_project_source["source_url"],
            )
        )
    if source_links:
        lines.extend(["## Source Links", ""])
        lines.extend(f"- {label}: {url}" for label, url in source_links)
        lines.append("")

    if reasons:
        lines.extend(["## Source Signals", ""])
        lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")

    for data_path, diff in record_diffs:
        lines.extend([f"## Record Changes: `{data_path}`", ""])
        for key, title in (("added", "Added"), ("removed", "Removed"), ("changed", "Changed")):
            if diff[key]:
                lines.append(f"### {title}")
                lines.extend(f"- {item}" for item in format_limited(diff[key]))
                lines.append("")

    if alert_required:
        if booking_project_source.get("review_required"):
            published_additions = booking_project_source.get(
                "published_booking_project_additions"
            ) or []
            unconfirmed_additions = booking_project_source.get(
                "unconfirmed_added_vs_reviewed_roster"
            ) or []
            boundary_notes = []
            if published_additions:
                boundary_notes.append(
                    f"{len(published_additions)} explicitly confirmed booking-project additions are published as current venues; they are not represented in the retained Amex roster image."
                )
            if unconfirmed_additions:
                boundary_notes.append(
                    f"{len(unconfirmed_additions)} other booking-project addition remains review-gated."
                )
            if not boundary_notes:
                boundary_notes.append(
                    "Booking-project additions/removals remain review signals until corroborated."
                )
            lines.extend(
                [
                    "## Evidence Boundary",
                    "",
                    *(f"- {note}" for note in boundary_notes),
                    "",
                ]
            )
        lines.extend([
            "## Review Checklist",
            "",
            "- Open the relevant source links in the metadata file.",
            "- Re-check benefit wording, blackout notes, closed venues, and newly added/removed records.",
            "- If the displayed wording is still correct, update the reviewed baseline or close this issue.",
        ])
    else:
        lines.append("No watched source hashes, counts, or official records changed.")

    Path(args.output).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
