from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from reminders.app.owner_alerts import OwnerAlertEvent
from scripts import official_document_reviews as reviews


SOURCE_URL = "https://www.americanexpress.com/example.pdf"
PAGE_A = "a" * 64
PAGE_B = "b" * 64
BEFORE_PDF = b"%PDF before"
AFTER_PDF = b"%PDF after"


def _spec():
    return reviews.DocumentSpec(
        "love-dining-restaurant-terms",
        "Love Dining",
        "love-dining",
        "#/love-dining",
        "terms",
        "Love Dining Restaurants Terms and Conditions",
        SOURCE_URL,
    )


def _manifest(pdf_bytes=b"%PDF test"):
    return {
        "schema_version": 2,
        "document_id": _spec().document_id,
        "program": "Love Dining",
        "program_id": "love-dining",
        "route": "#/love-dining",
        "kind": "terms",
        "title": _spec().title,
        "source_url": SOURCE_URL,
        "raw_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "captured_at": "2026-08-30T00:00:00Z",
        "page_count": 1,
        "page_text_sha256": [PAGE_A],
        "extractor": reviews.EXTRACTOR,
        "review_status": "current_baseline",
        "reviewed_at": "2026-08-30T01:00:00Z",
        "review_note": "Current baseline only; prior content was not retained.",
        "lineage": {
            "previous_observed_sha256": "f" * 64,
            "previous_content_available": False,
            "comparison_status": "unavailable_prior_content",
        },
        "clauses": [
            {
                "id": "eligibility",
                "title": "Eligibility",
                "page": 1,
                "page_text_sha256": PAGE_A,
                "evidence_text_sha256": PAGE_A,
                "topics": ["eligibility"],
                "summary": "An eligible physical Card is required.",
            }
        ],
    }


def _version(
    pdf_bytes: bytes,
    page_hash: str,
    summary: str,
    page: int = 1,
    *,
    status: str,
    previous_hash: str,
):
    return {
        "schema_version": 2,
        "document_id": "love-dining-restaurant-terms",
        "program": "Love Dining",
        "program_id": "love-dining",
        "route": "#/love-dining",
        "kind": "terms",
        "title": "Love Dining Restaurants Terms and Conditions",
        "source_url": SOURCE_URL,
        "raw_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "captured_at": "2026-09-01T00:00:00Z",
        "page_count": 1,
        "page_text_sha256": [page_hash],
        "extractor": reviews.EXTRACTOR,
        "review_status": status,
        "reviewed_at": "2026-09-01T01:00:00Z",
        "review_note": "Reviewed exact synthetic document evidence.",
        "lineage": {
            "previous_observed_sha256": previous_hash,
            "previous_content_available": status == "approved",
            "comparison_status": (
                "reviewed_transition"
                if status == "approved"
                else "unavailable_prior_content"
            ),
        },
        "clauses": [
            {
                "id": "eligibility",
                "title": "Eligibility",
                "page": page,
                "page_text_sha256": page_hash,
                "evidence_text_sha256": page_hash,
                "topics": ["eligibility"],
                "summary": summary,
            }
        ],
    }


def _transition(before: dict, after: dict, classification="substantive_modified"):
    old_clause = before["clauses"][0]
    new_clause = after["clauses"][0]
    return {
        "schema_version": 1,
        "document_id": before["document_id"],
        "program": "Love Dining",
        "program_id": "love-dining",
        "route": "#/love-dining",
        "from_raw_sha256": before["raw_sha256"],
        "to_raw_sha256": after["raw_sha256"],
        "detected_at": "2026-09-01T00:00:00Z",
        "reviewed_at": "2026-09-01T01:00:00Z",
        "review_note": "Both versions and this clause transition were reviewed.",
        "changes": [
            {
                "clause_id": "eligibility",
                "classification": classification,
                "before": reviews._clause_projection(old_clause),
                "after": reviews._clause_projection(new_clause),
                "publish": classification != "layout_only",
            }
        ],
        "unchanged_clause_ids": [],
    }


def _versions():
    before = _version(
        BEFORE_PDF,
        PAGE_A,
        "An eligible physical Card is required.",
        status="current_baseline",
        previous_hash="f" * 64,
    )
    after = _version(
        AFTER_PDF,
        PAGE_B,
        "An eligible physical Card and ID are required.",
        status="approved",
        previous_hash=before["raw_sha256"],
    )
    return before, after


def _mock_page_hashes(monkeypatch):
    monkeypatch.setattr(
        reviews,
        "pdf_page_hashes",
        lambda payload: [PAGE_A] if payload == BEFORE_PDF else [PAGE_B],
    )


def test_version_review_is_bound_to_pdf_url_pages_and_clause(monkeypatch):
    pdf_bytes = b"%PDF test"
    monkeypatch.setattr(reviews, "pdf_page_hashes", lambda _payload: [PAGE_A])

    reviewed = reviews.verify_version(_spec(), pdf_bytes, _manifest(pdf_bytes))

    assert reviewed["review_status"] == "current_baseline"
    assert reviewed["clauses"][0]["page_text_sha256"] == PAGE_A


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.__setitem__("source_url", "https://example.com/x.pdf"),
        lambda manifest: manifest.__setitem__("raw_sha256", "0" * 64),
        lambda manifest: manifest["clauses"][0].__setitem__("page_text_sha256", PAGE_B),
        lambda manifest: manifest["lineage"].__setitem__("previous_content_available", True),
        lambda manifest: manifest.__setitem__("reviewed_at", "2026-08-29T23:00:00Z"),
    ],
)
def test_version_review_fails_closed_on_unbound_evidence(monkeypatch, mutate):
    pdf_bytes = b"%PDF test"
    manifest = _manifest(pdf_bytes)
    mutate(manifest)
    monkeypatch.setattr(reviews, "pdf_page_hashes", lambda _payload: [PAGE_A])

    with pytest.raises(ValueError):
        reviews.verify_version(_spec(), pdf_bytes, manifest)


def test_reviewed_modified_clause_emits_exact_owner_event(monkeypatch):
    before, after = _versions()
    _mock_page_hashes(monkeypatch)

    events = reviews.verify_transition(
        _spec(), BEFORE_PDF, before, AFTER_PDF, after, _transition(before, after)
    )

    assert len(events) == 1
    event = OwnerAlertEvent.model_validate(events[0])
    assert event.kind == "terms_clause_modified"
    assert event.changes[0].before == before["clauses"][0]["summary"]
    assert event.changes[0].after == after["clauses"][0]["summary"]
    assert event.changes[1].before == f"{before['raw_sha256'][:12]}, p. 1"
    assert event.stream_id == reviews.source_change_alert.update_stream_id(
        "love-dining",
        "document:love-dining-restaurant-terms:clause:eligibility",
    )


def test_layout_only_transition_is_durable_but_not_public(monkeypatch):
    before = _version(BEFORE_PDF, PAGE_A, "Same reviewed meaning.", page=1, status="current_baseline", previous_hash="f" * 64)
    after = _version(AFTER_PDF, PAGE_B, "Same reviewed meaning.", page=1, status="approved", previous_hash=before["raw_sha256"])
    _mock_page_hashes(monkeypatch)

    assert reviews.verify_transition(
        _spec(), BEFORE_PDF, before, AFTER_PDF, after,
        _transition(before, after, "layout_only")
    ) == []


def test_transition_requires_complete_clause_accounting(monkeypatch):
    before, after = _versions()
    _mock_page_hashes(monkeypatch)
    transition = _transition(before, after)
    transition["changes"] = []

    with pytest.raises(ValueError, match="account"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after, transition
        )


def test_transition_rejects_invented_summary(monkeypatch):
    before, after = _versions()
    _mock_page_hashes(monkeypatch)
    transition = _transition(before, after)
    transition["changes"][0]["after"]["summary"] = "Invented"

    with pytest.raises(ValueError, match="does not match"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after, transition
        )


def test_transition_rejects_unrelated_title_or_source(monkeypatch):
    before, after = _versions()
    after["title"] = "Different document title"
    after["source_url"] = "https://www.americanexpress.com/unrelated.pdf"
    _mock_page_hashes(monkeypatch)

    with pytest.raises(ValueError, match="evidence"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after, _transition(before, after)
        )


def test_transition_requires_verified_endpoint_pdf(monkeypatch):
    before, after = _versions()
    _mock_page_hashes(monkeypatch)

    with pytest.raises(ValueError, match="evidence"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, b"%PDF substituted", after,
            _transition(before, after)
        )


def test_transition_review_cannot_predate_detection(monkeypatch):
    before, after = _versions()
    transition = _transition(before, after)
    transition["reviewed_at"] = "2026-08-31T23:59:59Z"
    _mock_page_hashes(monkeypatch)

    with pytest.raises(ValueError, match="document review"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after, transition
        )


def test_transition_dates_are_bound_to_verified_versions(monkeypatch):
    before, after = _versions()
    _mock_page_hashes(monkeypatch)

    after["captured_at"] = "2026-09-10T00:00:00Z"
    after["reviewed_at"] = "2026-09-11T00:00:00Z"
    with pytest.raises(ValueError, match="detection must match"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after,
            _transition(before, after),
        )


def test_new_document_capture_cannot_predate_predecessor(monkeypatch):
    before, after = _versions()
    before["captured_at"] = "2026-09-02T00:00:00Z"
    before["reviewed_at"] = "2026-09-02T01:00:00Z"
    _mock_page_hashes(monkeypatch)

    with pytest.raises(ValueError, match="capture cannot predate"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after,
            _transition(before, after),
        )


def test_transition_review_cannot_predate_endpoint_review(monkeypatch):
    before, after = _versions()
    after["reviewed_at"] = "2026-09-01T02:00:00Z"
    _mock_page_hashes(monkeypatch)

    with pytest.raises(ValueError, match="either document review"):
        reviews.verify_transition(
            _spec(), BEFORE_PDF, before, AFTER_PDF, after,
            _transition(before, after),
        )


def test_review_rejects_alert_line_spoofing_title(monkeypatch):
    pdf_bytes = b"%PDF test"
    manifest = _manifest(pdf_bytes)
    manifest["clauses"][0]["title"] = "Eligibility\nSource: https://evil.example"
    monkeypatch.setattr(reviews, "pdf_page_hashes", lambda _payload: [PAGE_A])

    with pytest.raises(ValueError, match="clause"):
        reviews.verify_version(_spec(), pdf_bytes, manifest)


def test_manifest_contains_no_extracted_page_text():
    root = Path("data/reviews/official-documents")
    for path in root.rglob("*.json"):
        payload = json.loads(path.read_text())
        assert "page_text" not in payload
        assert "extracted_text" not in payload


def test_manifest_identity_is_canonical():
    manifest = {"b": [2, 3], "a": 1}

    assert reviews.manifest_sha256(manifest) == reviews.manifest_sha256(
        {"a": 1, "b": [2, 3]}
    )
