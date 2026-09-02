from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone

import pytest

from reminders.app.owner_alerts import OwnerAlertEvent
from scripts import apply_tft_menu_review, fetch_tft_menus, tft_menu_reviews
from scripts import source_change_alert


PDF = b"%PDF reviewed candidate"
NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


def fixture(decision="approved"):
    previous = {
        "status": "published",
        "url": "https://www.americanexpress.com/old.pdf",
        "filename": "Place-Menu_Platinum.pdf",
        "card": "platinum",
        "label": "Platinum",
        "checked_at": "2026-08-29T00:00:00Z",
        "first_seen_at": "2026-08-01T00:00:00Z",
        "last_seen_at": "2026-08-29T00:00:00Z",
        "sha256": "a" * 64,
        "bytes": 100,
        "aem_created": "before",
        "changed_at": None,
    }
    item = {
        "status": "review_required",
        "kind": "changed_or_new_venue_menu",
        "venue_id": "tft-place",
        "venue_name": "Place",
        "card": "platinum",
        "filename": "Place-Menu-Platinum.pdf",
        "url": "https://www.americanexpress.com/content/dam/Place-Menu-Platinum.pdf",
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "bytes": len(PDF),
        "aem_uuid": "candidate-uuid",
        "previous_sha256": previous["sha256"],
        "previous": previous,
        "roster_sha256": "b" * 64,
        "listing_sha256": "c" * 64,
        "detected_at": "2026-08-30T05:00:00Z",
    }
    item["candidate_id"] = tft_menu_reviews.review_item_sha256(item)
    queue = [item]
    payload = {
        "program": "Table for Two",
        "official_url": "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/",
        "venues": [
            {
                "id": "tft-place",
                "name": "Place",
                "menu_pdfs": {"platinum": previous},
                "menu_pdf": previous,
            }
        ],
        "menu_source": {
            "venues_review": 0,
            "review_queue": queue,
            "review_queue_count": 1,
            "review_queue_sha256": tft_menu_reviews.review_queue_sha256(queue),
            "review_required": True,
        },
    }
    manifest = {
        "schema_version": 1,
        "program_id": "table-for-two",
        "review_queue_sha256": payload["menu_source"]["review_queue_sha256"],
        "candidate_id": item["candidate_id"],
        "decision": decision,
        "kind": item["kind"],
        "venue_id": item["venue_id"],
        "card": item["card"],
        "filename": item["filename"],
        "source_url": item["url"],
        "asset_sha256": item["sha256"],
        "bytes": item["bytes"],
        "aem_uuid": item["aem_uuid"],
        "roster_sha256": item["roster_sha256"],
        "listing_sha256": item["listing_sha256"],
        "reviewed_at": "2026-08-30T06:00:00Z",
        "reviewed_by": "owner",
        "review_note": "Reviewed exact official candidate PDF.",
    }
    return payload, manifest, item, previous


def test_approval_replaces_active_and_builds_truthful_event():
    payload, manifest, item, previous = fixture()

    updated, event = tft_menu_reviews.apply_review(
        payload, manifest, PDF, now=NOW
    )

    assert payload["venues"][0]["menu_pdf"] == previous
    active = updated["venues"][0]["menu_pdfs"]["platinum"]
    assert active["status"] == "published"
    assert active["filename"] == item["filename"]
    assert active["sha256"] == item["sha256"]
    assert active["review_manifest_sha256"] == tft_menu_reviews.manifest_sha256(manifest)
    assert updated["menu_source"]["review_queue_count"] == 0
    assert updated["menu_source"]["review_required"] is False
    assert event["kind"] == "menu_updated"
    assert event["route"] == "#/table-for-two?venue=tft-place"
    assert event["changes"] == [
        {"field": "Menu file", "before": previous["filename"], "after": item["filename"]},
        {"field": "Menu version", "before": previous["sha256"][:12], "after": item["sha256"][:12]},
    ]
    entity_key = event.pop("entity_key")
    source_change_alert.assign_event_identity(event, entity_key)
    OwnerAlertEvent.model_validate(event)
    tft_menu_reviews.verify_decision_receipts(updated)


def test_prepared_manifest_copies_only_bound_candidate_fields():
    payload, expected, item, _previous = fixture()

    prepared = tft_menu_reviews.prepare_manifest(
        payload,
        item["candidate_id"],
        "approved",
        expected["reviewed_at"],
        expected["reviewed_by"],
        expected["review_note"],
    )

    assert prepared == expected
    tft_menu_reviews.verify_review(payload, prepared, PDF, now=NOW)


def test_rejection_preserves_active_and_creates_no_event():
    payload, manifest, _item, previous = fixture("rejected")

    updated, event = tft_menu_reviews.apply_review(
        payload, manifest, None, now=NOW
    )

    assert updated["venues"][0]["menu_pdf"] == previous
    assert updated["menu_source"]["review_queue"] == []
    assert updated["menu_source"]["review_decisions"][0]["decision"] == "rejected"
    assert event is None


def test_exact_reapply_is_noop_and_conflict_fails():
    payload, manifest, _item, _previous = fixture("rejected")
    applied, _event = tft_menu_reviews.apply_review(payload, manifest, now=NOW)

    repeated, event = tft_menu_reviews.apply_review(applied, manifest, now=NOW)
    assert repeated == applied
    assert event is None
    conflicting = copy.deepcopy(manifest)
    conflicting["review_note"] = "Different terminal instruction."
    with pytest.raises(ValueError, match="different terminal decision"):
        tft_menu_reviews.apply_review(applied, conflicting, now=NOW)


def test_exact_reapply_repairs_missing_active_review_receipt_metadata():
    payload, manifest, _item, _previous = fixture("approved")
    applied, _event = tft_menu_reviews.apply_review(payload, manifest, PDF, now=NOW)
    active = applied["venues"][0]["menu_pdfs"]["platinum"]
    active.pop("review_manifest_sha256")
    active.pop("reviewed_at")
    applied["venues"][0]["menu_pdf"] = copy.deepcopy(active)

    repaired, event = tft_menu_reviews.apply_review(applied, manifest, now=NOW)

    expected_digest = tft_menu_reviews.manifest_sha256(manifest)
    assert repaired["venues"][0]["menu_pdf"]["review_manifest_sha256"] == expected_digest
    assert repaired["venues"][0]["menu_pdfs"]["platinum"]["reviewed_at"] == manifest["reviewed_at"]
    assert event is None


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda manifest: manifest.update(review_queue_sha256="d" * 64), "queue changed"),
        (lambda manifest: manifest.update(source_url="https://example.com/menu.pdf"), "provenance"),
        (lambda manifest: manifest.update(reviewed_at="2026-08-30T04:00:00Z"), "chronology"),
    ],
)
def test_manifest_drift_fails_closed(mutation, error):
    payload, manifest, _item, _previous = fixture()
    mutation(manifest)

    with pytest.raises(ValueError, match=error):
        tft_menu_reviews.apply_review(payload, manifest, PDF, now=NOW)


def test_approval_requires_exact_pdf():
    payload, manifest, _item, _previous = fixture()

    with pytest.raises(ValueError, match="does not match"):
        tft_menu_reviews.apply_review(payload, manifest, b"%PDF wrong", now=NOW)


def test_missing_menu_is_not_a_decidable_candidate():
    payload, manifest, item, _previous = fixture("rejected")
    item["kind"] = "missing_venue_menu"
    item["candidate_id"] = tft_menu_reviews.review_item_sha256(item)
    payload["menu_source"]["review_queue_sha256"] = tft_menu_reviews.review_queue_sha256([item])
    manifest.update(
        kind=item["kind"],
        candidate_id=item["candidate_id"],
        review_queue_sha256=payload["menu_source"]["review_queue_sha256"],
    )

    with pytest.raises(ValueError, match="concrete menu candidates"):
        tft_menu_reviews.apply_review(payload, manifest, now=NOW)


def test_refresh_decision_helpers_are_card_and_snapshot_bound():
    payload, manifest, item, previous = fixture("rejected")
    rejected, _event = tft_menu_reviews.apply_review(payload, manifest, now=NOW)
    decisions = rejected["menu_source"]["review_decisions"]

    assert fetch_tft_menus.matching_terminal_decision(item, decisions)["decision"] == "rejected"

    payload2, manifest2, item2, _previous2 = fixture("approved")
    approved, _event = tft_menu_reviews.apply_review(payload2, manifest2, PDF, now=NOW)
    approved_decisions = approved["menu_source"]["review_decisions"]
    assert fetch_tft_menus.approved_candidate_filename(
        approved_decisions,
        "tft-place",
        "platinum",
        [item2["filename"], previous["filename"]],
        item2["roster_sha256"],
        item2["listing_sha256"],
    ) == item2["filename"]
    old_asset = {
        "card": "platinum",
        "filename": previous["filename"],
        "sha256": previous["sha256"],
        "roster_sha256": item2["roster_sha256"],
        "listing_sha256": item2["listing_sha256"],
    }
    assert fetch_tft_menus.superseding_decision(
        approved_decisions, old_asset, "tft-place"
    ) is not None


def test_receipt_verifier_rejects_unbound_reviewed_menu():
    payload, _manifest, _item, _previous = fixture()
    payload["venues"][0]["menu_pdfs"]["platinum"]["review_manifest_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="lacks an approved"):
        tft_menu_reviews.verify_decision_receipts(payload)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda event: event.update(subject="Forged subject"),
        lambda event: event.update(route="#/table-for-two?venue=other"),
        lambda event: event["before"]["fields"].update(**{"Menu file": "FORGED.pdf"}),
        lambda event: event["after"]["fields"].update(**{"Menu file": "FORGED.pdf"}),
        lambda event: event["changes"][0].update(before="FORGED.pdf"),
        lambda event: event.update(entity_key="record:other:menu:platinum"),
    ],
)
def test_receipt_verifier_rejects_tampered_owner_event(tamper):
    payload, manifest, _item, _previous = fixture()
    updated, _event = tft_menu_reviews.apply_review(payload, manifest, PDF, now=NOW)
    tamper(updated["menu_source"]["review_decisions"][0]["owner_event"])

    with pytest.raises(ValueError, match="invalid owner event"):
        tft_menu_reviews.verify_decision_receipts(updated)


def test_receipt_verifier_rejects_forged_terminal_receipt():
    payload, manifest, _item, _previous = fixture("rejected")
    updated, _event = tft_menu_reviews.apply_review(payload, manifest, now=NOW)
    updated["menu_source"]["review_decisions"][0]["manifest"]["review_note"] = "forged"

    with pytest.raises(ValueError, match="invalid TFT menu decision receipt"):
        tft_menu_reviews.verify_decision_receipts(updated)


def test_receipt_verifier_rejects_self_consistent_invalid_manifest():
    payload, manifest, _item, _previous = fixture("rejected")
    updated, _event = tft_menu_reviews.apply_review(payload, manifest, now=NOW)
    receipt = updated["menu_source"]["review_decisions"][0]
    receipt["manifest"]["schema_version"] = 999
    receipt["manifest"]["program_id"] = "evil"
    receipt["manifest_sha256"] = tft_menu_reviews.manifest_sha256(
        receipt["manifest"]
    )

    with pytest.raises(ValueError, match="invalid TFT menu decision receipt"):
        tft_menu_reviews.verify_decision_receipts(updated)


def test_only_latest_active_approval_requires_event_recovery():
    payload, manifest, _item, _previous = fixture()
    first, _event = tft_menu_reviews.apply_review(payload, manifest, PDF, now=NOW)
    first_receipt = first["menu_source"]["review_decisions"][0]
    current = first["venues"][0]["menu_pdfs"]["platinum"]
    second_pdf = b"%PDF latest candidate"
    second_item = {
        "status": "review_required",
        "kind": "changed_or_new_venue_menu",
        "venue_id": "tft-place",
        "venue_name": "Place",
        "card": "platinum",
        "filename": "Place-Menu-v3.pdf",
        "url": "https://www.americanexpress.com/content/dam/Place-Menu-v3.pdf",
        "sha256": hashlib.sha256(second_pdf).hexdigest(),
        "bytes": len(second_pdf),
        "aem_uuid": "candidate-v3",
        "previous": copy.deepcopy(current),
        "roster_sha256": "b" * 64,
        "listing_sha256": "e" * 64,
        "detected_at": "2026-08-30T07:00:00Z",
    }
    second_item["candidate_id"] = tft_menu_reviews.review_item_sha256(second_item)
    first["menu_source"].update(
        review_queue=[second_item],
        review_queue_count=1,
        review_queue_sha256=tft_menu_reviews.review_queue_sha256([second_item]),
        review_required=True,
    )
    second_manifest = tft_menu_reviews.prepare_manifest(
        first,
        second_item["candidate_id"],
        "approved",
        "2026-08-30T08:00:00Z",
        "owner",
        "Reviewed latest exact official candidate PDF.",
    )
    second, _event = tft_menu_reviews.apply_review(
        first, second_manifest, second_pdf, now=NOW
    )

    assert apply_tft_menu_review._expected_event(second, first_receipt) is None
    assert apply_tft_menu_review._expected_event(
        second, second["menu_source"]["review_decisions"][1]
    ) is not None


def test_sequential_approvals_keep_history_and_verify_latest_active():
    payload, manifest, _item, _previous = fixture()
    first, _event = tft_menu_reviews.apply_review(payload, manifest, PDF, now=NOW)
    current = first["venues"][0]["menu_pdfs"]["platinum"]
    second_pdf = b"%PDF second reviewed candidate"
    second_item = {
        "status": "review_required",
        "kind": "changed_or_new_venue_menu",
        "venue_id": "tft-place",
        "venue_name": "Place",
        "card": "platinum",
        "filename": "Place-Menu-Platinum-v2.pdf",
        "url": "https://www.americanexpress.com/content/dam/Place-Menu-Platinum-v2.pdf",
        "sha256": hashlib.sha256(second_pdf).hexdigest(),
        "bytes": len(second_pdf),
        "aem_uuid": "candidate-uuid-v2",
        "previous_sha256": current["sha256"],
        "previous": copy.deepcopy(current),
        "roster_sha256": "b" * 64,
        "listing_sha256": "d" * 64,
        "detected_at": "2026-08-30T07:00:00Z",
    }
    second_item["candidate_id"] = tft_menu_reviews.review_item_sha256(second_item)
    first["menu_source"].update(
        review_queue=[second_item],
        review_queue_count=1,
        review_queue_sha256=tft_menu_reviews.review_queue_sha256([second_item]),
        review_required=True,
    )
    second_manifest = tft_menu_reviews.prepare_manifest(
        first,
        second_item["candidate_id"],
        "approved",
        "2026-08-30T08:00:00Z",
        "owner",
        "Reviewed second exact official candidate PDF.",
    )

    second, _event = tft_menu_reviews.apply_review(
        first, second_manifest, second_pdf, now=NOW
    )

    assert len(second["menu_source"]["review_decisions"]) == 2
    assert second["venues"][0]["menu_pdfs"]["platinum"]["sha256"] == second_item["sha256"]
    tft_menu_reviews.verify_decision_receipts(second)


def test_cli_applies_approval_and_deduplicates_event(tmp_path, monkeypatch):
    payload, manifest, item, _previous = fixture()
    data_path = tmp_path / "table-for-two.json"
    manifest_path = tmp_path / "review.json"
    pdf_path = tmp_path / "candidate.pdf"
    updates_path = tmp_path / "updates.json"
    catalog_path = tmp_path / "catalog.json"
    data_path.write_text(json.dumps(payload))
    manifest_path.write_text(json.dumps(manifest))
    pdf_path.write_bytes(PDF)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_tft_menu_review.py",
            "--manifest",
            str(manifest_path),
            "--pdf",
            str(pdf_path),
            "--data",
            str(data_path),
            "--updates",
            str(updates_path),
            "--catalog",
            str(catalog_path),
        ],
    )

    assert apply_tft_menu_review.main() == 0
    first_ledger = json.loads(updates_path.read_text())
    assert len(first_ledger["updates"]) == 1
    assert first_ledger["updates"][0]["status"] == "published"
    assert json.loads(data_path.read_text())["venues"][0]["menu_pdf"]["sha256"] == item["sha256"]
    assert apply_tft_menu_review.main() == 0
    assert json.loads(updates_path.read_text()) == first_ledger


def test_cli_check_detects_missing_event_and_replay_repairs_derivatives(
    tmp_path, monkeypatch
):
    payload, manifest, _item, _previous = fixture()
    data_path = tmp_path / "table-for-two.json"
    manifest_path = tmp_path / "review.json"
    pdf_path = tmp_path / "candidate.pdf"
    updates_path = tmp_path / "updates.json"
    catalog_path = tmp_path / "catalog.json"
    data_path.write_text(json.dumps(payload))
    manifest_path.write_text(json.dumps(manifest))
    pdf_path.write_bytes(PDF)
    base_argv = [
        "apply_tft_menu_review.py",
        "--manifest",
        str(manifest_path),
        "--pdf",
        str(pdf_path),
        "--data",
        str(data_path),
        "--updates",
        str(updates_path),
        "--catalog",
        str(catalog_path),
    ]
    monkeypatch.setattr(sys, "argv", base_argv)
    assert apply_tft_menu_review.main() == 0
    ledger = json.loads(updates_path.read_text())
    ledger["updates"] = []
    updates_path.write_text(json.dumps(ledger))
    catalog_path.write_text("{}")

    monkeypatch.setattr(sys, "argv", [*base_argv, "--check"])
    with pytest.raises(SystemExit, match="not been fully applied"):
        apply_tft_menu_review.main()

    monkeypatch.setattr(sys, "argv", base_argv)
    assert apply_tft_menu_review.main() == 0
    repaired = json.loads(updates_path.read_text())
    assert len(repaired["updates"]) == 1
    assert repaired["updates"][0]["status"] == "published"
    assert json.loads(catalog_path.read_text())["schema_version"]


@pytest.mark.parametrize(
    "tamper",
    [
        lambda event: event.update(subject="Tampered subject"),
        lambda event: event["changes"][0].update(after="Tampered menu"),
        lambda event: event.update(id="0" * 20),
    ],
)
def test_cli_check_rejects_tampered_approval_event(tmp_path, monkeypatch, tamper):
    payload, manifest, _item, _previous = fixture()
    data_path = tmp_path / "table-for-two.json"
    manifest_path = tmp_path / "review.json"
    pdf_path = tmp_path / "candidate.pdf"
    updates_path = tmp_path / "updates.json"
    catalog_path = tmp_path / "catalog.json"
    data_path.write_text(json.dumps(payload))
    manifest_path.write_text(json.dumps(manifest))
    pdf_path.write_bytes(PDF)
    base_argv = [
        "apply_tft_menu_review.py", "--manifest", str(manifest_path),
        "--pdf", str(pdf_path), "--data", str(data_path),
        "--updates", str(updates_path), "--catalog", str(catalog_path),
    ]
    monkeypatch.setattr(sys, "argv", base_argv)
    assert apply_tft_menu_review.main() == 0
    ledger = json.loads(updates_path.read_text())
    tamper(ledger["updates"][0])
    updates_path.write_text(json.dumps(ledger))

    monkeypatch.setattr(sys, "argv", [*base_argv, "--check"])
    with pytest.raises(SystemExit, match="not been fully applied"):
        apply_tft_menu_review.main()


def test_queue_resolution_does_not_reject_mixed_source_review(tmp_path):
    event = {
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": "#/table-for-two",
        "kind": "source_updated",
        "subject": "Table for Two source",
        "detected_at": "2026-08-30T05:00:00Z",
        "status": "review_required",
        "before": {"state": "available", "fields": {}},
        "after": {"state": "available", "fields": {}},
        "changes": [
            {"field": "Menu review flag", "before": True, "after": False},
            {"field": "Official roster SHA-256", "before": "a", "after": "b"},
        ],
        "source_url": "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/",
    }
    source_change_alert.assign_event_identity(event, "meta")
    path = tmp_path / "updates.json"
    source_change_alert._atomic_write_json(
        path,
        {
            "schema_version": 1,
            "updates": [event],
            "identity_state": source_change_alert.rebuild_identity_state([event]),
        },
    )

    apply_tft_menu_review._resolve_queue_events(path, "2026-08-30T06:00:00Z")

    assert json.loads(path.read_text())["updates"][0]["status"] == "review_required"


def test_cli_recovers_after_data_first_event_failure(tmp_path, monkeypatch):
    payload, manifest, item, _previous = fixture()
    data_path = tmp_path / "table-for-two.json"
    manifest_path = tmp_path / "review.json"
    pdf_path = tmp_path / "candidate.pdf"
    updates_path = tmp_path / "updates.json"
    catalog_path = tmp_path / "catalog.json"
    data_path.write_text(json.dumps(payload))
    manifest_path.write_text(json.dumps(manifest))
    pdf_path.write_bytes(PDF)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_tft_menu_review.py",
            "--manifest",
            str(manifest_path),
            "--pdf",
            str(pdf_path),
            "--data",
            str(data_path),
            "--updates",
            str(updates_path),
            "--catalog",
            str(catalog_path),
        ],
    )
    real_append = source_change_alert.append_updates
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated ledger failure")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(source_change_alert, "append_updates", fail_once)
    with pytest.raises(RuntimeError, match="simulated ledger failure"):
        apply_tft_menu_review.main()
    persisted = json.loads(data_path.read_text())
    assert persisted["venues"][0]["menu_pdf"]["sha256"] == item["sha256"]
    assert persisted["menu_source"]["review_decisions"]

    assert apply_tft_menu_review.main() == 0
    assert json.loads(updates_path.read_text())["updates"][0]["status"] == "published"
    assert catalog_path.exists()
