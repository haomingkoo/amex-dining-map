from __future__ import annotations

import copy
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apply_love_dining_review.py"
SPEC = importlib.util.spec_from_file_location("apply_love_dining_review", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_review_publishes_corrections_retracts_bad_events_and_keeps_terms_pending():
    manifest = _load(
        "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json"
    )
    records = _load("data/love-dining.json")
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")

    reviewed_meta, reviewed_ledger = MODULE.apply_review(
        manifest, records, meta, ledger
    )
    events = {event["id"]: event for event in reviewed_ledger["updates"]}

    for mapping in manifest["mappings"]:
        correction = events[mapping["correction_event_id"]]
        assert correction["kind"] == "correction"
        assert correction["status"] == "published"
        assert correction["changes"] == [
            {
                "field": "Hotel",
                "before": mapping["before_hotel"],
                "after": mapping["after_hotel"],
            }
        ]
        if original_id := mapping.get("retracts_event_id"):
            assert events[original_id]["status"] == "retracted"
            assert events[original_id]["corrected_by"] == correction["id"]
            assert correction["corrects"] == [original_id]
    assert events[manifest["source_event_id"]]["status"] == "rejected"
    assert reviewed_meta["reviewed_records_sha256"] == manifest["records_sha256"]
    assert reviewed_meta["manual_review_required"] is True
    assert reviewed_meta["major_change_reasons"] == [
        "Love Dining T&C PDF changed: restaurants, hotels"
    ]
    for event in reviewed_ledger["updates"]:
        if not event.get("transition_id"):
            continue
        assert event["transition_id"] == MODULE.source_change_alert.update_event_id(event)
        assert event["id"] == MODULE.source_change_alert._occurrence_id(
            event["stream_id"], event["transition_id"], event["occurrence"]
        )
    assert reviewed_ledger["identity_state"] == (
        MODULE.source_change_alert.rebuild_identity_state(reviewed_ledger["updates"])
    )

    same_meta, same_ledger = MODULE.apply_review(
        manifest, records, reviewed_meta, reviewed_ledger
    )
    assert same_meta == reviewed_meta
    assert same_ledger == reviewed_ledger


def test_wrong_record_hash_fails_without_mutating_inputs():
    manifest = _load(
        "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json"
    )
    records = _load("data/love-dining.json")
    meta = _load("data/love-dining-source.json")
    ledger = _load("data/updates.json")
    original_meta = copy.deepcopy(meta)
    original_ledger = copy.deepcopy(ledger)
    meta["records_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="record hash"):
        MODULE.apply_review(manifest, records, meta, ledger)

    assert original_meta["records_sha256"] != meta["records_sha256"]
    assert ledger == original_ledger


def test_unrelated_record_change_cannot_reuse_reviewed_metadata_hash():
    manifest = _load(
        "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json"
    )
    records = _load("data/love-dining.json")
    records[0]["notes"] = "Unreviewed unrelated mutation"

    with pytest.raises(ValueError, match="record hash"):
        MODULE.apply_review(
            manifest,
            records,
            _load("data/love-dining-source.json"),
            _load("data/updates.json"),
        )


def test_incomplete_manifest_fails_closed():
    manifest = _load(
        "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json"
    )
    manifest["mappings"].pop()

    with pytest.raises(ValueError, match="exactly six"):
        MODULE.apply_review(
            manifest,
            _load("data/love-dining.json"),
            _load("data/love-dining-source.json"),
            _load("data/updates.json"),
        )


def test_main_locks_before_reads_and_writes_ledger_before_meta(
    tmp_path, monkeypatch
):
    paths = {}
    for name, source in {
        "manifest": "data/reviews/love-dining/2026-08-30-hotel-attribution-correction.json",
        "data": "data/love-dining.json",
        "meta": "data/love-dining-source.json",
        "updates": "data/updates.json",
    }.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text((ROOT / source).read_text())
    locked = False
    reads = []
    writes = []
    real_load = MODULE._load

    @contextmanager
    def lock(_path):
        nonlocal locked
        locked = True
        try:
            yield
        finally:
            locked = False

    def observed_load(path):
        assert locked
        reads.append(path)
        return real_load(path)

    def observed_write(path, _payload):
        assert locked
        writes.append(path)
        if path == paths["meta"]:
            raise OSError("injected metadata write failure")

    monkeypatch.setattr(MODULE.source_change_alert, "_ledger_lock", lock)
    monkeypatch.setattr(MODULE.source_change_alert, "_atomic_write_json", observed_write)
    monkeypatch.setattr(MODULE, "_load", observed_load)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_love_dining_review.py",
            "--manifest",
            str(paths["manifest"]),
            "--data",
            str(paths["data"]),
            "--meta",
            str(paths["meta"]),
            "--updates",
            str(paths["updates"]),
        ],
    )

    with pytest.raises(OSError, match="metadata write failure"):
        MODULE.main()

    assert reads == [
        paths["manifest"],
        paths["data"],
        paths["meta"],
        paths["updates"],
    ]
    assert writes == [paths["updates"], paths["meta"]]
