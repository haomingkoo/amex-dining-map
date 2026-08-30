from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import apply_tft_roster_review, source_change_alert, tft_roster_reviews


ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "data/table-for-two.json").read_text(encoding="utf-8"))
IMAGE_SHA = DATA["source_images"]["participating_merchants_sha256"]
MANIFEST_PATH = ROOT / "data/reviews/table-for-two-roster" / f"{IMAGE_SHA}.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def ledger() -> dict:
    return {"schema_version": 1, "updates": [], "identity_state": {"streams": {}}}


def test_baseline_manifest_is_content_addressed_complete_and_chronological():
    tft_roster_reviews.validate_manifest(MANIFEST, MANIFEST_PATH)

    assert MANIFEST["manifest_sha256"] == tft_roster_reviews.manifest_sha256(MANIFEST)
    assert MANIFEST_PATH.stem == MANIFEST["source"]["participating_image_sha256"]
    assert len(MANIFEST["venues"]) == 23
    assert {venue["id"] for venue in MANIFEST["venues"]} == {
        venue["id"] for venue in DATA["venues"]
    }
    assert all(
        not (tft_roster_reviews.RUNTIME_FIELDS & venue.keys())
        for venue in MANIFEST["venues"]
    )


def test_unknown_image_retains_approved_roster_and_creates_source_review_item():
    existing = copy.deepcopy(DATA)
    existing["roster_source"] = {
        "approved_participating_sha256": IMAGE_SHA,
        "approved_manifest_sha256": MANIFEST["manifest_sha256"],
        "reviewed_at": MANIFEST["review"]["reviewed_at"],
    }
    roster, state = tft_roster_reviews.review_state(
        "f" * 64,
        "https://www.americanexpress.com/content/dam/new-roster.png",
        "2026-08-31T01:00:00Z",
        existing,
    )

    assert roster == [tft_roster_reviews.stable_venue(v) for v in DATA["venues"]]
    assert state["status"] == "review_required"
    assert state["approved_participating_sha256"] == IMAGE_SHA
    assert state["observed_participating_sha256"] == "f" * 64
    assert state["review_item"] == {
        "source_id": "table-for-two-roster",
        "kind": "unknown_participating_image",
        "detected_at": "2026-08-31T01:00:00Z",
        "official_url": tft_roster_reviews.OFFICIAL_URL,
        "participating_image_url": "https://www.americanexpress.com/content/dam/new-roster.png",
        "observed_participating_sha256": "f" * 64,
        "approved_participating_sha256": IMAGE_SHA,
    }


def test_unknown_image_without_prior_roster_fails_closed():
    with pytest.raises(RuntimeError, match="no previously approved"):
        tft_roster_reviews.review_state(
            "f" * 64,
            "https://www.americanexpress.com/content/dam/new-roster.png",
            "2026-08-31T01:00:00Z",
            {},
        )


def changed_manifest() -> dict:
    manifest = copy.deepcopy(MANIFEST)
    manifest["source"]["participating_image_sha256"] = "e" * 64
    manifest["source"]["participating_image_url"] = (
        "https://www.americanexpress.com/content/dam/reviewed-next.png"
    )
    manifest["source"]["captured_at"] = "2026-08-31T01:00:00Z"
    manifest["predecessor"] = {
        "manifest_sha256": MANIFEST["manifest_sha256"],
        "participating_image_sha256": IMAGE_SHA,
    }
    manifest["review"].update(
        reviewed_at="2026-08-31T02:00:00Z",
        venue_count=23,
        note="Reviewed one addition and one removal against the full source image.",
    )
    removed = manifest["venues"].pop(0)
    added = copy.deepcopy(removed)
    added.update(
        id="tft-reviewed-new-place",
        name="Reviewed New Place",
        address="1 Reviewed Road, Singapore 000001",
        dining_city_id="reviewed-new-place",
    )
    manifest["venues"].append(added)
    manifest["manifest_sha256"] = tft_roster_reviews.manifest_sha256(manifest)
    return manifest


def reviewed_data() -> dict:
    data = copy.deepcopy(DATA)
    data["source_images"]["participating_merchants_sha256"] = "e" * 64
    data["participating_merchants_image_url"] = (
        "https://www.americanexpress.com/content/dam/reviewed-next.png"
    )
    data["manual_review_required"] = True
    data["roster_source"] = {
        "status": "review_required",
        "review_required": True,
        "observed_participating_sha256": "e" * 64,
        "approved_participating_sha256": IMAGE_SHA,
        "approved_manifest_sha256": MANIFEST["manifest_sha256"],
        "reviewed_at": MANIFEST["review"]["reviewed_at"],
        "review_item": {"source_id": "table-for-two-roster"},
    }
    return data


def test_apply_publishes_reviewed_add_remove_and_preserves_other_source_state():
    manifest = changed_manifest()
    data = reviewed_data()
    retained = data["venues"][1]
    original_menu = copy.deepcopy(retained["menu_pdf"])
    original_availability = copy.deepcopy(retained["availability"])
    original_documents = copy.deepcopy(data["source_documents"])
    original_menu_source = copy.deepcopy(data["menu_source"])

    updated, events = tft_roster_reviews.apply_manifest(manifest, data)

    assert {event["kind"] for event in events} == {"added", "removed"}
    assert all(event["status"] == "published" for event in events)
    assert all(event["reviewed_at"] == "2026-08-31T02:00:00Z" for event in events)
    removed = next(event for event in events if event["kind"] == "removed")
    added = next(event for event in events if event["kind"] == "added")
    assert removed["before"]["state"] == "listed" and removed["after"]["state"] == "not_listed"
    assert added["before"]["state"] == "not_listed" and added["after"]["state"] == "listed"
    retained_after = next(v for v in updated["venues"] if v["id"] == retained["id"])
    assert retained_after["menu_pdf"] == original_menu
    assert retained_after["availability"] == original_availability
    assert updated["source_documents"] == original_documents
    assert updated["menu_source"] == original_menu_source
    assert updated["roster_source"]["status"] == "approved"
    assert updated["roster_source"]["pending_events"] == events
    assert updated["manual_review_required"] is False

    reapplied, reapplied_events = tft_roster_reviews.apply_manifest(manifest, updated)
    assert reapplied == updated
    assert reapplied_events == events


def test_apply_rejects_wrong_predecessor_before_mutating_inputs():
    manifest = changed_manifest()
    manifest["predecessor"]["manifest_sha256"] = "0" * 64
    manifest["manifest_sha256"] = tft_roster_reviews.manifest_sha256(manifest)
    data = reviewed_data()
    original = copy.deepcopy(data)

    with pytest.raises(ValueError, match="predecessor"):
        tft_roster_reviews.apply_manifest(manifest, data)
    assert data == original


def test_manifest_rejects_runtime_fields_and_tampering():
    manifest = copy.deepcopy(MANIFEST)
    manifest["venues"][0]["availability"] = {"status": "unknown"}
    manifest["manifest_sha256"] = tft_roster_reviews.manifest_sha256(manifest)
    with pytest.raises(ValueError, match="runtime"):
        tft_roster_reviews.validate_manifest(manifest)

    manifest = copy.deepcopy(MANIFEST)
    manifest["venues"][0]["name"] = "Tampered"
    with pytest.raises(ValueError, match="manifest_sha256"):
        tft_roster_reviews.validate_manifest(manifest)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def manifest_version(
    venues: list[dict], image_sha: str, image_name: str, predecessor: dict, reviewed_at: str
) -> dict:
    manifest = copy.deepcopy(MANIFEST)
    manifest["source"].update(
        participating_image_sha256=image_sha,
        participating_image_url=f"https://www.americanexpress.com/content/dam/{image_name}.png",
        captured_at=reviewed_at,
    )
    manifest["predecessor"] = {
        "manifest_sha256": predecessor["manifest_sha256"],
        "participating_image_sha256": predecessor["source"]["participating_image_sha256"],
    }
    manifest["review"].update(
        reviewed_at=reviewed_at,
        venue_count=len(venues),
        note="Reviewed the complete source image for roster transition testing.",
    )
    manifest["venues"] = copy.deepcopy(venues)
    manifest["manifest_sha256"] = tft_roster_reviews.manifest_sha256(manifest)
    return manifest


def prepare_observation(data: dict, manifest: dict) -> dict:
    observed = copy.deepcopy(data)
    observed["source_images"]["participating_merchants_sha256"] = manifest["source"][
        "participating_image_sha256"
    ]
    observed["participating_merchants_image_url"] = manifest["source"][
        "participating_image_url"
    ]
    observed["manual_review_required"] = True
    return observed


def test_commit_recovers_after_ledger_failure_without_losing_event(tmp_path, monkeypatch):
    manifest = changed_manifest()
    data_path = tmp_path / "table-for-two.json"
    updates_path = tmp_path / "updates.json"
    write_json(data_path, reviewed_data())
    write_json(updates_path, ledger())
    real_append = source_change_alert.append_updates

    def crash(*_args, **_kwargs):
        raise RuntimeError("simulated ledger crash")

    monkeypatch.setattr(source_change_alert, "append_updates", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        apply_tft_roster_review.commit_review(manifest, data_path, updates_path)
    interrupted = json.loads(data_path.read_text())
    assert len(interrupted["roster_source"]["pending_events"]) == 2
    assert json.loads(updates_path.read_text())["updates"] == []

    monkeypatch.setattr(source_change_alert, "append_updates", real_append)
    apply_tft_roster_review.commit_review(manifest, data_path, updates_path)
    committed = json.loads(data_path.read_text())
    committed_ledger = json.loads(updates_path.read_text())
    assert "pending_events" not in committed["roster_source"]
    assert len(committed_ledger["updates"]) == 2


def test_inverse_and_repeated_roster_transition_increments_occurrence(tmp_path):
    data_path = tmp_path / "table-for-two.json"
    updates_path = tmp_path / "updates.json"
    initial = copy.deepcopy(DATA)
    initial["roster_source"] = {
        "status": "approved",
        "review_required": False,
        "observed_participating_sha256": IMAGE_SHA,
        "approved_participating_sha256": IMAGE_SHA,
        "approved_manifest_sha256": MANIFEST["manifest_sha256"],
        "reviewed_at": MANIFEST["review"]["reviewed_at"],
        "review_item": None,
    }
    write_json(data_path, initial)
    write_json(updates_path, ledger())

    b1 = changed_manifest()
    data = prepare_observation(initial, b1)
    write_json(data_path, data)
    apply_tft_roster_review.commit_review(b1, data_path, updates_path)

    a2 = manifest_version(
        MANIFEST["venues"], "d" * 64, "roster-a2", b1, "2026-09-01T01:00:00Z"
    )
    data = prepare_observation(json.loads(data_path.read_text()), a2)
    write_json(data_path, data)
    apply_tft_roster_review.commit_review(a2, data_path, updates_path)

    b2 = manifest_version(
        b1["venues"], "c" * 64, "roster-b2", a2, "2026-09-02T01:00:00Z"
    )
    data = prepare_observation(json.loads(data_path.read_text()), b2)
    write_json(data_path, data)
    apply_tft_roster_review.commit_review(b2, data_path, updates_path)

    events = json.loads(updates_path.read_text())["updates"]
    repeated = [
        event
        for event in events
        if event["kind"] == "added" and event["subject"].startswith("Reviewed New Place")
    ]
    assert sorted(event["occurrence"] for event in repeated) == [1, 2]
    assert len({event["transition_id"] for event in repeated}) == 1
    assert len({event["id"] for event in repeated}) == 2


def test_generic_meta_alert_surfaces_roster_review_item():
    old = {"roster_source": {"status": "approved", "observed_participating_sha256": IMAGE_SHA}}
    new = {
        "official_url": tft_roster_reviews.OFFICIAL_URL,
        "roster_source": {
            "status": "review_required",
            "review_required": True,
            "observed_participating_sha256": "f" * 64,
            "approved_participating_sha256": IMAGE_SHA,
            "review_item": {"kind": "unknown_participating_image"},
        },
    }
    event = source_change_alert.build_meta_update_event(
        "Table for Two", old, new, "2026-09-01T00:00:00Z"
    )
    fields = {change["field"] for change in event["changes"]}
    assert {"Roster review status", "Observed roster image hash", "Roster review item"} <= fields
    assert event["status"] == "review_required"
