#!/usr/bin/env python3
"""Apply one exact Love Dining PDF baseline review to source metadata."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from scripts import source_change_alert
from scripts.official_document_reviews import manifest_sha256, verify_version
from scripts.verify_love_dining_documents import DOCUMENTS, document_spec
from scripts.verify_tft_official_documents import fetch_pdf


META = Path("data/love-dining-source.json")
UPDATES = Path("data/updates.json")


def _load(path: Path):
    return json.loads(path.read_text())


def apply_baseline(meta: dict, ledger: dict, key: str, reviewed: dict):
    if key not in DOCUMENTS or reviewed.get("review_status") != "current_baseline":
        raise ValueError("only a current Love Dining document baseline can be applied")
    document_id, _title = DOCUMENTS[key]
    current_hash = (meta.get("terms_hashes") or {}).get(key)
    if reviewed.get("document_id") != document_id or reviewed.get("raw_sha256") != current_hash:
        raise ValueError("reviewed document does not match current metadata")
    previously_reviewed = (meta.get("reviewed_terms_hashes") or {}).get(key)
    manifest_digest = manifest_sha256(reviewed)
    if previously_reviewed == current_hash:
        stored_digest = (meta.get("reviewed_terms_manifest_sha256") or {}).get(key)
        stored_reviewed_at = (meta.get("terms_reviewed_at_by_document") or {}).get(key)
        if stored_digest != manifest_digest or stored_reviewed_at != reviewed.get("reviewed_at"):
            raise ValueError("already-applied baseline review identity does not match")
        return copy.deepcopy(meta), copy.deepcopy(ledger)
    if (reviewed.get("lineage") or {}).get("previous_observed_sha256") != previously_reviewed:
        raise ValueError("document baseline lineage does not match reviewed metadata")
    updated_meta = copy.deepcopy(meta)
    reviewed_hashes = dict(updated_meta.get("reviewed_terms_hashes") or {})
    reviewed_hashes[key] = current_hash
    updated_meta["reviewed_terms_hashes"] = reviewed_hashes
    manifest_hashes = dict(updated_meta.get("reviewed_terms_manifest_sha256") or {})
    manifest_hashes[key] = manifest_digest
    updated_meta["reviewed_terms_manifest_sha256"] = manifest_hashes
    review_times = dict(updated_meta.get("terms_reviewed_at_by_document") or {})
    review_times[key] = reviewed["reviewed_at"]
    updated_meta["terms_reviewed_at_by_document"] = review_times

    pending = [
        candidate
        for candidate in DOCUMENTS
        if (updated_meta.get("terms_hashes") or {}).get(candidate)
        != reviewed_hashes.get(candidate)
    ]
    reasons = [
        reason
        for reason in updated_meta.get("major_change_reasons") or []
        if not str(reason).startswith("Love Dining T&C PDF changed:")
    ]
    if pending:
        reasons.append(f"Love Dining T&C PDF changed: {', '.join(pending)}")
    else:
        updated_meta["terms_reviewed_at"] = max(review_times.values())
    updated_meta["major_change_reasons"] = reasons
    updated_meta["manual_review_required"] = bool(reasons)
    updated_ledger = copy.deepcopy(ledger)
    if not pending:
        expected = {
            "Restaurant T&C PDF hash": updated_meta["terms_hashes"]["restaurants"][:12],
            "Hotel T&C PDF hash": updated_meta["terms_hashes"]["hotels"][:12],
        }
        candidates = []
        for event in updated_ledger.get("updates") or []:
            after = {
                change.get("field"): change.get("after")
                for change in event.get("changes") or []
                if isinstance(change, dict)
            }
            if (
                event.get("program_id") == "love-dining"
                and event.get("kind") == "source_updated"
                and all(after.get(field) == value for field, value in expected.items())
            ):
                candidates.append(event)
        if len(candidates) != 1 or candidates[0].get("status") not in {
            "review_required",
            "rejected",
        }:
            raise ValueError("matching Love Dining source review event is missing")
        source_event = candidates[0]
        source_event["status"] = "rejected"
        source_event["reviewed_at"] = updated_meta["terms_reviewed_at"]
        source_event["review_note"] = (
            "Roster changes were superseded by reviewed correction events. Current "
            "T&C versions are approved as baselines only; prior PDF content was not "
            "retained, so no retroactive clause-level change is claimed."
        )
        updated_ledger["updated_at"] = updated_meta["terms_reviewed_at"]
    return updated_meta, updated_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", choices=sorted(DOCUMENTS), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--meta", type=Path, default=META)
    parser.add_argument("--updates", type=Path, default=UPDATES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    with source_change_alert._ledger_lock(args.updates):
        meta = _load(args.meta)
        ledger = _load(args.updates)
        manifest = _load(args.manifest)
        document_id, title = DOCUMENTS[args.key]
        source_url = (meta.get("terms") or {}).get(args.key)
        pdf_bytes = args.pdf.read_bytes() if args.pdf else fetch_pdf(str(source_url))
        reviewed = verify_version(
            document_spec(document_id, title, str(source_url)), pdf_bytes, manifest
        )
        updated_meta, updated_ledger = apply_baseline(
            meta, ledger, args.key, reviewed
        )
        if args.check:
            if updated_meta != meta or updated_ledger != ledger:
                raise SystemExit("Love Dining document baseline has not been applied")
            print("Love Dining document baseline is current")
            return 0
        source_change_alert._atomic_write_json(args.updates, updated_ledger)
        source_change_alert._atomic_write_json(args.meta, updated_meta)
    print(f"Applied {args.key} Love Dining document baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
