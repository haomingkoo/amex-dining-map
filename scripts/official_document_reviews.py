"""Hash-bound review and transition validation for official PDF documents."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import pypdf
from pypdf import PdfReader

from scripts import source_change_alert


EXTRACTOR = "pypdf 6.16.2 extract_text normalized-whitespace-v1"
SUPPORTED_EXTRACTORS = {
    EXTRACTOR,
    "pypdf 6.15.0 extract_text normalized-whitespace-v1",
}
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 100
MAX_PAGE_CHARACTERS = 50_000
HASH = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9-]{1,64}$")


@dataclass(frozen=True)
class DocumentSpec:
    document_id: str
    program: str
    program_id: str
    route: str
    kind: str
    title: str
    source_url: str


def _aware_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be an aware timestamp")
    return value


def _parsed_timestamp(value: Any, field: str) -> datetime:
    checked = _aware_timestamp(value, field)
    return datetime.fromisoformat(checked.replace("Z", "+00:00"))


def _official_url(value: Any, expected: str) -> str:
    if value != expected:
        raise ValueError("document source URL does not match the fixed source")
    parsed = urlparse(str(value))
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not (host == "americanexpress.com" or host.endswith(".americanexpress.com"))
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("document source must be a fixed Amex HTTPS URL")
    return str(value)


def pdf_page_hashes(pdf_bytes: bytes) -> list[str]:
    if pypdf.__version__ != "6.16.2":
        raise ValueError(f"expected pypdf 6.16.2, found {pypdf.__version__}")
    if len(pdf_bytes) > MAX_PDF_BYTES or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("official document is not a bounded PDF")
    reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
        raise ValueError("unsupported official PDF structure")
    hashes = []
    for page in reader.pages:
        normalized = " ".join((page.extract_text() or "").split())
        if not normalized or len(normalized) > MAX_PAGE_CHARACTERS:
            raise ValueError("official PDF page text is empty or oversized")
        hashes.append(hashlib.sha256(normalized.encode()).hexdigest())
    return hashes


def manifest_sha256(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validated_clauses(manifest: dict, page_hashes: list[str]) -> list[dict]:
    clauses = manifest.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise ValueError("reviewed document must contain clauses")
    seen = set()
    validated = []
    for clause in clauses:
        clause_id = clause.get("id") if isinstance(clause, dict) else None
        title = clause.get("title") if isinstance(clause, dict) else None
        page = clause.get("page") if isinstance(clause, dict) else None
        topics = clause.get("topics") if isinstance(clause, dict) else None
        summary = clause.get("summary") if isinstance(clause, dict) else None
        if (
            not isinstance(clause_id, str)
            or IDENTIFIER.fullmatch(clause_id) is None
            or clause_id in seen
            or not isinstance(title, str)
            or not 1 <= len(title) <= 120
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in title)
            or not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= len(page_hashes)
            or not isinstance(topics, list)
            or not 1 <= len(topics) <= 20
            or any(not isinstance(topic, str) or not 1 <= len(topic) <= 80 for topic in topics)
            or not isinstance(summary, str)
            or not 1 <= len(summary) <= 500
            or any(ord(character) < 32 and character not in "\n\t" for character in summary)
            or clause.get("page_text_sha256") != page_hashes[page - 1]
            or clause.get("evidence_text_sha256") != page_hashes[page - 1]
        ):
            raise ValueError(f"invalid reviewed clause: {clause_id}")
        seen.add(clause_id)
        validated.append(dict(clause))
    return validated


def verify_version(spec: DocumentSpec, pdf_bytes: bytes, manifest: dict) -> dict:
    raw_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    page_hashes = pdf_page_hashes(pdf_bytes)
    if (
        manifest.get("schema_version") != 2
        or manifest.get("document_id") != spec.document_id
        or manifest.get("program") != spec.program
        or manifest.get("program_id") != spec.program_id
        or manifest.get("route") != spec.route
        or manifest.get("kind") != spec.kind
        or manifest.get("title") != spec.title
        or manifest.get("raw_sha256") != raw_sha256
        or manifest.get("extractor") not in SUPPORTED_EXTRACTORS
        or manifest.get("page_count") != len(page_hashes)
        or manifest.get("page_text_sha256") != page_hashes
        or manifest.get("review_status") not in {"current_baseline", "approved"}
    ):
        raise ValueError("document review evidence does not match the PDF")
    _official_url(manifest.get("source_url"), spec.source_url)
    captured_at = _parsed_timestamp(manifest.get("captured_at"), "captured_at")
    reviewed_at = _parsed_timestamp(manifest.get("reviewed_at"), "reviewed_at")
    if captured_at > reviewed_at:
        raise ValueError("document review cannot predate capture")
    note = manifest.get("review_note")
    if not isinstance(note, str) or not 1 <= len(note) <= 500:
        raise ValueError("review note is required")
    lineage = manifest.get("lineage")
    if manifest["review_status"] == "current_baseline":
        previous_observed = lineage.get("previous_observed_sha256") if isinstance(lineage, dict) else None
        if (
            not isinstance(lineage, dict)
            or previous_observed is not None
            and HASH.fullmatch(str(previous_observed)) is None
            or lineage.get("previous_content_available") is not False
            or lineage.get("comparison_status") != "unavailable_prior_content"
        ):
            raise ValueError("current baseline must disclose unavailable prior content")
    else:
        if (
            not isinstance(lineage, dict)
            or HASH.fullmatch(str(lineage.get("previous_observed_sha256"))) is None
            or lineage.get("previous_content_available") is not True
            or lineage.get("comparison_status") != "reviewed_transition"
        ):
            raise ValueError("approved version must disclose its reviewed predecessor")
    clauses = _validated_clauses(manifest, page_hashes)
    return dict(manifest) | {"clauses": clauses}


def _clause_projection(clause: dict) -> dict:
    return {
        "title": clause["title"],
        "page": clause["page"],
        "page_text_sha256": clause["page_text_sha256"],
        "evidence_text_sha256": clause["evidence_text_sha256"],
        "topics": clause["topics"],
        "summary": clause["summary"],
    }


def _clause_semantics(clause: dict) -> tuple[str, tuple[str, ...], str]:
    return clause["title"], tuple(clause["topics"]), clause["summary"]


def _event_snapshot(version: dict, clause: dict | None) -> dict:
    if clause is None:
        return {"state": "not_present", "fields": {}}
    return {
        "state": "present",
        "fields": {
            "Document": version["title"],
            "Document version": version["raw_sha256"],
            "Clause": clause["title"],
            "Summary": clause["summary"],
            "Page": clause["page"],
        },
    }


def verify_transition(
    spec: DocumentSpec,
    before_pdf_bytes: bytes,
    before_manifest: dict,
    after_pdf_bytes: bytes,
    after_manifest: dict,
    transition: dict,
) -> list[dict]:
    before = verify_version(spec, before_pdf_bytes, before_manifest)
    after = verify_version(spec, after_pdf_bytes, after_manifest)
    if (
        before.get("document_id") != spec.document_id
        or after.get("document_id") != spec.document_id
        or before.get("program") != spec.program
        or after.get("program") != spec.program
        or before.get("program_id") != spec.program_id
        or after.get("program_id") != spec.program_id
        or before.get("route") != spec.route
        or after.get("route") != spec.route
        or before.get("kind") != spec.kind
        or after.get("kind") != spec.kind
        or before.get("title") != spec.title
        or after.get("title") != spec.title
        or before.get("source_url") != spec.source_url
        or after.get("source_url") != spec.source_url
        or before.get("review_status") not in {"current_baseline", "approved"}
        or after.get("review_status") != "approved"
        or HASH.fullmatch(str(before.get("raw_sha256"))) is None
        or HASH.fullmatch(str(after.get("raw_sha256"))) is None
        or (after.get("lineage") or {}).get("previous_observed_sha256")
        != before.get("raw_sha256")
        or transition.get("schema_version") != 1
        or transition.get("document_id") != before.get("document_id")
        or transition.get("document_id") != after.get("document_id")
        or transition.get("from_raw_sha256") != before.get("raw_sha256")
        or transition.get("to_raw_sha256") != after.get("raw_sha256")
        or transition.get("from_raw_sha256") == transition.get("to_raw_sha256")
        or transition.get("program") != before.get("program")
        or transition.get("program") != after.get("program")
        or transition.get("program_id") != before.get("program_id")
        or transition.get("program_id") != after.get("program_id")
        or transition.get("route") != before.get("route")
        or transition.get("route") != after.get("route")
    ):
        raise ValueError("invalid document transition endpoints")
    _official_url(before["source_url"], spec.source_url)
    _official_url(after["source_url"], spec.source_url)
    before_captured_at = _parsed_timestamp(before["captured_at"], "before captured_at")
    after_captured_at = _parsed_timestamp(after["captured_at"], "after captured_at")
    detected_at = _aware_timestamp(transition.get("detected_at"), "detected_at")
    reviewed_at = _aware_timestamp(transition.get("reviewed_at"), "reviewed_at")
    detected = _parsed_timestamp(detected_at, "detected_at")
    reviewed = _parsed_timestamp(reviewed_at, "reviewed_at")
    if before_captured_at > after_captured_at:
        raise ValueError("new document capture cannot predate its predecessor")
    if detected != after_captured_at:
        raise ValueError("transition detection must match the new document capture")
    if reviewed < max(
        _parsed_timestamp(before["reviewed_at"], "before reviewed_at"),
        _parsed_timestamp(after["reviewed_at"], "after reviewed_at"),
    ):
        raise ValueError("transition review cannot predate either document review")
    review_note = transition.get("review_note")
    if not isinstance(review_note, str) or not 1 <= len(review_note) <= 500:
        raise ValueError("transition review note is required")
    old = {clause["id"]: clause for clause in before.get("clauses") or []}
    new = {clause["id"]: clause for clause in after.get("clauses") or []}
    unchanged = transition.get("unchanged_clause_ids")
    changes = transition.get("changes")
    if not isinstance(unchanged, list) or not isinstance(changes, list):
        raise ValueError("transition clause accounting is required")
    accounted_old = set()
    accounted_new = set()
    for clause_id in unchanged:
        if (
            clause_id in accounted_old
            or clause_id not in old
            or clause_id not in new
            or _clause_projection(old[clause_id]) != _clause_projection(new[clause_id])
        ):
            raise ValueError(f"invalid unchanged clause: {clause_id}")
        accounted_old.add(clause_id)
        accounted_new.add(clause_id)

    events = []
    clause_kind = "faq" if spec.kind == "faq" else "terms"
    kinds = {
        "added": f"{clause_kind}_clause_added",
        "removed": f"{clause_kind}_clause_removed",
        "substantive_modified": f"{clause_kind}_clause_modified",
        "layout_only": f"{clause_kind}_clause_modified",
    }
    for change in changes:
        clause_id = change.get("clause_id") if isinstance(change, dict) else None
        classification = change.get("classification") if isinstance(change, dict) else None
        if clause_id not in old and clause_id not in new or classification not in kinds:
            raise ValueError(f"invalid changed clause: {clause_id}")
        old_clause = old.get(clause_id)
        new_clause = new.get(clause_id)
        expected_before = _clause_projection(old_clause) if old_clause else None
        expected_after = _clause_projection(new_clause) if new_clause else None
        if (
            change.get("before") != expected_before
            or change.get("after") != expected_after
            or classification == "added" and (old_clause is not None or new_clause is None)
            or classification == "removed" and (old_clause is None or new_clause is not None)
            or classification in {"substantive_modified", "layout_only"}
            and (old_clause is None or new_clause is None)
            or classification == "layout_only"
            and _clause_semantics(old_clause) != _clause_semantics(new_clause)
            or classification == "substantive_modified"
            and _clause_semantics(old_clause) == _clause_semantics(new_clause)
            or change.get("publish") is not (classification != "layout_only")
        ):
            raise ValueError(f"clause transition does not match reviewed versions: {clause_id}")
        if old_clause:
            if clause_id in accounted_old:
                raise ValueError(f"duplicate old clause accounting: {clause_id}")
            accounted_old.add(clause_id)
        if new_clause:
            if clause_id in accounted_new:
                raise ValueError(f"duplicate new clause accounting: {clause_id}")
            accounted_new.add(clause_id)
        if classification == "layout_only":
            continue
        current_clause = new_clause or old_clause
        page_before = old_clause["page"] if old_clause else None
        page_after = new_clause["page"] if new_clause else None
        event = {
            "program": before["program"],
            "program_id": before["program_id"],
            "route": before["route"],
            "kind": kinds[classification],
            "subject": f"{after['title']} · {current_clause['title']}",
            "detected_at": detected_at,
            "reviewed_at": reviewed_at,
            "review_note": review_note,
            "status": "published",
            "before": _event_snapshot(before, old_clause),
            "after": _event_snapshot(after, new_clause),
            "changes": [
                {
                    "field": current_clause["title"],
                    "before": old_clause["summary"] if old_clause else "Not present",
                    "after": new_clause["summary"] if new_clause else "Removed",
                },
                {
                    "field": "Page evidence",
                    "before": f"{before['raw_sha256'][:12]}, p. {page_before}" if old_clause else "Not present",
                    "after": f"{after['raw_sha256'][:12]}, p. {page_after}" if new_clause else "Removed",
                },
            ],
            "source_url": after["source_url"],
        }
        source_change_alert.assign_event_identity(
            event, f"document:{before['document_id']}:clause:{clause_id}"
        )
        events.append(event)
    if accounted_old != set(old) or accounted_new != set(new):
        raise ValueError("transition does not account for every reviewed clause")
    return events
