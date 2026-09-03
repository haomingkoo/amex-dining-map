#!/usr/bin/env python3
"""Re-dispatch the workflow behind a stale source, then escalate if it stays stale.

Source health already detects staleness every 30 minutes, but nothing acted on it,
so a failed daily refresh waited a full day for its next cron. This closes that
loop: one retry per owning workflow per window, then a single deduped issue.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

DEFAULT_HEALTH_PATH = Path("data/source-health.json")
RETRY_WINDOW_HOURS = 6
DEGRADED_FRESHNESS = {"stale", "unavailable"}
ISSUE_TITLE = "Source data is stale: refresh needs attention"
ISSUE_LABEL = "source-health"

# A source is refreshed by exactly one workflow. Several sources can share one.
# `tabelog-ratings` is deliberately absent: Match Tabelog Candidates uploads a
# candidate artifact and commits nothing, so a retry cannot clear its staleness.
# It escalates to the issue instead, where a human runs the promote/merge steps.
SOURCE_WORKFLOWS = {
    "global-dining": "Refresh Global Dining Data",
    "japan-dining": "Refresh Data",
    "plat-stay": "Refresh Data",
    "love-dining": "Refresh Love Dining",
    "table-for-two-roster": "Refresh Table for Two",
    "table-for-two-menus": "Refresh Table for Two",
    "table-for-two-availability": "Table for Two Alerts",
    "google-maps-ratings": "Refresh Google Maps Ratings",
}
UNOWNED_SOURCES = {"tabelog-ratings"}


class Action(str, Enum):
    DISPATCH = "dispatch"
    ESCALATE = "escalate"
    SKIP = "skip"


@dataclass(frozen=True)
class Plan:
    workflow: str
    action: Action
    source_ids: tuple[str, ...]
    reason: str


def parse_utc(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_degraded(source: dict) -> bool:
    """A source needs attention when it is past its own freshness limit or failing.

    `review_required` is a human review flag, not staleness, so it is not included.
    """
    return (
        source.get("freshness_state") in DEGRADED_FRESHNESS
        or source.get("failure_state") not in (None, "clear")
    )


def degraded_sources(health: dict) -> list[dict]:
    return [source for source in health.get("sources") or [] if is_degraded(source)]


def plan_actions(
    sources: list[dict],
    last_dispatch_at: dict[str, datetime | None],
    now: datetime,
    retry_window_hours: float = RETRY_WINDOW_HOURS,
) -> list[Plan]:
    """One plan per owning workflow: retry once per window, then escalate."""
    by_workflow: dict[str, list[str]] = {}
    for source in sources:
        workflow = SOURCE_WORKFLOWS.get(str(source.get("id")))
        if not workflow:
            continue
        by_workflow.setdefault(workflow, []).append(str(source["id"]))

    cutoff = now - timedelta(hours=retry_window_hours)
    plans = []
    for workflow, source_ids in sorted(by_workflow.items()):
        previous = last_dispatch_at.get(workflow)
        if previous is None or previous < cutoff:
            action, reason = Action.DISPATCH, "no manual or watchdog retry in the window"
        else:
            action, reason = Action.ESCALATE, f"a retry at {previous:%Y-%m-%dT%H:%M:%SZ} did not clear it"
        plans.append(Plan(workflow, action, tuple(sorted(source_ids)), reason))
    return plans


def issue_body(sources: list[dict], plans: list[Plan], now: datetime) -> str:
    lines = [
        f"Source health reported degraded sources at {now:%Y-%m-%dT%H:%M:%SZ}.",
        "",
        "| Source | Freshness | Failure | Last checked | Limit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source in sorted(sources, key=lambda item: str(item.get("id"))):
        lines.append(
            f"| {source.get('id')} | {source.get('freshness_state')} | "
            f"{source.get('failure_state')} | {source.get('checked_at')} | "
            f"{source.get('stale_after_hours')}h |"
        )
    lines += ["", "Watchdog decisions:", ""]
    for plan in plans:
        lines.append(f"- `{plan.workflow}` -> {plan.action.value} ({plan.reason})")
    for source_id in sorted(str(s.get("id")) for s in sources if s.get("id") in UNOWNED_SOURCES):
        lines.append(f"- `{source_id}` -> no workflow refreshes this; it needs a manual run")
    lines += [
        "",
        "Only one of these is open at a time. Close it once the sources report",
        "`current` again; the watchdog opens a fresh one if they degrade later.",
    ]
    return "\n".join(lines) + "\n"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def last_workflow_dispatch(workflow: str) -> datetime | None:
    result = run(
        [
            "gh", "run", "list",
            "--workflow", workflow,
            "--event", "workflow_dispatch",
            "--limit", "10",
            "--json", "createdAt",
        ]
    )
    if result.returncode != 0:
        # Treat an unreadable history as "already retried" so a broken gh call
        # escalates instead of dispatching on every 30-minute monitor run.
        print(f"watchdog: cannot read runs for {workflow}: {result.stderr.strip()}", file=sys.stderr)
        return datetime.now(timezone.utc)
    stamps = [parse_utc(entry.get("createdAt")) for entry in json.loads(result.stdout or "[]")]
    valid = [stamp for stamp in stamps if stamp]
    return max(valid) if valid else None


def dispatch(workflow: str) -> bool:
    result = run(["gh", "workflow", "run", workflow])
    if result.returncode != 0:
        print(f"watchdog: dispatch failed for {workflow}: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def escalate(body: str) -> None:
    """Open one issue and leave it. The monitor runs every 30 minutes, so
    commenting on each pass would bury the signal it is meant to raise."""
    run(["gh", "label", "create", ISSUE_LABEL, "--color", "B60205",
         "--description", "A refresh source is stale or failing"])
    found = run(["gh", "issue", "list", "--state", "open", "--label", ISSUE_LABEL,
                 "--search", f"{ISSUE_TITLE} in:title", "--json", "number", "--jq", ".[0].number // empty"])
    if (found.stdout or "").strip():
        print("watchdog: an open source-health issue already carries this", file=sys.stderr)
        return
    body_path = Path("/tmp/watchdog-stale-sources.md")
    body_path.write_text(body, encoding="utf-8")
    run(["gh", "issue", "create", "--title", ISSUE_TITLE,
         "--label", ISSUE_LABEL, "--body-file", str(body_path)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health", type=Path, default=DEFAULT_HEALTH_PATH)
    parser.add_argument("--retry-window-hours", type=float, default=RETRY_WINDOW_HOURS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    health = json.loads(args.health.read_text(encoding="utf-8"))
    sources = degraded_sources(health)
    if not sources:
        print("watchdog: every source is within its freshness limit")
        return 0

    now = datetime.now(timezone.utc)
    workflows = {SOURCE_WORKFLOWS[s["id"]] for s in sources if s.get("id") in SOURCE_WORKFLOWS}
    last_dispatch = (
        {workflow: None for workflow in workflows}
        if args.dry_run
        else {workflow: last_workflow_dispatch(workflow) for workflow in workflows}
    )
    plans = plan_actions(sources, last_dispatch, now, args.retry_window_hours)

    unowned = [s["id"] for s in sources if s.get("id") not in SOURCE_WORKFLOWS]
    for source_id in unowned:
        print(f"watchdog: {source_id} is degraded and no workflow can refresh it", file=sys.stderr)

    escalating = [plan for plan in plans if plan.action is Action.ESCALATE]
    for plan in plans:
        print(f"watchdog: {plan.workflow} -> {plan.action.value} ({plan.reason}) for {', '.join(plan.source_ids)}")
        if args.dry_run or plan.action is not Action.DISPATCH:
            continue
        if not dispatch(plan.workflow):
            escalating.append(plan)

    if (escalating or unowned) and not args.dry_run:
        escalate(issue_body(sources, plans, now))
    # Staying quiet keeps the monitor green; the issue carries the signal.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
