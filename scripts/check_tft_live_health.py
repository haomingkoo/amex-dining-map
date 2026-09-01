#!/usr/bin/env python3
"""Fail closed when Railway's public TFT snapshot breaches its live contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from typing import Any
import urllib.request


DEFAULT_URL = "https://amex-reminders-production.up.railway.app/healthz"
MAX_BODY_BYTES = 64 * 1024
MAX_CLOCK_DIFFERENCE_SECONDS = 120


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_health(
    payload: object,
    *,
    now: datetime | None = None,
    max_age_seconds: int = 30 * 60,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("service health is not ok")
    features = payload.get("feature_state")
    if not isinstance(features, dict) or features.get("tft_live_refresh_enabled") is not True:
        raise ValueError("live refresh is not enabled")
    live = payload.get("tft_live")
    if not isinstance(live, dict) or live.get("status") != "success":
        raise ValueError("live refresh status is not success")
    generated = _timestamp(live.get("generated_at"))
    if generated is None:
        raise ValueError("live generated time is invalid")
    reported_age = live.get("age_seconds")
    if not _integer(reported_age) or not 0 <= reported_age <= max_age_seconds:
        raise ValueError("live snapshot is outside the freshness window")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    calculated_age = max(
        0,
        int((current.astimezone(timezone.utc) - generated).total_seconds()),
    )
    if calculated_age > max_age_seconds:
        raise ValueError("live generated time is outside the freshness window")
    if abs(calculated_age - reported_age) > MAX_CLOCK_DIFFERENCE_SECONDS:
        raise ValueError("live age does not match generated time")
    counts = live.get("counts")
    if not isinstance(counts, dict) or any(
        not _integer(counts.get(key))
        for key in ("eligible", "succeeded", "failed", "retained")
    ):
        raise ValueError("live counts are invalid")
    if not (
        1 <= counts["eligible"] <= 50
        and counts["succeeded"] == counts["eligible"]
        and counts["failed"] == 0
        and counts["retained"] == 0
    ):
        raise ValueError("live refresh did not cover every eligible venue")
    deployment_id = payload.get("deployment_id")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ValueError("deployment id is unavailable")
    return {
        "deployment_id": deployment_id,
        "generated_at": live["generated_at"],
        "age_seconds": reported_age,
        "eligible": counts["eligible"],
    }


def fetch_health(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "amex-tft-health-check/1"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("health response exceeds size limit")
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--max-age-seconds", type=int, default=30 * 60)
    args = parser.parse_args()
    try:
        result = validate_health(
            fetch_health(args.url),
            max_age_seconds=args.max_age_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"TFT LIVE HEALTH FAILED reason={str(exc)}")
        return 1
    print(
        "TFT LIVE HEALTH OK "
        f"deployment={result['deployment_id']} "
        f"generated_at={result['generated_at']} "
        f"age_seconds={result['age_seconds']} "
        f"eligible={result['eligible']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
