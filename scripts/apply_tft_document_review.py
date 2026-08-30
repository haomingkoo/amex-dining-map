#!/usr/bin/env python3
"""Apply one reviewed TFT document transition with resumable owner events."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scripts import source_change_alert, tft_document_reviews
from scripts.official_document_reviews import manifest_sha256, verify_transition, verify_version


DATA = Path("data/table-for-two.json")
UPDATES = Path("data/updates.json")
CATALOG = Path("reminders/app/tft_guide_catalog.json")
RELEASE_HISTORY = Path("data/table-for-two-release-history.json")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _recompute_manual_review(source: dict[str, Any]) -> bool:
    from scripts import scrape_table_for_two

    roster_review = bool((source.get("roster_source") or {}).get("review_required"))
    document_review = tft_document_reviews.source_review_required(source)
    cycle_review = (
        (source.get("source_images") or {}).get("voucher_cycles_sha256")
        != scrape_table_for_two.KNOWN_CYCLES_SHA256
    )
    return roster_review or document_review or cycle_review


def _catalog_projection(
    source: dict[str, Any], release_history_path: Path, review_root: Path
) -> dict[str, Any]:
    from scripts import build_tft_guide_catalog

    return build_tft_guide_catalog.build_catalog(
        source,
        load(release_history_path),
        review_root,
    )


def apply_review(
    source: dict[str, Any],
    document_id: str,
    before_pdf: bytes,
    before_manifest: dict[str, Any],
    after_pdf: bytes,
    after_manifest: dict[str, Any],
    transition: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = tft_document_reviews.DOCUMENTS.get(document_id)
    if config is None:
        raise ValueError(f"unknown TFT document: {document_id}")
    state = (source.get("document_reviews") or {}).get(document_id)
    if not isinstance(state, dict):
        raise ValueError("document has no approved review state")
    observed = (source.get("source_documents") or {}).get(config["hash_key"])
    after_hash = hashlib.sha256(after_pdf).hexdigest()
    before_hash = hashlib.sha256(before_pdf).hexdigest()
    if state.get("approved_sha256") == after_hash:
        if state.get("approved_manifest_sha256") != manifest_sha256(after_manifest):
            raise ValueError("already-applied document manifest identity does not match")
        pending = state.get("pending_events")
        return copy.deepcopy(source), copy.deepcopy(pending if isinstance(pending, list) else [])
    if state.get("pending_events"):
        raise ValueError("retry the pending document event before applying another successor")
    if observed != after_hash or after_manifest.get("raw_sha256") != observed:
        raise ValueError("reviewed document does not match the current observed hash")
    if state.get("approved_sha256") != before_hash:
        raise ValueError("review predecessor does not match the approved public document")
    if state.get("approved_manifest_sha256") != manifest_sha256(before_manifest):
        raise ValueError("approved predecessor manifest identity does not match")

    events = verify_transition(
        tft_document_reviews.spec(source, document_id),
        before_pdf,
        before_manifest,
        after_pdf,
        after_manifest,
        transition,
    )
    updated = copy.deepcopy(source)
    reviews = copy.deepcopy(updated.get("document_reviews") or {})
    reviews[document_id] = {
        "status": "approved",
        "review_required": False,
        "observed_sha256": after_hash,
        "approved_sha256": after_hash,
        "approved_manifest_sha256": manifest_sha256(after_manifest),
        "approved_transition_sha256": manifest_sha256(transition),
        "approved_captured_at": after_manifest["captured_at"],
        "reviewed_at": transition["reviewed_at"],
        "review_item": None,
        "pending_events": copy.deepcopy(events),
    }
    updated["document_reviews"] = reviews
    updated["manual_review_required"] = _recompute_manual_review(updated)
    return updated, events


def commit_review(
    document_id: str,
    manifest_path: Path,
    transition_path: Path,
    data_path: Path,
    updates_path: Path,
    after_pdf_path: Path | None = None,
    review_root: Path = tft_document_reviews.REVIEW_ROOT,
    pdf_root: Path = tft_document_reviews.PDF_ROOT,
    transition_root: Path = tft_document_reviews.TRANSITION_ROOT,
    catalog_path: Path | None = None,
    release_history_path: Path = RELEASE_HISTORY,
) -> None:
    after_manifest = load(manifest_path)
    transition = load(transition_path)
    after_hash = after_manifest.get("raw_sha256")
    if not isinstance(after_hash, str):
        raise ValueError("review manifest has no content hash")
    expected_manifest = tft_document_reviews.manifest_path(
        document_id, after_hash, review_root
    )
    expected_transition = tft_document_reviews.transition_path(
        document_id,
        str(transition.get("from_raw_sha256") or ""),
        str(transition.get("to_raw_sha256") or ""),
        transition_root,
    )
    if manifest_path.resolve() != expected_manifest.resolve():
        raise ValueError("review manifest must use its canonical content-addressed path")
    if transition_path.resolve() != expected_transition.resolve():
        raise ValueError("document transition must use its canonical endpoint path")
    with source_change_alert._ledger_lock(data_path):
        source = load(data_path)
        state = (source.get("document_reviews") or {}).get(document_id) or {}
        before_hash = state.get("approved_sha256")
        if not isinstance(before_hash, str):
            raise ValueError("document has no approved predecessor")
        before_manifest = load(
            tft_document_reviews.manifest_path(document_id, before_hash, review_root)
        )
        before_pdf_path = tft_document_reviews.pdf_path(
            document_id, before_hash, pdf_root
        )
        before_pdf = before_pdf_path.read_bytes()
        retained_after_pdf = tft_document_reviews.pdf_path(
            document_id, str(after_manifest.get("raw_sha256") or ""), pdf_root
        )
        selected_after_pdf = after_pdf_path or retained_after_pdf
        if not selected_after_pdf.exists():
            raise ValueError("reviewed successor PDF is missing from the observation archive")
        after_pdf = selected_after_pdf.read_bytes()
        after_hash = hashlib.sha256(after_pdf).hexdigest()
        updated, events = apply_review(
            source,
            document_id,
            before_pdf,
            before_manifest,
            after_pdf,
            after_manifest,
            transition,
        )
        cached_after = tft_document_reviews.pdf_path(document_id, after_hash, pdf_root)
        if not cached_after.exists():
            _atomic_write_bytes(cached_after, after_pdf)
        elif cached_after.read_bytes() != after_pdf:
            raise ValueError("content-addressed PDF cache mismatch")
        if updated != source:
            source_change_alert._atomic_write_json(data_path, updated)
        source_change_alert.append_updates(
            updates_path, events, transition["reviewed_at"]
        )
        committed = load(data_path)
        committed_state = (committed.get("document_reviews") or {}).get(document_id) or {}
        if (
            committed_state.get("approved_manifest_sha256")
            == manifest_sha256(after_manifest)
            and "pending_events" in committed_state
        ):
            committed_state.pop("pending_events")
            source_change_alert._atomic_write_json(data_path, committed)
        if catalog_path is not None:
            source_change_alert._atomic_write_json(
                catalog_path,
                _catalog_projection(load(data_path), release_history_path, review_root),
            )


def check_review(
    document_id: str,
    manifest_path: Path,
    transition_path: Path,
    data_path: Path,
    updates_path: Path,
    review_root: Path,
    pdf_root: Path,
    transition_root: Path,
    catalog_path: Path | None = None,
    release_history_path: Path = RELEASE_HISTORY,
) -> None:
    source = load(data_path)
    after_manifest = load(manifest_path)
    transition = load(transition_path)
    state = (source.get("document_reviews") or {}).get(document_id) or {}
    after_hash = after_manifest.get("raw_sha256")
    if not isinstance(after_hash, str):
        raise ValueError("review manifest has no content hash")
    if manifest_path.resolve() != tft_document_reviews.manifest_path(
        document_id, after_hash, review_root
    ).resolve():
        raise ValueError("review manifest must use its canonical content-addressed path")
    if transition_path.resolve() != tft_document_reviews.transition_path(
        document_id,
        str(transition.get("from_raw_sha256") or ""),
        str(transition.get("to_raw_sha256") or ""),
        transition_root,
    ).resolve():
        raise ValueError("document transition must use its canonical endpoint path")
    after_pdf_path = tft_document_reviews.pdf_path(document_id, after_hash, pdf_root)
    if not after_pdf_path.exists():
        raise ValueError("reviewed successor PDF is missing from the content-addressed cache")
    reviewed = verify_version(
        tft_document_reviews.spec(source, document_id),
        after_pdf_path.read_bytes(),
        after_manifest,
    )
    if (
        state.get("approved_sha256") != reviewed["raw_sha256"]
        or state.get("approved_manifest_sha256") != manifest_sha256(reviewed)
        or state.get("review_required") is not False
        or state.get("approved_transition_sha256") != manifest_sha256(transition)
        or "pending_events" in state
    ):
        raise ValueError("TFT document review has not been fully applied")
    before_hash = transition.get("from_raw_sha256")
    if not isinstance(before_hash, str):
        raise ValueError("transition has no predecessor hash")
    before_manifest = load(
        tft_document_reviews.manifest_path(document_id, before_hash, review_root)
    )
    before_pdf = tft_document_reviews.pdf_path(document_id, before_hash, pdf_root).read_bytes()
    expected_events = verify_transition(
        tft_document_reviews.spec(source, document_id),
        before_pdf,
        before_manifest,
        after_pdf_path.read_bytes(),
        after_manifest,
        transition,
    )
    ledger = load(updates_path).get("updates") or []
    identities = {
        (event.get("stream_id"), event.get("transition_id"))
        for event in ledger
        if isinstance(event, dict) and event.get("status") == "published"
    }
    missing = [
        event
        for event in expected_events
        if (event.get("stream_id"), event.get("transition_id")) not in identities
    ]
    if missing:
        raise ValueError("reviewed owner event is missing from the durable update ledger")
    if catalog_path is not None:
        expected_catalog = _catalog_projection(source, release_history_path, review_root)
        if not catalog_path.exists() or load(catalog_path) != expected_catalog:
            raise ValueError("Telegram guide catalogue is stale after document review")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", choices=sorted(tft_document_reviews.DOCUMENTS), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--transition", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--updates", type=Path, default=UPDATES)
    parser.add_argument("--review-root", type=Path, default=tft_document_reviews.REVIEW_ROOT)
    parser.add_argument("--pdf-root", type=Path, default=tft_document_reviews.PDF_ROOT)
    parser.add_argument(
        "--transition-root", type=Path, default=tft_document_reviews.TRANSITION_ROOT
    )
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--release-history", type=Path, default=RELEASE_HISTORY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        check_review(
            args.document,
            args.manifest,
            args.transition,
            args.data,
            args.updates,
            args.review_root,
            args.pdf_root,
            args.transition_root,
            args.catalog,
            args.release_history,
        )
        print(f"TFT document review is current: {args.document}")
        return 0
    commit_review(
        args.document,
        args.manifest,
        args.transition,
        args.data,
        args.updates,
        args.pdf,
        args.review_root,
        args.pdf_root,
        args.transition_root,
        args.catalog,
        args.release_history,
    )
    print(f"Applied reviewed TFT document transition: {args.document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
