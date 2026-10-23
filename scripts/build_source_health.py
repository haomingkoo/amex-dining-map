#!/usr/bin/env python3
"""Rebuild the public source-health snapshot and owner transition events."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_tft_live_health import fetch_health
from source_health import AVAILABILITY_SOURCE_ID, parse_time, update_source_health


def read_tft_live(url: str) -> tuple[dict[str, Any], str]:
    """Railway's live snapshot health, and whether this check produced a dated snapshot."""
    try:
        live = fetch_health(url).get("tft_live")
    except (OSError, ValueError, AttributeError, json.JSONDecodeError) as exc:
        print(f"SOURCE HEALTH live TFT check failed: {exc}")
        return {"status": "unavailable"}, "failure"
    if not isinstance(live, dict):
        return {"status": "unavailable"}, "failure"
    return live, "success" if parse_time(live.get("generated_at")) else "failure"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--updates", type=Path)
    parser.add_argument("--source", action="append", default=[], help="Source ID; repeatable")
    parser.add_argument("--attempt-outcome", choices=("success", "failure"))
    parser.add_argument("--tft-live-url", help="Railway /healthz URL; only the monitor passes it")
    parser.add_argument("--no-events", action="store_true")
    parser.add_argument("--now", help="UTC ISO-8601 time for deterministic builds")
    args = parser.parse_args()
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error("--now must be an ISO-8601 timestamp")
    if bool(args.source) != bool(args.attempt_outcome):
        parser.error("--source and --attempt-outcome must be supplied together")
    data_dir = args.root / "data"
    output = args.output or data_dir / "source-health.json"
    updates = args.updates or data_dir / "updates.json"
    attempts = {source: args.attempt_outcome for source in args.source}
    tft_live = None
    if args.tft_live_url:
        tft_live, attempts[AVAILABILITY_SOURCE_ID] = read_tft_live(args.tft_live_url)
    payload, events = update_source_health(
        data_dir,
        output,
        None if args.no_events else updates,
        now,
        attempts,
        tft_live,
    )
    print(f"SOURCE HEALTH OK sources={len(payload['sources'])} events={len(events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
