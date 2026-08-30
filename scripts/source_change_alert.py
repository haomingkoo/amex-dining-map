#!/usr/bin/env python3
"""Build a GitHub Actions alert body when source-backed data changes.

Compares current files against HEAD so refresh workflows can open/update a
GitHub issue only when source hashes, counts, or official records move.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
    "source_images.participating_merchants_sha256": "Participating merchants image hash",
    "source_images.voucher_cycles_sha256": "Voucher cycles image hash",
    "source_documents.terms_sha256": "Table for Two T&C PDF hash",
    "source_documents.faq_sha256": "Table for Two FAQ PDF hash",
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
    if key != "manual_review_required"
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
    stable = {key: value for key, value in payload.items() if key != "detected_at"}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_record_update_events(
    program: str,
    old_payload: Any,
    new_payload: Any,
    meta: dict[str, Any],
    detected_at: str,
) -> list[dict[str, Any]]:
    config = PROGRAM_UPDATE_CONFIG.get(program, {"id": program.lower().replace(" ", "-"), "route": "#/alerts"})
    status = "review_required" if meta.get("manual_review_required") else "published"
    old_by_key = {record_key(record): record for record in records_from_payload(old_payload)}
    new_by_key = {record_key(record): record for record in records_from_payload(new_payload)}
    events: list[dict[str, Any]] = []

    for key in sorted(set(new_by_key) - set(old_by_key)):
        record = new_by_key[key]
        event = {
            "program": program,
            "program_id": config["id"],
            "route": config["route"],
            "kind": "added",
            "subject": record_label(record),
            "detected_at": detected_at,
            "status": status,
            "before": {"state": "not_listed", "fields": {}},
            "after": {"state": "listed", "fields": public_record_fields(record)},
            "changes": [{"field": "Listing", "before": "Not listed", "after": "Listed"}],
            "source_url": record_source_url(record, meta),
        }
        event["id"] = update_event_id(event)
        events.append(event)

    for key in sorted(set(old_by_key) - set(new_by_key)):
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
        event["id"] = update_event_id(event)
        events.append(event)

    for key in sorted(set(old_by_key) & set(new_by_key)):
        old_record = old_by_key[key]
        new_record = new_by_key[key]
        if stable_record_hash(old_record) == stable_record_hash(new_record):
            continue
        changes = public_field_changes(old_record, new_record)
        if not changes:
            continue
        menu_change = any("menu" in change["field"].lower() for change in changes)
        event = {
            "program": program,
            "program_id": config["id"],
            "route": config["route"],
            "kind": "menu_updated" if menu_change else "details_updated",
            "subject": record_label(new_record),
            "detected_at": detected_at,
            "status": status,
            "before": {"state": "listed", "fields": public_record_fields(old_record)},
            "after": {"state": "listed", "fields": public_record_fields(new_record)},
            "changes": changes,
            "source_url": record_source_url(new_record, meta),
        }
        event["id"] = update_event_id(event)
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
    event = {
        "program": program,
        "program_id": config["id"],
        "route": config["route"],
        "kind": "source_updated",
        "subject": f"{program} source",
        "detected_at": detected_at,
        "status": "review_required" if new_meta.get("manual_review_required") else "published",
        "before": {"state": "available", "fields": {item["field"]: item["before"] for item in changes}},
        "after": {"state": "available", "fields": {item["field"]: item["after"] for item in changes}},
        "changes": changes,
        "source_url": record_source_url(None, new_meta),
    }
    event["id"] = update_event_id(event)
    return event


def append_updates(path: Path, events: list[dict[str, Any]], updated_at: str) -> None:
    if not events:
        return
    payload = load_json(path) if path.exists() else {"schema_version": 1, "updates": []}
    existing = payload.get("updates") if isinstance(payload, dict) else []
    existing = existing if isinstance(existing, list) else []
    known_ids = {event.get("id") for event in existing if isinstance(event, dict)}
    additions = [event for event in events if event["id"] not in known_ids]
    if not additions:
        return
    payload["schema_version"] = 1
    payload["updated_at"] = updated_at
    payload["updates"] = sorted(
        [*additions, *existing],
        key=lambda event: (event.get("detected_at") or "", event.get("id") or ""),
        reverse=True,
    )[:500]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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

    added = sorted(record_label(new_by_key[key]) for key in set(new_by_key) - set(old_by_key))
    removed = sorted(record_label(old_by_key[key]) for key in set(old_by_key) - set(new_by_key))
    changed = sorted(
        record_label(new_by_key[key])
        for key in set(old_by_key) & set(new_by_key)
        if stable_record_hash(old_by_key[key]) != stable_record_hash(new_by_key[key])
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

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [f"## {timestamp} — {program}", ""]
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
        lines.extend([
            "## Review Checklist",
            "",
            "- Open the official source links in the metadata file.",
            "- Re-check benefit wording, blackout notes, closed venues, and newly added/removed records.",
            "- If the displayed wording is still correct, update the reviewed baseline or close this issue.",
        ])
    else:
        lines.append("No watched source hashes, counts, or official records changed.")

    Path(args.output).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
