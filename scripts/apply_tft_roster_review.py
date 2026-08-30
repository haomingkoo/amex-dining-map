#!/usr/bin/env python3
"""Atomically apply a hash-bound reviewed Table for Two roster."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts import source_change_alert, tft_roster_reviews
except ModuleNotFoundError:
    import source_change_alert
    import tft_roster_reviews


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def commit_review(manifest: dict, data_path: Path, updates_path: Path) -> None:
    """Commit through a resumable data -> ledger -> pending-clear protocol."""
    with source_change_alert._ledger_lock(data_path):
        current_data = load(data_path)
        updated_data, events = tft_roster_reviews.apply_manifest(manifest, current_data)
        if updated_data != current_data:
            source_change_alert._atomic_write_json(data_path, updated_data)
        reviewed_at = manifest["review"]["reviewed_at"]
        source_change_alert.append_updates(updates_path, events, reviewed_at)
        committed = load(data_path)
        roster_source = committed.get("roster_source") or {}
        if (
            roster_source.get("approved_manifest_sha256") == manifest["manifest_sha256"]
            and "pending_events" in roster_source
        ):
            roster_source.pop("pending_events")
            source_change_alert._atomic_write_json(data_path, committed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("data/table-for-two.json"))
    parser.add_argument("--updates", type=Path, default=Path("data/updates.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    manifest = load(args.manifest)
    tft_roster_reviews.validate_manifest(manifest, args.manifest)
    current_data = load(args.data)
    updated_data, pending = tft_roster_reviews.apply_manifest(manifest, current_data)
    if args.check:
        if updated_data != current_data or pending:
            raise SystemExit("Table for Two roster review has not been fully committed")
        print("Table for Two roster review is current")
        return 0
    commit_review(manifest, args.data, args.updates)
    print(f"Applied reviewed Table for Two roster ({len(manifest['venues'])} venues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
