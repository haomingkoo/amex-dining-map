from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import (
    apply_tft_document_review,
    source_change_alert,
    tft_document_reviews,
)


DOCUMENT_ID = "tft-terms"
BEFORE_PDF = b"%PDF-before-reviewed-bytes"
AFTER_PDF = b"%PDF-after-reviewed-bytes"
BEFORE_SHA = hashlib.sha256(BEFORE_PDF).hexdigest()
AFTER_SHA = hashlib.sha256(AFTER_PDF).hexdigest()
SOURCE_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/TableforTwo-Plat-TnCs.pdf"


def manifest(raw_sha: str, previous: str | None, reviewed_at: str) -> dict:
    return {
        "schema_version": 2,
        "document_id": DOCUMENT_ID,
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": "#/table-for-two",
        "kind": "terms",
        "title": "Table for Two - Platinum Edition Terms and Conditions",
        "source_url": SOURCE_URL,
        "raw_sha256": raw_sha,
        "extractor": "pypdf 6.15.0 extract_text normalized-whitespace-v1",
        "page_count": 1,
        "page_text_sha256": ["1" * 64],
        "captured_at": reviewed_at,
        "reviewed_at": reviewed_at,
        "review_status": "approved" if previous else "current_baseline",
        "review_note": "Complete reviewed test document.",
        "lineage": {
            "previous_observed_sha256": previous,
            "previous_content_available": previous is not None,
            "comparison_status": "reviewed_transition" if previous else "unavailable_prior_content",
        },
        "clauses": [],
    }


BEFORE_MANIFEST = manifest(BEFORE_SHA, None, "2026-08-01T00:00:00Z")
AFTER_MANIFEST = manifest(AFTER_SHA, BEFORE_SHA, "2026-09-01T00:00:00Z")
TRANSITION = {
    "schema_version": 1,
    "document_id": DOCUMENT_ID,
    "from_raw_sha256": BEFORE_SHA,
    "to_raw_sha256": AFTER_SHA,
    "program": "Table for Two",
    "program_id": "table-for-two",
    "route": "#/table-for-two",
    "detected_at": "2026-09-01T00:00:00Z",
    "reviewed_at": "2026-09-01T01:00:00Z",
    "review_note": "Reviewed every clause against both exact PDFs.",
    "unchanged_clause_ids": [],
    "changes": [],
}


def source() -> dict:
    return {
        "official_url": "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/",
        "terms_url": SOURCE_URL,
        "faq_url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining/TableforTwo_FAQ.pdf",
        "source_documents": {"terms_sha256": AFTER_SHA, "faq_sha256": "f" * 64},
        "source_images": {"voucher_cycles_sha256": "a" * 64},
        "roster_source": {"review_required": False},
        "document_reviews": {
            DOCUMENT_ID: {
                "status": "review_required",
                "review_required": True,
                "observed_sha256": AFTER_SHA,
                "approved_sha256": BEFORE_SHA,
                "approved_manifest_sha256": tft_document_reviews.manifest_sha256(BEFORE_MANIFEST),
                "approved_captured_at": BEFORE_MANIFEST["captured_at"],
                "reviewed_at": BEFORE_MANIFEST["reviewed_at"],
                "review_item": {"kind": "unreviewed_official_document"},
            },
            "tft-faq": {
                "status": "approved",
                "review_required": False,
                "observed_sha256": "f" * 64,
                "approved_sha256": "f" * 64,
                "approved_manifest_sha256": "e" * 64,
                "review_item": None,
            },
        },
        "manual_review_required": True,
    }


def owner_event() -> dict:
    event = {
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": "#/table-for-two",
        "kind": "terms_clause_modified",
        "subject": "Table for Two terms · Eligibility",
        "detected_at": "2026-09-01T00:00:00Z",
        "reviewed_at": "2026-09-01T01:00:00Z",
        "review_note": "Reviewed exact predecessor and successor PDFs.",
        "status": "published",
        "before": {"state": "present", "fields": {"Summary": "Before"}},
        "after": {"state": "present", "fields": {"Summary": "After"}},
        "changes": [{"field": "Eligibility", "before": "Before", "after": "After"}],
        "source_url": SOURCE_URL,
    }
    source_change_alert.assign_event_identity(
        event, "document:tft-terms:clause:eligibility"
    )
    return event


def test_unknown_observed_hash_retains_approved_document_and_scopes_review():
    current = source()
    current["source_documents"]["terms_sha256"] = BEFORE_SHA
    current["document_reviews"][DOCUMENT_ID].update(
        status="approved",
        review_required=False,
        observed_sha256=BEFORE_SHA,
        review_item=None,
    )

    states = tft_document_reviews.refresh_states(
        {"terms_sha256": AFTER_SHA, "faq_sha256": "f" * 64},
        current,
        "2026-09-01T00:00:00Z",
    )

    terms = states[DOCUMENT_ID]
    assert terms["status"] == "review_required"
    assert terms["observed_sha256"] == AFTER_SHA
    assert terms["approved_sha256"] == BEFORE_SHA
    assert terms["review_item"]["document_id"] == DOCUMENT_ID
    assert states["tft-faq"]["status"] == "approved"


def test_refresh_does_not_erase_interrupted_pending_owner_events():
    current = source()
    current["source_documents"]["terms_sha256"] = BEFORE_SHA
    current["document_reviews"][DOCUMENT_ID].update(
        status="approved",
        review_required=False,
        observed_sha256=BEFORE_SHA,
        approved_sha256=BEFORE_SHA,
        pending_events=[owner_event()],
    )

    states = tft_document_reviews.refresh_states(
        {"terms_sha256": BEFORE_SHA, "faq_sha256": "f" * 64},
        current,
        "2026-09-01T00:00:00Z",
    )

    assert states[DOCUMENT_ID]["pending_events"] == [owner_event()]


def test_repeated_pending_refresh_preserves_first_detection_time():
    current = source()
    current["document_reviews"][DOCUMENT_ID]["review_item"]["detected_at"] = (
        "2026-09-01T00:00:00Z"
    )

    states = tft_document_reviews.refresh_states(
        {"terms_sha256": AFTER_SHA, "faq_sha256": "f" * 64},
        current,
        "2026-09-02T00:00:00Z",
    )

    assert (
        states[DOCUMENT_ID]["review_item"]["detected_at"]
        == "2026-09-01T00:00:00Z"
    )


def test_apply_preserves_other_document_and_sets_resumable_events(monkeypatch):
    expected_event = owner_event()
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [copy.deepcopy(expected_event)],
    )
    monkeypatch.setattr(
        apply_tft_document_review, "_recompute_manual_review", lambda _source: False
    )
    current = source()
    faq = copy.deepcopy(current["document_reviews"]["tft-faq"])

    updated, events = apply_tft_document_review.apply_review(
        current,
        DOCUMENT_ID,
        BEFORE_PDF,
        BEFORE_MANIFEST,
        AFTER_PDF,
        AFTER_MANIFEST,
        TRANSITION,
    )

    assert events == [expected_event]
    assert updated["document_reviews"]["tft-faq"] == faq
    terms = updated["document_reviews"][DOCUMENT_ID]
    assert terms["approved_sha256"] == AFTER_SHA
    assert terms["review_required"] is False
    assert terms["pending_events"] == events
    assert updated["manual_review_required"] is False


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare_files(tmp_path: Path):
    data = tmp_path / "table-for-two.json"
    updates = tmp_path / "updates.json"
    manifests = tmp_path / "manifests"
    pdfs = tmp_path / "pdfs"
    transitions = tmp_path / "transitions"
    write_json(data, source())
    write_json(updates, {"schema_version": 1, "updates": []})
    before_manifest_path = manifests / DOCUMENT_ID / f"{BEFORE_SHA}.json"
    after_manifest_path = manifests / DOCUMENT_ID / f"{AFTER_SHA}.json"
    transition_path = (
        transitions / DOCUMENT_ID / f"{BEFORE_SHA}-to-{AFTER_SHA}.json"
    )
    write_json(before_manifest_path, BEFORE_MANIFEST)
    write_json(after_manifest_path, AFTER_MANIFEST)
    write_json(transition_path, TRANSITION)
    before_pdf_path = pdfs / DOCUMENT_ID / f"{BEFORE_SHA}.pdf"
    before_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    before_pdf_path.write_bytes(BEFORE_PDF)
    after_pdf_path = tmp_path / "after.pdf"
    after_pdf_path.write_bytes(AFTER_PDF)
    return (
        data,
        updates,
        manifests,
        pdfs,
        transitions,
        after_manifest_path,
        transition_path,
        after_pdf_path,
    )


def test_commit_recovers_after_ledger_failure(tmp_path, monkeypatch):
    data, updates, manifests, pdfs, transitions, after_manifest, transition, after_pdf = prepare_files(tmp_path)
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [owner_event()],
    )
    monkeypatch.setattr(
        apply_tft_document_review, "_recompute_manual_review", lambda _source: False
    )
    real_append = source_change_alert.append_updates
    monkeypatch.setattr(
        source_change_alert,
        "append_updates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ledger crash")),
    )

    with pytest.raises(RuntimeError, match="ledger crash"):
        apply_tft_document_review.commit_review(
            DOCUMENT_ID, after_manifest, transition, data, updates, after_pdf, manifests, pdfs, transitions
        )
    interrupted = json.loads(data.read_text())
    assert interrupted["document_reviews"][DOCUMENT_ID]["pending_events"]

    interrupted["source_documents"]["terms_sha256"] = "c" * 64
    interrupted["document_reviews"] = tft_document_reviews.refresh_states(
        {"terms_sha256": "c" * 64, "faq_sha256": "f" * 64},
        interrupted,
        "2026-09-02T00:00:00Z",
    )
    write_json(data, interrupted)

    monkeypatch.setattr(source_change_alert, "append_updates", real_append)
    apply_tft_document_review.commit_review(
        DOCUMENT_ID, after_manifest, transition, data, updates, after_pdf, manifests, pdfs, transitions
    )
    committed = json.loads(data.read_text())
    ledger = json.loads(updates.read_text())
    assert "pending_events" not in committed["document_reviews"][DOCUMENT_ID]
    assert len(ledger["updates"]) == 1


def test_pending_event_blocks_a_different_successor(monkeypatch):
    current = source()
    current["document_reviews"][DOCUMENT_ID].update(
        approved_sha256=AFTER_SHA,
        approved_manifest_sha256=tft_document_reviews.manifest_sha256(AFTER_MANIFEST),
        pending_events=[owner_event()],
    )
    next_pdf = b"%PDF-next-successor"
    next_hash = hashlib.sha256(next_pdf).hexdigest()
    current["source_documents"]["terms_sha256"] = next_hash
    current["document_reviews"][DOCUMENT_ID]["observed_sha256"] = next_hash
    next_manifest = manifest(next_hash, AFTER_SHA, "2026-10-01T00:00:00Z")

    with pytest.raises(ValueError, match="pending document event"):
        apply_tft_document_review.apply_review(
            current,
            DOCUMENT_ID,
            AFTER_PDF,
            AFTER_MANIFEST,
            next_pdf,
            next_manifest,
            {**TRANSITION, "from_raw_sha256": AFTER_SHA, "to_raw_sha256": next_hash},
        )


def test_check_reproduces_cached_evidence_and_requires_durable_owner_event(
    tmp_path, monkeypatch
):
    data, updates, manifests, pdfs, transitions, after_manifest, transition, after_pdf = prepare_files(tmp_path)
    expected_event = owner_event()
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [copy.deepcopy(expected_event)],
    )
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_version",
        lambda _spec, _pdf, reviewed: copy.deepcopy(reviewed),
    )
    monkeypatch.setattr(
        apply_tft_document_review, "_recompute_manual_review", lambda _source: False
    )
    apply_tft_document_review.commit_review(
        DOCUMENT_ID, after_manifest, transition, data, updates, after_pdf, manifests, pdfs, transitions
    )

    apply_tft_document_review.check_review(
        DOCUMENT_ID, after_manifest, transition, data, updates, manifests, pdfs, transitions
    )
    write_json(updates, {"schema_version": 1, "updates": []})
    with pytest.raises(ValueError, match="missing from the durable update ledger"):
        apply_tft_document_review.check_review(
            DOCUMENT_ID, after_manifest, transition, data, updates, manifests, pdfs, transitions
        )


def test_apply_rejects_noncanonical_manifest_or_transition_path(tmp_path):
    data, updates, manifests, pdfs, transitions, after_manifest, transition, after_pdf = prepare_files(tmp_path)
    copied_manifest = tmp_path / "reviewed.json"
    copied_manifest.write_bytes(after_manifest.read_bytes())

    with pytest.raises(ValueError, match="canonical content-addressed path"):
        apply_tft_document_review.commit_review(
            DOCUMENT_ID,
            copied_manifest,
            transition,
            data,
            updates,
            after_pdf,
            manifests,
            pdfs,
            transitions,
        )


def test_check_rejects_stale_telegram_catalog(tmp_path, monkeypatch):
    data, updates, manifests, pdfs, transitions, after_manifest, transition, after_pdf = prepare_files(tmp_path)
    expected_event = owner_event()
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [copy.deepcopy(expected_event)],
    )
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_version",
        lambda _spec, _pdf, reviewed: copy.deepcopy(reviewed),
    )
    monkeypatch.setattr(
        apply_tft_document_review, "_recompute_manual_review", lambda _source: False
    )
    expected_catalog = {"schema_version": 4, "documents": ["reviewed"]}
    monkeypatch.setattr(
        apply_tft_document_review,
        "_catalog_projection",
        lambda *_args, **_kwargs: copy.deepcopy(expected_catalog),
    )
    catalog_path = tmp_path / "catalog.json"
    release_history = tmp_path / "release-history.json"
    write_json(release_history, {})
    apply_tft_document_review.commit_review(
        DOCUMENT_ID,
        after_manifest,
        transition,
        data,
        updates,
        after_pdf,
        manifests,
        pdfs,
        transitions,
    )
    write_json(catalog_path, {"schema_version": 4, "documents": []})

    with pytest.raises(ValueError, match="catalogue is stale"):
        apply_tft_document_review.check_review(
            DOCUMENT_ID,
            after_manifest,
            transition,
            data,
            updates,
            manifests,
            pdfs,
            transitions,
            catalog_path,
            release_history,
        )

    write_json(catalog_path, expected_catalog)
    apply_tft_document_review.check_review(
        DOCUMENT_ID,
        after_manifest,
        transition,
        data,
        updates,
        manifests,
        pdfs,
        transitions,
        catalog_path,
        release_history,
    )


def test_layout_only_transition_can_advance_without_owner_event(monkeypatch):
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        apply_tft_document_review, "_recompute_manual_review", lambda _source: False
    )
    updated, events = apply_tft_document_review.apply_review(
        source(), DOCUMENT_ID, BEFORE_PDF, BEFORE_MANIFEST, AFTER_PDF, AFTER_MANIFEST, TRANSITION
    )
    assert events == []
    assert updated["document_reviews"][DOCUMENT_ID]["approved_sha256"] == AFTER_SHA


@pytest.mark.parametrize("tamper", ["observed", "predecessor", "manifest"])
def test_apply_rejects_identity_tampering(monkeypatch, tamper):
    current = source()
    before_manifest = copy.deepcopy(BEFORE_MANIFEST)
    after_manifest = copy.deepcopy(AFTER_MANIFEST)
    if tamper == "observed":
        current["source_documents"]["terms_sha256"] = "0" * 64
    elif tamper == "predecessor":
        current["document_reviews"][DOCUMENT_ID]["approved_sha256"] = "0" * 64
    else:
        before_manifest["review_note"] = "tampered"
    monkeypatch.setattr(
        apply_tft_document_review,
        "verify_transition",
        lambda *_args, **_kwargs: [owner_event()],
    )
    with pytest.raises(ValueError):
        apply_tft_document_review.apply_review(
            current,
            DOCUMENT_ID,
            BEFORE_PDF,
            before_manifest,
            AFTER_PDF,
            after_manifest,
            TRANSITION,
        )
