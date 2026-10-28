#!/usr/bin/env python3
"""Send published public-ledger events to the private owner-alert ingress as one digest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request
from pathlib import Path

try:
    from scripts.timeutil import iso_now
except ImportError:  # running as `python3 scripts/<file>.py`
    from timeutil import iso_now


try:
    from scripts import source_change_alert
except ModuleNotFoundError:  # Direct `python scripts/dispatch_owner_updates.py`.
    import source_change_alert


DEFAULT_UPDATES = Path("data/updates.json")
OWNER_ACTIONABLE_KINDS = {
    "added",
    "removed",
    "renamed",
    "menu_added",
    "menu_updated",
    "details_updated",
    "correction",
    "source_failed",
    "source_review_required",
    "source_updated",
    "terms_clause_added",
    "terms_clause_removed",
    "terms_clause_modified",
    "faq_clause_added",
    "faq_clause_removed",
    "faq_clause_modified",
}
OWNER_NOISE_KINDS = {
    "source_stale",
    "source_recovered",
    "source_health_changed",
    "source_review_cleared",
}


def published_events(
    path: Path, days: int = 90, now: datetime | None = None
) -> list[dict]:
    payload = json.loads(path.read_text())
    current = [
        event
        for event in payload.get("updates", [])
        if event.get("status") == "published"
        and event.get("owner_delivery_state")
        not in source_change_alert.TERMINAL_OWNER_DELIVERY_STATES
    ]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    eligible = []
    for event in current:
        value = event.get("reviewed_at") or event.get("detected_at")
        try:
            effective_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"Published event {event.get('id')} has an invalid timestamp") from exc
        if effective_at.tzinfo is None:
            raise RuntimeError(f"Published event {event.get('id')} has a naive timestamp")
        if effective_at >= cutoff:
            eligible.append(event)
    return eligible


def select_owner_notifications(events: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Keep owner Telegram focused on actionable content and persistent failures."""
    selected = []
    withheld = {}
    for event in events:
        event_id = str(event.get("id") or "")
        if event.get("kind") in OWNER_ACTIONABLE_KINDS:
            selected.append(event)
        elif event.get("kind") in OWNER_NOISE_KINDS and event_id:
            withheld[event_id] = "withheld"
        else:
            raise RuntimeError(
                f"Unknown published owner event kind: {event.get('kind') or 'missing'}"
            )
    return selected, withheld


INGEST_SUFFIX = "/api/owner-alerts/events"
BATCH_LIMIT = 500


def batch_url(ingest_url: str) -> str:
    if not ingest_url.endswith(INGEST_SUFFIX):
        raise RuntimeError(f"OWNER_ALERT_INGEST_URL must end with {INGEST_SUFFIX}")
    return ingest_url[: -len("/events")] + "/batch"


def _post_batch(url: str, token: str, events: list[dict]) -> dict[str, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps({"events": events}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(1_048_577)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                "Owner alert batch route returned HTTP 404; the reminders service "
                "needs the owner-alert digest deploy before this script can run"
            ) from exc
        raise RuntimeError(f"Owner alert ingress returned HTTP {exc.code}") from exc
    payload = json.loads(body)
    if payload.get("ok") is not True or not isinstance(payload.get("results"), list):
        raise RuntimeError("Owner alert ingress did not acknowledge the batch")
    return {
        str(result.get("id")): result
        for result in payload["results"]
        if isinstance(result, dict)
    }


def dispatch(
    url: str,
    token: str,
    events: list[dict],
    terminal_outcomes: dict[str, str] | None = None,
) -> int:
    target = batch_url(url)
    complete = 0
    failures = []
    for offset in range(0, len(events), BATCH_LIMIT):
        chunk = events[offset : offset + BATCH_LIMIT]
        results = _post_batch(target, token, chunk)
        for event in chunk:
            event_id = str(event.get("id"))
            result = results.get(event_id)
            state = result.get("state") if result else None
            if state in {"sent", "before_activation", "withheld"}:
                if terminal_outcomes is not None:
                    terminal_outcomes[event_id] = str(state)
                complete += 1
            elif state in {"unknown", "dead"}:
                if terminal_outcomes is not None:
                    terminal_outcomes[event_id] = str(state)
                error_code = result.get("error_code") or "not_reported"
                print(
                    f"::warning title=Owner alert quarantined::{event_id} is {state} "
                    f"({error_code}); it will not be retried automatically.",
                    file=sys.stderr,
                )
                complete += 1
            elif state == "schema_rejected":
                if terminal_outcomes is not None:
                    terminal_outcomes[event_id] = "schema_rejected"
                print(
                    f"::warning title=Owner alert schema rejected::{event_id} "
                    "was quarantined; later events will still be attempted.",
                    file=sys.stderr,
                )
                complete += 1
            else:
                failures.append(f"{event_id}:{state or 'missing'}")
    if failures:
        raise RuntimeError("Owner alert delivery incomplete: " + ", ".join(failures))
    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates", type=Path, default=DEFAULT_UPDATES)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    url = os.getenv("OWNER_ALERT_INGEST_URL", "").strip()
    token = os.getenv("OWNER_ALERT_INGEST_TOKEN", "").strip()
    if not url and not token:
        print("Owner alert dispatch is not configured; skipping.")
        return 0
    if not url.startswith("https://") or re.fullmatch(r"[A-Za-z0-9_-]{43,}", token) is None:
        raise RuntimeError("Owner alert ingress configuration is incomplete")
    batch_url(url)
    if not 1 <= args.days <= 365:
        raise RuntimeError("Owner alert replay window must be between 1 and 365 days")
    events, terminal_outcomes = select_owner_notifications(
        published_events(args.updates, args.days)
    )
    try:
        count = dispatch(url, token, events, terminal_outcomes)
    finally:
        source_change_alert.record_owner_delivery_states(
            args.updates,
            terminal_outcomes,
            iso_now(),
        )
    print(f"Owner alert ingress accepted {count} published ledger event(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
