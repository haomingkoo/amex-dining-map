#!/usr/bin/env python3
"""Overlay Railway's live TFT slot snapshot onto the committed roster for the alert job."""

from __future__ import annotations

import argparse
import copy
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.jsonio import load_json, save_json
    from scripts.timeutil import parse_utc
except ImportError:  # running as `python3 scripts/<file>.py`
    from jsonio import load_json, save_json
    from timeutil import parse_utc


SOURCE_PROJECT = "AMEXPlatSG"
# Matches the service's own TFT_LIVE_STALE_AFTER_SECONDS; it refreshes every 10 minutes.
MAX_AGE_SECONDS = 30 * 60
# Matches the service's MAX_SNAPSHOT_BYTES.
MAX_BODY_BYTES = 2_000_000
FETCH_TIMEOUT_SECONDS = 30
LIVE_STATUSES = {"live_available", "live_no_seats"}
UNKNOWN = {"project": SOURCE_PROJECT, "status": "unknown", "checked_at": None, "meals": []}


def _age_seconds(value: object, now: datetime) -> float | None:
    parsed = parse_utc(value)
    return None if parsed is None else (now - parsed).total_seconds()


def _availability(venue: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    if not venue or venue.get("status") not in LIVE_STATUSES:
        return dict(UNKNOWN)
    age = _age_seconds(venue.get("checked_at"), now)
    # A retained venue keeps its last good checked_at; past the limit it is not live.
    if age is None or age > MAX_AGE_SECONDS:
        return dict(UNKNOWN)
    return {
        "project": SOURCE_PROJECT,
        "status": venue["status"],
        "checked_at": venue["checked_at"],
        "meals": venue.get("meals") or [],
    }


def overlay_live_availability(roster: dict[str, Any], snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    if snapshot.get("source_project") != SOURCE_PROJECT:
        raise ValueError(f"live snapshot project is not {SOURCE_PROJECT}")
    age = _age_seconds(snapshot.get("generated_at"), now)
    if age is None or age > MAX_AGE_SECONDS:
        raise ValueError(f"live snapshot is stale or undated: generated_at={snapshot.get('generated_at')}")
    live = {venue.get("id"): venue for venue in snapshot.get("venues") or [] if isinstance(venue, dict)}
    payload = copy.deepcopy(roster)
    for venue in payload.get("venues") or []:
        venue["availability"] = _availability(live.get(venue.get("id")), now)
    payload["availability_last_checked_at"] = snapshot["generated_at"]
    payload["availability_source"] = {**(payload.get("availability_source") or {}), "project": SOURCE_PROJECT}
    return payload


def fetch_snapshot(base_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/tft/slots",
        headers={"Accept": "application/json", "User-Agent": "amex-tft-alerts/1"},
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("live snapshot exceeds size limit")
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", default="data/table-for-two.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base_url = os.environ.get("REMINDERS_API_BASE", "").strip()
    if not base_url:
        raise RuntimeError("REMINDERS_API_BASE is required to read live availability")
    payload = overlay_live_availability(load_json(args.roster), fetch_snapshot(base_url), datetime.now(timezone.utc))
    save_json(Path(args.output), payload)
    live = sum(venue["availability"]["status"] in LIVE_STATUSES for venue in payload["venues"])
    print(f"TFT LIVE OK generated_at={payload['availability_last_checked_at']} live_venues={live}/{len(payload['venues'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
