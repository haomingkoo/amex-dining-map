#!/usr/bin/env python3
"""Validate and apply human-reviewed Table for Two roster versions."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts import source_change_alert
except ModuleNotFoundError:
    import source_change_alert


PROGRAM_ID = "table-for-two"
OFFICIAL_URL = "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/"
REVIEW_ROOT = Path(__file__).resolve().parents[1] / "data/reviews/table-for-two-roster"
RUNTIME_FIELDS = {
    "availability",
    "dining_city_profile",
    "menu_pdf",
    "menu_pdfs",
    "slot_source_status",
}
REQUIRED_VENUE_FIELDS = {
    "id",
    "name",
    "category",
    "address",
    "lat",
    "lng",
    "booking_channel",
}


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def stable_venue(record: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(
        {key: value for key, value in record.items() if key not in RUNTIME_FIELDS}
    )


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} is required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc


def validate_manifest(manifest: dict[str, Any], path: Path | None = None) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("program_id") != PROGRAM_ID:
        raise ValueError("invalid Table for Two roster manifest")
    source = manifest.get("source")
    review = manifest.get("review")
    predecessor = manifest.get("predecessor")
    if not isinstance(source, dict) or source.get("official_url") != OFFICIAL_URL:
        raise ValueError("manifest must bind the official Table for Two URL")
    image_url = source.get("participating_image_url")
    image_sha = source.get("participating_image_sha256")
    if not isinstance(image_url, str) or not image_url.startswith("https://www.americanexpress.com/"):
        raise ValueError("manifest must bind the official participating-image URL")
    if not isinstance(image_sha, str) or len(image_sha) != 64:
        raise ValueError("manifest participating-image SHA-256 is invalid")
    if path is not None and path.stem != image_sha:
        raise ValueError("manifest filename must equal the participating-image SHA-256")
    captured_at = _parse_timestamp(source.get("captured_at"), "source.captured_at")
    if not isinstance(review, dict) or review.get("complete_roster") is not True:
        raise ValueError("manifest must record a complete human roster review")
    reviewed_at = _parse_timestamp(review.get("reviewed_at"), "review.reviewed_at")
    if reviewed_at < captured_at:
        raise ValueError("review cannot predate source capture")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("review.reviewer is required")
    if not isinstance(review.get("note"), str) or not review["note"].strip():
        raise ValueError("review.note is required")
    if not isinstance(predecessor, dict):
        raise ValueError("predecessor lineage is required")
    predecessor_manifest = predecessor.get("manifest_sha256")
    predecessor_image = predecessor.get("participating_image_sha256")
    if (predecessor_manifest is None) != (predecessor_image is None):
        raise ValueError("predecessor manifest and image hashes must both be set or null")
    for field, value in (
        ("predecessor.manifest_sha256", predecessor_manifest),
        ("predecessor.participating_image_sha256", predecessor_image),
    ):
        if value is not None and (not isinstance(value, str) or len(value) != 64):
            raise ValueError(f"{field} is invalid")

    venues = manifest.get("venues")
    if not isinstance(venues, list) or not venues:
        raise ValueError("manifest must contain the reviewed roster")
    if review.get("venue_count") != len(venues):
        raise ValueError("review venue_count does not match the roster")
    identifiers: set[str] = set()
    for venue in venues:
        if not isinstance(venue, dict) or not REQUIRED_VENUE_FIELDS <= venue.keys():
            raise ValueError("every reviewed venue must be a complete stable record")
        if RUNTIME_FIELDS & venue.keys():
            raise ValueError("reviewed venues cannot contain runtime menu or availability fields")
        venue_id = venue.get("id")
        if not isinstance(venue_id, str) or not venue_id.startswith("tft-") or venue_id in identifiers:
            raise ValueError("reviewed venue IDs must be unique stable tft-* IDs")
        identifiers.add(venue_id)
    expected = manifest_sha256(manifest)
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("manifest_sha256 does not match the canonical manifest")


def load_manifest_for_hash(image_sha256: str) -> tuple[dict[str, Any], Path] | None:
    path = REVIEW_ROOT / f"{image_sha256}.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(manifest, path)
    return manifest, path


def review_state(
    image_sha256: str,
    image_url: str,
    detected_at: str,
    existing_payload: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the approved stable roster and source-scoped review state.

    An unreviewed image never changes the public roster. Existing approved records
    remain authoritative until a manifest bound to the observed image is applied.
    """
    existing_payload = existing_payload or {}
    existing_source = existing_payload.get("roster_source") or {}
    loaded = load_manifest_for_hash(image_sha256)
    manifest_is_applied = loaded and (
        existing_source.get("approved_manifest_sha256") == loaded[0]["manifest_sha256"]
        or (
            existing_source.get("approved_manifest_sha256") is None
            and (existing_payload.get("source_images") or {}).get(
                "participating_merchants_sha256"
            )
            == image_sha256
        )
    )
    if manifest_is_applied:
        manifest, _ = loaded
        return copy.deepcopy(manifest["venues"]), {
            "status": "approved",
            "review_required": False,
            "observed_participating_sha256": image_sha256,
            "approved_participating_sha256": image_sha256,
            "approved_manifest_sha256": manifest["manifest_sha256"],
            "reviewed_at": manifest["review"]["reviewed_at"],
            "review_item": None,
        }

    existing = existing_payload.get("venues")
    if not isinstance(existing, list) or not existing:
        raise RuntimeError("unknown roster image has no previously approved public roster to retain")
    prior = existing_payload.get("roster_source") or {}
    approved_image = prior.get("approved_participating_sha256")
    approved_manifest = prior.get("approved_manifest_sha256")
    if not approved_image:
        approved_image = (existing_payload.get("source_images") or {}).get(
            "participating_merchants_sha256"
        )
    return [stable_venue(record) for record in existing], {
        "status": "review_required",
        "review_required": True,
        "observed_participating_sha256": image_sha256,
        "approved_participating_sha256": approved_image,
        "approved_manifest_sha256": approved_manifest,
        "reviewed_at": prior.get("reviewed_at"),
        "review_item": {
            "source_id": "table-for-two-roster",
            "kind": "unknown_participating_image",
            "detected_at": detected_at,
            "official_url": OFFICIAL_URL,
            "participating_image_url": image_url,
            "observed_participating_sha256": image_sha256,
            "approved_participating_sha256": approved_image,
        },
    }


def apply_manifest(
    manifest: dict[str, Any], data: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validate_manifest(manifest)
    source = manifest["source"]
    observed = (data.get("source_images") or {}).get("participating_merchants_sha256")
    if observed != source["participating_image_sha256"]:
        raise ValueError("current observed roster image does not match the review")
    if data.get("official_url") != source["official_url"]:
        raise ValueError("current official roster URL does not match the review")
    if data.get("participating_merchants_image_url") != source["participating_image_url"]:
        raise ValueError("current participating-image URL does not match the review")

    current_source = data.get("roster_source") or {}
    if current_source.get("approved_manifest_sha256") == manifest["manifest_sha256"]:
        if (
            current_source.get("status") != "approved"
            or current_source.get("approved_participating_sha256")
            != source["participating_image_sha256"]
            or [stable_venue(record) for record in data.get("venues", [])]
            != manifest["venues"]
        ):
            raise ValueError("applied roster does not match its approved manifest")
        pending = current_source.get("pending_events")
        return copy.deepcopy(data), copy.deepcopy(pending if isinstance(pending, list) else [])
    predecessor = manifest["predecessor"]
    if predecessor["manifest_sha256"] is not None:
        if (
            current_source.get("approved_manifest_sha256")
            != predecessor["manifest_sha256"]
            or current_source.get("approved_participating_sha256")
            != predecessor["participating_image_sha256"]
        ):
            raise ValueError("review predecessor does not match the applied roster lineage")
    elif current_source.get("approved_manifest_sha256") not in {
        None,
        manifest["manifest_sha256"],
    }:
        raise ValueError("a baseline manifest cannot replace an existing lineage")

    old_venues = data.get("venues") or []
    old_by_id = {record["id"]: record for record in old_venues}
    new_venues = []
    for reviewed in manifest["venues"]:
        existing = old_by_id.get(reviewed["id"], {})
        if existing:
            record = copy.deepcopy(existing)
            for field in stable_venue(existing):
                if field not in reviewed:
                    record.pop(field, None)
            for field, value in reviewed.items():
                record[field] = copy.deepcopy(value)
        else:
            record = copy.deepcopy(reviewed)
        new_venues.append(record)

    reviewed_at = manifest["review"]["reviewed_at"]
    review_note = manifest["review"]["note"]
    events = source_change_alert.build_record_update_events(
        "Table for Two",
        {"venues": old_venues},
        {"venues": new_venues},
        {"official_url": source["official_url"], "manual_review_required": False},
        reviewed_at,
    )
    for event in events:
        event["status"] = "published"
        event["reviewed_at"] = reviewed_at
        event["review_note"] = review_note

    updated_data = copy.deepcopy(data)
    updated_data["venues"] = new_venues
    updated_data["roster_source"] = {
        "status": "approved",
        "review_required": False,
        "observed_participating_sha256": source["participating_image_sha256"],
        "approved_participating_sha256": source["participating_image_sha256"],
        "approved_manifest_sha256": manifest["manifest_sha256"],
        "reviewed_at": reviewed_at,
        "review_item": None,
        "pending_events": copy.deepcopy(events),
    }
    try:
        from scripts import scrape_table_for_two as scraper
    except ModuleNotFoundError:
        import scrape_table_for_two as scraper
    other_source_review = any(
        (data.get("source_images") or {}).get(key) != expected
        for key, expected in {
            "voucher_cycles_sha256": scraper.KNOWN_CYCLES_SHA256,
        }.items()
    )
    other_source_review = other_source_review or any(
        (data.get("source_documents") or {}).get(key) != expected
        for key, expected in {
            "terms_sha256": scraper.KNOWN_TERMS_SHA256,
            "faq_sha256": scraper.KNOWN_FAQ_SHA256,
        }.items()
    )
    updated_data["manual_review_required"] = other_source_review

    return updated_data, events
