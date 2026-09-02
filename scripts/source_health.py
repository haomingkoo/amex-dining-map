#!/usr/bin/env python3
"""Build stable, user-facing health for Explorer data sources."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from source_change_alert import append_updates, assign_event_identity


SCHEMA_VERSION = 1
PRIMARY_STALE_HOURS = 36
AVAILABILITY_STALE_HOURS = 0.5
RATINGS_STALE_HOURS = 90 * 24
TABELOG_STALE_HOURS = 90 * 24


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if len(raw) == 10:
        raw += "T00:00:00Z"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def _times(values: Iterable[Any]) -> list[datetime]:
    return sorted(parsed for value in values if (parsed := parse_time(value)) is not None)


def _freshness(
    timestamps: list[datetime], now: datetime, stale_after_hours: float
) -> tuple[str, int]:
    if not timestamps:
        return "unavailable", 0
    cutoff = now - timedelta(hours=stale_after_hours)
    stale_count = sum(value < cutoff for value in timestamps)
    if stale_count == len(timestamps):
        return "stale", stale_count
    if stale_count:
        return "mixed_age", stale_count
    return "current", 0


def _source(
    *,
    source_id: str,
    label: str,
    program: str,
    program_id: str,
    route: str,
    kind: str,
    timestamps: Iterable[Any],
    now: datetime,
    stale_after_hours: float,
    review_required: bool = False,
    error_count: int = 0,
    record_count: int = 0,
    covered_count: int | None = None,
    unavailable_count: int = 0,
    review_count: int = 0,
    detail: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    parsed = _times(timestamps)
    freshness_state, stale_record_count = _freshness(parsed, now, stale_after_hours)
    error_count = max(0, int(error_count or 0))
    if error_count:
        failure_state = "partial_failure" if parsed else "failed"
    else:
        failure_state = "clear"
    review_state = "required" if review_required else "clear"
    if failure_state != "clear":
        state = failure_state
    elif review_required:
        state = "review_required"
    else:
        state = freshness_state
    total = max(0, int(record_count or 0))
    unavailable_count = max(0, min(total, int(unavailable_count or 0)))
    covered = max(0, min(total, total - unavailable_count if covered_count is None else int(covered_count)))
    coverage = {
        "covered": covered,
        "total": total,
        "unavailable": unavailable_count,
        "percent": round(covered * 100 / total, 1) if total else 0.0,
    }
    checked_at = format_time(parsed[-1]) if parsed else None
    return {
        "id": source_id,
        "label": label,
        "program": program,
        "program_id": program_id,
        "route": route,
        "tier": kind,
        "kind": kind,
        "status": state,
        "state": state,
        "freshness_state": freshness_state,
        "review_state": review_state,
        "failure_state": failure_state,
        "checked_at": checked_at,
        "oldest_checked_at": format_time(parsed[0]) if parsed else None,
        "upstream_date": checked_at[:10] if checked_at else None,
        "upstream_year": int(checked_at[:4]) if checked_at else None,
        "stale_after_hours": stale_after_hours,
        "stale_after_minutes": int(stale_after_hours * 60),
        "record_count": total,
        "coverage": coverage,
        "retained_snapshot": False,
        "stale_record_count": stale_record_count,
        "error_count": error_count,
        "review_required": bool(review_required),
        "review_count": max(0, int(review_count or 0)),
        "detail": detail,
        "source_url": source_url,
    }


def build_source_health(data_dir: Path, now: datetime) -> dict[str, Any]:
    now = now.astimezone(timezone.utc)
    global_meta = load_json(data_dir / "global-dining-source.json", {})
    japan_meta = load_json(data_dir / "japan-dining-source.json", {})
    stay_meta = load_json(data_dir / "plat-stay-source.json", {})
    love_meta = load_json(data_dir / "love-dining-source.json", {})
    tft = load_json(data_dir / "table-for-two.json", {})
    slots = load_json(data_dir / "table-for-two-slots.json", {})
    google = load_json(data_dir / "google-maps-ratings.json", {})
    global_records = load_json(data_dir / "global-restaurants.json", [])
    japan_records = load_json(data_dir / "japan-restaurants.json", [])
    love_records = load_json(data_dir / "love-dining.json", [])
    stay_records = load_json(data_dir / "plat-stays.json", [])

    slot_venues = slots.get("venues", []) if isinstance(slots, dict) else []
    slot_venues = slot_venues if isinstance(slot_venues, list) else []
    availability_source = tft.get("availability_source") or {}
    availability_source = availability_source if isinstance(availability_source, dict) else {}
    unavailable_slot_ids = set((availability_source.get("errors") or {}).keys())
    current_records: list[Any] = []
    for records in (global_records, japan_records, love_records, stay_records):
        if isinstance(records, list):
            current_records.extend(records)
    current_records.extend(tft.get("venues") or [])
    current_ids = {
        item.get("id") for item in current_records if isinstance(item, dict) and item.get("id")
    }
    google_values = [
        google[source_id]
        for source_id in current_ids
        if isinstance(google, dict) and isinstance(google.get(source_id), dict)
    ]
    tabelog_values = [
        (item.get("external_signals") or {}).get("tabelog")
        for item in japan_records
        if isinstance(item, dict)
        and isinstance((item.get("external_signals") or {}).get("tabelog"), dict)
    ] if isinstance(japan_records, list) else []

    booking_review_items = (
        (tft.get("booking_project_source") or {}).get("booking_project_review_items")
        or []
    )
    roster_review_required = bool(
        (tft.get("roster_source") or {}).get("review_required")
        or booking_review_items
    )
    sources = [
        _source(
            source_id="global-dining",
            label="Global Dining",
            program="Global Dining",
            program_id="global-dining",
            route="#/dining/world",
            kind="primary",
            timestamps=[global_meta.get("fetched_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            review_required=bool(global_meta.get("manual_review_required")),
            review_count=len(global_meta.get("major_change_reasons") or []),
            error_count=global_meta.get("failed_count", 0),
            record_count=global_meta.get("record_count", 0),
            source_url=global_meta.get("source_url"),
        ),
        _source(
            source_id="japan-dining",
            label="Japan Dining",
            program="Japan Dining",
            program_id="japan-dining",
            route="#/dining/japan/top",
            kind="primary",
            timestamps=[japan_meta.get("fetched_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            review_required=bool(japan_meta.get("manual_review_required")),
            review_count=len(japan_meta.get("major_change_reasons") or []),
            record_count=japan_meta.get("record_count", 0),
            source_url=japan_meta.get("source_url"),
        ),
        _source(
            source_id="plat-stay",
            label="Plat Stay",
            program="Plat Stay",
            program_id="plat-stay",
            route="#/stays",
            kind="primary",
            timestamps=[stay_meta.get("fetched_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            record_count=stay_meta.get("record_count", 0),
            source_url=stay_meta.get("resolved_url") or stay_meta.get("canonical_url"),
        ),
        _source(
            source_id="love-dining",
            label="Love Dining",
            program="Love Dining",
            program_id="love-dining",
            route="#/love-dining",
            kind="primary",
            timestamps=[love_meta.get("last_checked_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            review_required=bool(love_meta.get("manual_review_required")),
            review_count=len(love_meta.get("major_change_reasons") or []),
            record_count=love_meta.get("record_count", 0),
            source_url=next(iter((love_meta.get("official_pages") or {}).values()), None),
        ),
        _source(
            source_id="table-for-two-roster",
            label="Table for Two roster",
            program="Table for Two",
            program_id="table-for-two",
            route="#/table-for-two",
            kind="primary",
            timestamps=[tft.get("last_verified_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            review_required=roster_review_required,
            review_count=(
                1 if (tft.get("roster_source") or {}).get("review_item") else 0
            ) + len(booking_review_items),
            record_count=len(tft.get("venues") or []),
            source_url=(
                (tft.get("booking_project_source") or {}).get("source_url")
                if booking_review_items
                else tft.get("official_url")
            ),
        ),
        _source(
            source_id="table-for-two-menus",
            label="Table for Two menus",
            program="Table for Two",
            program_id="table-for-two",
            route="#/table-for-two",
            kind="primary",
            timestamps=[(tft.get("menu_source") or {}).get("checked_at")],
            now=now,
            stale_after_hours=PRIMARY_STALE_HOURS,
            review_required=bool((tft.get("menu_source") or {}).get("review_required")),
            review_count=(tft.get("menu_source") or {}).get("review_queue_count", 0),
            record_count=len(tft.get("venues") or []),
            covered_count=(tft.get("menu_source") or {}).get("venues_matched", 0),
            unavailable_count=max(
                0,
                len(tft.get("venues") or []) - int((tft.get("menu_source") or {}).get("venues_matched", 0)),
            ),
            source_url=tft.get("official_url"),
        ),
        _source(
            source_id="table-for-two-availability",
            label="Table for Two availability",
            program="Table for Two",
            program_id="table-for-two",
            route="#/table-for-two",
            kind="enrichment",
            timestamps=[
                venue.get("checked_at")
                for venue in slot_venues
                if isinstance(venue, dict) and venue.get("id") not in unavailable_slot_ids
            ],
            now=now,
            stale_after_hours=AVAILABILITY_STALE_HOURS,
            error_count=0,
            record_count=len(slot_venues),
            covered_count=max(0, len(slot_venues) - len(unavailable_slot_ids)),
            unavailable_count=len(unavailable_slot_ids),
            detail=f"{max(0, len(slot_venues) - len(unavailable_slot_ids))} of {len(slot_venues)} venues checked",
            source_url=availability_source.get("api_base"),
        ),
        _source(
            source_id="google-maps-ratings",
            label="Google Maps ratings",
            program="Explorer ratings",
            program_id="explorer-ratings",
            route="#/dining/world",
            kind="enrichment",
            timestamps=[item.get("scraped_at") for item in google_values if isinstance(item, dict)],
            now=now,
            stale_after_hours=RATINGS_STALE_HOURS,
            covered_count=len(google_values),
            unavailable_count=max(0, len(current_ids) - len(google_values)),
            record_count=len(current_ids),
            detail=f"{len(google_values)} of {len(current_ids)} current venues covered",
            source_url="https://www.google.com/maps",
        ),
        _source(
            source_id="tabelog-ratings",
            label="Tabelog ratings",
            program="Explorer ratings",
            program_id="explorer-ratings",
            route="#/dining/japan/top",
            kind="enrichment",
            timestamps=[item.get("last_checked_at") for item in tabelog_values],
            now=now,
            stale_after_hours=TABELOG_STALE_HOURS,
            record_count=len(japan_records) if isinstance(japan_records, list) else 0,
            covered_count=len(tabelog_values),
            unavailable_count=max(0, len(japan_records) - len(tabelog_values)) if isinstance(japan_records, list) else 0,
            detail=f"{len(tabelog_values)} of {len(japan_records) if isinstance(japan_records, list) else 0} current Japan venues covered",
            source_url="https://tabelog.com/en/",
        ),
    ]
    return {"schema_version": SCHEMA_VERSION, "sources": sources}


TRANSITION_FIELDS = {
    "state": "Source state",
    "freshness_state": "Freshness",
    "review_state": "Review",
    "failure_state": "Failures",
    "stale_record_count": "Stale records",
    "error_count": "Failed records",
    "review_count": "Review items",
    "coverage": "Coverage",
    "snapshot_state": "Snapshot",
    "last_attempt_outcome": "Refresh attempt",
    "consecutive_failures": "Consecutive failures",
}

OPERATION_FIELDS = (
    "last_attempt_at",
    "last_attempt_outcome",
    "last_success_at",
    "consecutive_failures",
    "snapshot_state",
    "retained_snapshot",
)


def transition_value(field: str, value: Any) -> Any:
    if field != "coverage" or not isinstance(value, dict):
        return value
    covered = max(0, int(value.get("covered") or 0))
    total = max(0, int(value.get("total") or 0))
    unavailable = max(0, int(value.get("unavailable") or 0))
    percent = float(value.get("percent") or 0)
    return f"{covered}/{total} ({percent:g}%), {unavailable} unavailable"


def build_transition_events(
    old_payload: dict[str, Any], new_payload: dict[str, Any], detected_at: str
) -> list[dict[str, Any]]:
    old_sources = {
        item.get("id"): item
        for item in old_payload.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    events: list[dict[str, Any]] = []
    for new in new_payload.get("sources", []):
        if not isinstance(new, dict) or not (old := old_sources.get(new.get("id"))):
            continue
        changes = [
            {
                "field": label,
                "before": transition_value(field, old.get(field)),
                "after": transition_value(field, new.get(field)),
            }
            for field, label in TRANSITION_FIELDS.items()
            if old.get(field) != new.get(field)
        ]
        if not changes:
            continue
        old_fresh = old.get("freshness_state")
        new_fresh = new.get("freshness_state")
        old_failure = old.get("failure_state")
        new_failure = new.get("failure_state")
        old_failure_count = max(0, int(old.get("consecutive_failures") or 0))
        new_failure_count = max(0, int(new.get("consecutive_failures") or 0))
        if (
            new_failure != "clear"
            and old_failure_count < 2 <= new_failure_count
        ):
            kind = "source_failed"
        elif old_failure != "clear" and new_failure == "clear":
            kind = "source_recovered"
        elif old_fresh == "current" and new_fresh in {"mixed_age", "stale", "unavailable"}:
            kind = "source_stale"
        elif old_fresh in {"mixed_age", "stale", "unavailable"} and new_fresh == "current":
            kind = "source_recovered"
        elif old.get("review_state") == "clear" and new.get("review_state") == "required":
            kind = "source_review_required"
        elif old.get("review_state") == "required" and new.get("review_state") == "clear":
            kind = "source_review_cleared"
        else:
            kind = "source_health_changed"
        event = {
            "program": new["program"],
            "program_id": new["program_id"],
            "route": new["route"],
            "kind": kind,
            "subject": new["label"],
            "detected_at": detected_at,
            "status": "published",
            "before": {"state": old.get("state"), "fields": {c["field"]: c["before"] for c in changes}},
            "after": {"state": new.get("state"), "fields": {c["field"]: c["after"] for c in changes}},
            "changes": changes,
            "source_url": new.get("source_url") or old.get("source_url"),
        }
        assign_event_identity(event, f"source-health:{new['id']}")
        events.append(event)
    return events


def apply_attempts(
    previous: dict[str, Any],
    payload: dict[str, Any],
    attempts: dict[str, str],
    now: datetime,
) -> None:
    old_sources = {
        item.get("id"): item
        for item in previous.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    attempted_at = format_time(now)
    known_ids = {item["id"] for item in payload["sources"]}
    unknown = sorted(set(attempts) - known_ids)
    if unknown:
        raise ValueError(f"unknown source id: {', '.join(unknown)}")
    for source in payload["sources"]:
        old = old_sources.get(source["id"], {})
        for field in OPERATION_FIELDS:
            if field in old:
                source[field] = old[field]
        if "last_attempt_outcome" not in source:
            source.update({
                "last_attempt_at": source.get("checked_at"),
                "last_attempt_outcome": "success" if source.get("checked_at") else "unknown",
                "last_success_at": source.get("checked_at"),
                "consecutive_failures": 0,
                "snapshot_state": "current" if source.get("checked_at") else "unavailable",
                "retained_snapshot": False,
            })
        outcome = attempts.get(source["id"])
        if outcome == "success":
            has_snapshot = bool(source.get("checked_at"))
            source.update({
                "last_attempt_at": attempted_at,
                "last_attempt_outcome": "success",
                "last_success_at": source.get("checked_at") or source.get("last_success_at"),
                "consecutive_failures": 0,
                "snapshot_state": "current" if has_snapshot else "unavailable",
                "retained_snapshot": False,
            })
        elif outcome == "failure":
            source.update({
                "last_attempt_at": attempted_at,
                "last_attempt_outcome": "failure",
                "consecutive_failures": max(0, int(source.get("consecutive_failures") or 0)) + 1,
                "snapshot_state": "retained" if source.get("checked_at") else "unavailable",
                "retained_snapshot": bool(source.get("checked_at")),
                "failure_state": "failed",
                "state": "failed",
                "status": "failed",
            })
        elif source.get("last_attempt_outcome") == "failure":
            source.update({
                "failure_state": "failed",
                "state": "failed",
                "status": "failed",
            })


def update_source_health(
    data_dir: Path,
    output: Path,
    updates: Path | None,
    now: datetime,
    attempts: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    previous = load_json(output, {})
    payload = build_source_health(data_dir, now)
    apply_attempts(previous, payload, attempts or {}, now)
    detected_at = format_time(now)
    events = build_transition_events(previous, payload, detected_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if updates is not None:
        append_updates(updates, events, detected_at)
    if not output.exists() or output.read_text(encoding="utf-8") != rendered:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, output)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
    return payload, events
