#!/usr/bin/env python3
"""Send published public-ledger events to the private owner-alert ingress."""

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
    from scripts import source_change_alert
except ModuleNotFoundError:  # Direct `python scripts/dispatch_owner_updates.py`.
    import source_change_alert


DEFAULT_UPDATES = Path("data/updates.json")
OWNER_ACTIONABLE_KINDS = {
    "added",
    "removed",
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


def dispatch(
    url: str,
    token: str,
    events: list[dict],
    terminal_outcomes: dict[str, str] | None = None,
) -> int:
    complete = 0
    failures = []
    for event in events:
        request = urllib.request.Request(
            url,
            data=json.dumps({"event": event}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(65_537)
        except urllib.error.HTTPError as exc:
            if exc.code == 422:
                if terminal_outcomes is not None:
                    terminal_outcomes[str(event.get("id"))] = "schema_rejected"
                print(
                    f"::warning title=Owner alert schema rejected::{event.get('id')} "
                    "was quarantined; later events will still be attempted.",
                    file=sys.stderr,
                )
                complete += 1
                continue
            raise RuntimeError(f"Owner alert ingress returned HTTP {exc.code}") from exc
        payload = json.loads(body)
        if payload.get("ok") is not True:
            raise RuntimeError("Owner alert ingress did not acknowledge the event")
        state = payload.get("state")
        if state in {"sent", "before_activation", "withheld"}:
            if terminal_outcomes is not None:
                terminal_outcomes[str(event.get("id"))] = str(state)
            complete += 1
        elif state in {"unknown", "dead"}:
            if terminal_outcomes is not None:
                terminal_outcomes[str(event.get("id"))] = str(state)
            event_id = event.get("id")
            error_code = payload.get("error_code") or "not_reported"
            print(
                f"::warning title=Owner alert quarantined::{event_id} is {state} "
                f"({error_code}); it will not be retried automatically.",
                file=sys.stderr,
            )
            complete += 1
        else:
            failures.append(f"{event.get('id')}:{state or 'invalid_response'}")
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
            source_change_alert.now_iso(),
        )
    print(f"Owner alert ingress accepted {count} published ledger event(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
