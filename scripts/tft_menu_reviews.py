#!/usr/bin/env python3
"""Pure, hash-bound review application for concrete TFT menu candidates."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse


MAX_PDF_BYTES = 20 * 1024 * 1024
DECIDABLE_KINDS = {"changed_or_new_venue_menu", "ambiguous_exact_match"}
DECISIONS = {"approved", "rejected"}
VOLATILE_REVIEW_KEYS = {
    "aem_created",
    "checked_at",
    "detected_at",
    "last_seen_at",
}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_item_sha256(item: dict) -> str:
    stable = _stable_review_value(item, {"candidate_id", "review_status", "status"})
    return _canonical_sha256(stable)


def review_observation_sha256(item: dict) -> str:
    stable = _stable_review_value(
        item,
        {"candidate_id", "review_status", "status", "first_detected_at"},
    )
    return _canonical_sha256(stable)


def review_queue_sha256(queue: list[dict]) -> str:
    stable_items = [_stable_review_value(item, set()) for item in queue]
    return _canonical_sha256(
        sorted(stable_items, key=lambda item: json.dumps(item, sort_keys=True))
    )


def _stable_review_value(value: Any, excluded: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_review_value(child, excluded)
            for key, child in value.items()
            if key not in excluded and key not in VOLATILE_REVIEW_KEYS
        }
    if isinstance(value, list):
        return [_stable_review_value(child, excluded) for child in value]
    return value


def _parsed_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_source_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 500 or "\\" in value:
        raise ValueError("candidate source URL is invalid")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not (host == "americanexpress.com" or host.endswith(".americanexpress.com"))
    ):
        raise ValueError("candidate source must be an Amex HTTPS URL")
    return value


def _manifest_projection(item: dict) -> dict:
    return {
        "kind": item.get("kind"),
        "venue_id": item.get("venue_id") or item.get("candidate_venue_id"),
        "card": item.get("card"),
        "filename": item.get("filename"),
        "source_url": item.get("url"),
        "asset_sha256": item.get("sha256"),
        "bytes": item.get("bytes"),
        "aem_uuid": item.get("aem_uuid"),
        "roster_sha256": item.get("roster_sha256"),
        "listing_sha256": item.get("listing_sha256"),
    }


def manifest_sha256(manifest: dict) -> str:
    return _canonical_sha256(manifest)


def prepare_manifest(
    payload: dict,
    candidate_id: str,
    decision: str,
    reviewed_at: str,
    reviewed_by: str,
    review_note: str,
) -> dict:
    menu_source = payload.get("menu_source") or {}
    queue_hash = menu_source.get("review_queue_sha256")
    item = _find_candidate(
        payload,
        {"candidate_id": candidate_id, "review_queue_sha256": queue_hash},
    )
    if item.get("kind") not in DECIDABLE_KINDS:
        raise ValueError("only concrete menu candidates can be decided")
    return {
        "schema_version": 1,
        "program_id": "table-for-two",
        "review_queue_sha256": queue_hash,
        "candidate_id": candidate_id,
        "decision": decision,
        **_manifest_projection(item),
        "reviewed_at": reviewed_at,
        "reviewed_by": reviewed_by,
        "review_note": review_note,
    }


def _find_candidate(payload: dict, manifest: dict) -> dict:
    menu_source = payload.get("menu_source") or {}
    queue = menu_source.get("review_queue") or []
    if menu_source.get("review_queue_sha256") != review_queue_sha256(queue):
        raise ValueError("stored menu review queue fingerprint is invalid")
    if manifest.get("review_queue_sha256") != menu_source.get("review_queue_sha256"):
        raise ValueError("menu review queue changed after the review was prepared")
    matches = [
        item
        for item in queue
        if item.get("candidate_id") == manifest.get("candidate_id")
        and review_item_sha256(item) == manifest.get("candidate_id")
    ]
    if len(matches) != 1:
        raise ValueError("review candidate is missing, duplicated, or stale")
    return matches[0]


def verify_review(
    payload: dict,
    manifest: dict,
    pdf_bytes: bytes | None = None,
    now: datetime | None = None,
) -> tuple[dict, str]:
    if manifest.get("schema_version") != 1 or manifest.get("program_id") != "table-for-two":
        raise ValueError("invalid TFT menu review manifest")
    decision = manifest.get("decision")
    if decision not in DECISIONS:
        raise ValueError("menu review decision must be approved or rejected")
    item = _find_candidate(payload, manifest)
    if item.get("kind") not in DECIDABLE_KINDS:
        raise ValueError("only concrete menu candidates can be decided")
    expected = _manifest_projection(item)
    supplied = {key: manifest.get(key) for key in expected}
    if supplied != expected:
        raise ValueError("menu review manifest does not match candidate provenance")
    venue_id = expected["venue_id"]
    if not isinstance(venue_id, str) or not venue_id:
        raise ValueError("candidate must resolve to one reviewed venue")
    if item.get("candidate_venue_ids") not in (None, [venue_id]):
        raise ValueError("ambiguous candidate has multiple venue claimants")
    if expected["card"] not in {"platinum", "centurion"}:
        raise ValueError("candidate card is invalid")
    if not isinstance(expected["filename"], str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._ -]{0,180}\.pdf", expected["filename"], re.I
    ) is None:
        raise ValueError("candidate filename is unsafe")
    _validate_source_url(expected["source_url"])
    for field in ("asset_sha256", "roster_sha256", "listing_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(expected[field])) is None:
            raise ValueError(f"candidate {field} is invalid")
    if not isinstance(expected["bytes"], int) or not 1 <= expected["bytes"] <= MAX_PDF_BYTES:
        raise ValueError("candidate byte count is invalid")
    if not isinstance(manifest.get("reviewed_by"), str) or not 1 <= len(manifest["reviewed_by"]) <= 100:
        raise ValueError("reviewed_by is required")
    if not isinstance(manifest.get("review_note"), str) or not 1 <= len(manifest["review_note"]) <= 500:
        raise ValueError("review note is required")
    detected_at = _parsed_utc(
        item.get("first_detected_at") or item.get("detected_at"),
        "first_detected_at",
    )
    reviewed_at = _parsed_utc(manifest.get("reviewed_at"), "reviewed_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if reviewed_at < detected_at or reviewed_at > current + timedelta(minutes=5):
        raise ValueError("review chronology is invalid")
    if decision == "approved":
        if pdf_bytes is None:
            raise ValueError("approval requires the reviewed local PDF")
        if len(pdf_bytes) > MAX_PDF_BYTES or not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("reviewed candidate is not a bounded PDF")
        if len(pdf_bytes) != expected["bytes"] or hashlib.sha256(pdf_bytes).hexdigest() != expected["asset_sha256"]:
            raise ValueError("reviewed PDF does not match candidate bytes")
    elif pdf_bytes is not None:
        raise ValueError("rejection does not accept PDF bytes")
    return item, manifest_sha256(manifest)


def _published_menu(item: dict, manifest: dict, digest: str) -> dict:
    previous = item.get("previous") or {}
    detected_at = item["detected_at"]
    return {
        "status": "published",
        "url": item["url"],
        "filename": item["filename"],
        "card": item["card"],
        "label": "Platinum" if item["card"] == "platinum" else "Centurion",
        "checked_at": detected_at,
        "first_seen_at": detected_at,
        "last_seen_at": detected_at,
        "sha256": item["sha256"],
        "bytes": item["bytes"],
        "aem_created": item.get("aem_created"),
        "aem_uuid": item.get("aem_uuid"),
        "changed_at": manifest["reviewed_at"] if previous else None,
        "review_manifest_sha256": digest,
        "reviewed_at": manifest["reviewed_at"],
    }


def _owner_event(item: dict, manifest: dict, venue_name: str) -> dict:
    digest = manifest_sha256(manifest)
    previous = item.get("previous") or {}
    published = _published_menu(item, manifest, digest)
    before_filename = previous.get("filename") or "Not published"
    before_hash = previous.get("sha256")
    before_version = before_hash[:12] if before_hash else "Not published"
    venue_id = _manifest_projection(item)["venue_id"]
    return {
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": f"#/table-for-two?venue={venue_id}",
        "kind": "menu_added" if not previous else "menu_updated",
        "subject": f"{venue_name} · {published['label']} menu",
        "detected_at": item["detected_at"],
        "status": "published",
        "before": {
            "state": "published" if previous else "not_published",
            "fields": {
                "Menu file": before_filename,
                "Menu version": before_version,
            },
        },
        "after": {
            "state": "published",
            "fields": {
                "Menu file": published["filename"],
                "Menu version": published["sha256"][:12],
            },
        },
        "changes": [
            {
                "field": "Menu file",
                "before": before_filename,
                "after": published["filename"],
            },
            {
                "field": "Menu version",
                "before": before_version,
                "after": published["sha256"][:12],
            },
        ],
        "source_url": published["url"],
        "reviewed_at": manifest["reviewed_at"],
        "review_note": manifest["review_note"],
        "entity_key": f"record:{venue_id}:menu:{item['card']}",
    }


def apply_review(
    payload: dict,
    manifest: dict,
    pdf_bytes: bytes | None = None,
    now: datetime | None = None,
) -> tuple[dict, dict | None]:
    menu_source = payload.get("menu_source") or {}
    prior_decisions = menu_source.get("review_decisions") or []
    digest = manifest_sha256(manifest)
    existing = [entry for entry in prior_decisions if entry.get("candidate_id") == manifest.get("candidate_id")]
    if existing:
        if len(existing) == 1 and existing[0].get("manifest_sha256") == digest:
            return copy.deepcopy(payload), None
        raise ValueError("candidate already has a different terminal decision")
    item, digest = verify_review(payload, manifest, pdf_bytes, now)
    updated = copy.deepcopy(payload)
    source = updated["menu_source"]
    queue = source.get("review_queue") or []
    source["review_queue"] = [entry for entry in queue if entry.get("candidate_id") != item["candidate_id"]]
    receipt = {
        "candidate_id": item["candidate_id"],
        "decision": manifest["decision"],
        "manifest_sha256": digest,
        "reviewed_at": manifest["reviewed_at"],
        "reviewed_by": manifest["reviewed_by"],
        "review_note": manifest["review_note"],
        "candidate": {**_manifest_projection(item), "previous": item.get("previous")},
        "candidate_item": copy.deepcopy(item),
        "manifest": copy.deepcopy(manifest),
        "owner_event": None,
    }
    source["review_decisions"] = [*prior_decisions, receipt]
    event = None
    if manifest["decision"] == "approved":
        venue_id = _manifest_projection(item)["venue_id"]
        matches = [venue for venue in updated.get("venues") or [] if venue.get("id") == venue_id]
        if len(matches) != 1:
            raise ValueError("reviewed venue is missing or duplicated")
        venue = matches[0]
        previous = item.get("previous") or {}
        active = (venue.get("menu_pdfs") or {}).get(item["card"]) or {}
        if active != previous:
            raise ValueError("active menu changed after candidate detection")
        published = _published_menu(item, manifest, digest)
        venue.setdefault("menu_pdfs", {})[item["card"]] = published
        if item["card"] == "platinum":
            venue["menu_pdf"] = published
        event = _owner_event(item, manifest, venue["name"])
        receipt["owner_event"] = copy.deepcopy(event)
    source["review_queue_count"] = len(source["review_queue"])
    source["review_queue_sha256"] = review_queue_sha256(source["review_queue"])
    source["venues_review"] = len(
        {
            entry.get("venue_id")
            for entry in source["review_queue"]
            if entry.get("kind") == "missing_venue_menu" and entry.get("venue_id")
        }
    )
    source["review_required"] = bool(source["review_queue"] or source.get("venues_review"))
    return updated, event


def verify_decision_receipts(payload: dict) -> None:
    decisions = (payload.get("menu_source") or {}).get("review_decisions") or []
    candidate_ids = [entry.get("candidate_id") for entry in decisions]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("TFT menu decision candidate IDs must be unique")
    latest_approved: dict[tuple[str, str], tuple[datetime, dict]] = {}
    approved_by_manifest = {}
    venues = {venue.get("id"): venue for venue in payload.get("venues") or []}
    for entry in decisions:
        candidate = entry.get("candidate") or {}
        candidate_item = entry.get("candidate_item") or {}
        manifest = entry.get("manifest") or {}
        candidate_projection = {
            key: candidate.get(key)
            for key in (
                "kind",
                "venue_id",
                "card",
                "filename",
                "source_url",
                "asset_sha256",
                "bytes",
                "aem_uuid",
                "roster_sha256",
                "listing_sha256",
            )
        }
        manifest_projection = {
            key: manifest.get(key) for key in candidate_projection
        }
        if (
            re.fullmatch(r"[0-9a-f]{64}", str(entry.get("candidate_id"))) is None
            or entry.get("decision") not in DECISIONS
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("manifest_sha256"))) is None
            or manifest_sha256(manifest) != entry.get("manifest_sha256")
            or manifest.get("candidate_id") != entry.get("candidate_id")
            or manifest.get("decision") != entry.get("decision")
            or manifest_projection != candidate_projection
            or manifest.get("reviewed_at") != entry.get("reviewed_at")
            or manifest.get("reviewed_by") != entry.get("reviewed_by")
            or manifest.get("review_note") != entry.get("review_note")
            or review_item_sha256(candidate_item) != entry.get("candidate_id")
            or _manifest_projection(candidate_item) != candidate_projection
            or manifest.get("schema_version") != 1
            or manifest.get("program_id") != "table-for-two"
            or re.fullmatch(
                r"[0-9a-f]{64}", str(manifest.get("review_queue_sha256"))
            )
            is None
        ):
            raise ValueError("invalid TFT menu decision receipt")
        if candidate_item.get("kind") not in DECIDABLE_KINDS:
            raise ValueError("invalid TFT menu decision receipt")
        _validate_source_url(candidate.get("source_url"))
        if candidate.get("card") not in {"platinum", "centurion"}:
            raise ValueError("invalid TFT menu decision receipt")
        if not isinstance(candidate.get("filename"), str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._ -]{0,180}\.pdf",
            candidate["filename"],
            re.I,
        ) is None:
            raise ValueError("invalid TFT menu decision receipt")
        for field in ("asset_sha256", "roster_sha256", "listing_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", str(candidate.get(field))) is None:
                raise ValueError("invalid TFT menu decision receipt")
        if not isinstance(candidate.get("bytes"), int) or not 1 <= candidate["bytes"] <= MAX_PDF_BYTES:
            raise ValueError("invalid TFT menu decision receipt")
        if not isinstance(entry.get("reviewed_by"), str) or not 1 <= len(entry["reviewed_by"]) <= 100:
            raise ValueError("invalid TFT menu decision receipt")
        if not isinstance(entry.get("review_note"), str) or not 1 <= len(entry["review_note"]) <= 500:
            raise ValueError("invalid TFT menu decision receipt")
        reviewed_at = _parsed_utc(entry.get("reviewed_at"), "reviewed_at")
        detected_at = _parsed_utc(
            candidate_item.get("first_detected_at")
            or candidate_item.get("detected_at"),
            "first_detected_at",
        )
        if reviewed_at < detected_at:
            raise ValueError("invalid TFT menu decision receipt")
        if entry["decision"] != "approved":
            if entry.get("owner_event") is not None:
                raise ValueError("rejected TFT menu decision cannot publish an event")
            continue
        event = entry.get("owner_event") or {}
        venue = venues.get(candidate.get("venue_id"))
        expected_event = _owner_event(
            candidate_item,
            manifest,
            str((venue or {}).get("name") or ""),
        )
        if (
            not venue
            or event != expected_event
        ):
            raise ValueError("approved TFT menu decision has an invalid owner event")
        approved_by_manifest[entry["manifest_sha256"]] = entry
        key = (str(candidate.get("venue_id")), str(candidate.get("card")))
        if key not in latest_approved or reviewed_at > latest_approved[key][0]:
            latest_approved[key] = (reviewed_at, entry)
    for (_venue_id, _card), (_reviewed_at, entry) in latest_approved.items():
        candidate = entry["candidate"]
        venue = venues.get(candidate.get("venue_id"))
        active = ((venue or {}).get("menu_pdfs") or {}).get(candidate.get("card")) or {}
        if (
            active.get("status") != "published"
            or active.get("filename") != candidate.get("filename")
            or active.get("url") != candidate.get("source_url")
            or active.get("sha256") != candidate.get("asset_sha256")
            or active.get("review_manifest_sha256") != entry["manifest_sha256"]
        ):
            raise ValueError("latest approved TFT menu decision does not match active menu")
    for venue in payload.get("venues") or []:
        for menu in (venue.get("menu_pdfs") or {}).values():
            digest = menu.get("review_manifest_sha256")
            if digest is not None and digest not in approved_by_manifest:
                raise ValueError("reviewed TFT menu lacks an approved decision receipt")
