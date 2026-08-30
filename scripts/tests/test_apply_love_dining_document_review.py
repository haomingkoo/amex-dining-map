from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import apply_love_dining_document_review as apply_review


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/reviews/official-documents/love-dining-restaurant-terms/c277102a13880883bbe046cf06da51172ff2ba357deec435d6c5e266638c1426.json"
HOTEL_MANIFEST = ROOT / "data/reviews/official-documents/love-dining-hotel-terms/806756636efb4a11906d9110f18e74857f9efe9918c8f2d125253c50e5a53ef4.json"


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_restaurant_baseline_does_not_approve_pending_hotel_document():
    meta = _load("data/love-dining-source.json")
    meta["reviewed_terms_hashes"]["restaurants"] = json.loads(
        MANIFEST.read_text()
    )["lineage"]["previous_observed_sha256"]
    meta["reviewed_terms_hashes"]["hotels"] = "f" * 64
    ledger = _load("data/updates.json")
    manifest = json.loads(MANIFEST.read_text())

    updated_meta, updated_ledger = apply_review.apply_baseline(
        meta, ledger, "restaurants", manifest
    )

    assert updated_meta["reviewed_terms_hashes"]["restaurants"] == manifest["raw_sha256"]
    assert updated_meta["reviewed_terms_hashes"]["hotels"] != updated_meta["terms_hashes"]["hotels"]
    assert updated_meta["major_change_reasons"] == ["Love Dining T&C PDF changed: hotels"]
    assert updated_meta["manual_review_required"] is True
    assert updated_ledger == ledger


def test_baseline_apply_is_idempotent():
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")
    manifest = json.loads(MANIFEST.read_text())

    once_meta, once_ledger = apply_review.apply_baseline(
        meta, ledger, "restaurants", manifest
    )
    twice_meta, twice_ledger = apply_review.apply_baseline(
        once_meta, once_ledger, "restaurants", manifest
    )

    assert twice_meta == once_meta
    assert twice_ledger == once_ledger


def test_reapply_rejects_different_review_identity_without_mutation():
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")
    manifest = json.loads(MANIFEST.read_text())
    manifest["reviewed_at"] = "2026-08-30T07:00:00Z"
    manifest["lineage"]["previous_observed_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="identity"):
        apply_review.apply_baseline(meta, ledger, "restaurants", manifest)


def test_wrong_document_cannot_approve_restaurant_hash():
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")
    manifest = json.loads(MANIFEST.read_text())
    manifest["document_id"] = "love-dining-hotel-terms"

    with pytest.raises(ValueError, match="does not match"):
        apply_review.apply_baseline(meta, ledger, "restaurants", manifest)


def test_first_apply_requires_lineage_to_match_reviewed_metadata():
    meta = _load("data/love-dining-source.json")
    meta["reviewed_terms_hashes"]["restaurants"] = "f" * 64
    ledger = _load("data/updates.json")
    manifest = json.loads(MANIFEST.read_text())
    manifest["lineage"]["previous_observed_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="lineage"):
        apply_review.apply_baseline(meta, ledger, "restaurants", manifest)


def test_second_baseline_clears_review_queue_and_rejects_hash_only_event():
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")
    hotel = json.loads(HOTEL_MANIFEST.read_text())

    updated_meta, updated_ledger = apply_review.apply_baseline(
        meta, ledger, "hotels", hotel
    )

    assert updated_meta["manual_review_required"] is False
    assert updated_meta["major_change_reasons"] == []
    assert updated_meta["reviewed_terms_hashes"] == updated_meta["terms_hashes"]
    source_events = [
        event
        for event in updated_ledger["updates"]
        if event.get("id") == "828a9ae7f3965510cfd3"
    ]
    assert len(source_events) == 1
    assert source_events[0]["status"] == "rejected"
    assert "no retroactive clause-level change" in source_events[0]["review_note"]
