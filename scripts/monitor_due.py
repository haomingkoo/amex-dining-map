#!/usr/bin/env python3
"""Decide whether a workflow_run-triggered Monitor Source Health run should do work.

Table for Two Alerts completes about every 15 minutes; this keeps the monitor to
one pass per MIN_GAP so its retries, issues and failure emails do not multiply.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable

try:
    from scripts.timeutil import parse_utc
except ImportError:  # running as `python3 scripts/<file>.py`
    from timeutil import parse_utc

WORKFLOW_FILE = "monitor-source-health.yml"
MONITOR_JOB = "monitor"
MIN_GAP = timedelta(minutes=25)
HISTORY = 20


def decide(
    run_ids: list[int],
    jobs_for: Callable[[int], list[dict]],
    now: datetime,
    min_gap: timedelta = MIN_GAP,
) -> tuple[bool, str]:
    for run_id in run_ids:
        job = next((item for item in jobs_for(run_id) if item.get("name") == MONITOR_JOB), None)
        if job is None or job.get("conclusion") == "skipped":
            continue
        if job.get("status") != "completed":
            return False, f"monitor run {run_id} is already {job.get('status')}"
        started = parse_utc(job.get("startedAt"))
        if started is None:
            return False, f"monitor run {run_id} has no start time"
        minutes = int((now - started).total_seconds() // 60)
        return now - started >= min_gap, f"last monitor pass started {minutes} min ago"
    return True, f"no monitor pass in the last {len(run_ids)} runs"


def gh_json(*args: str) -> object:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> int:
    current = os.environ.get("GITHUB_RUN_ID", "")
    try:
        runs = gh_json("run", "list", "--workflow", WORKFLOW_FILE, "--limit", str(HISTORY), "--json", "databaseId")
        run_ids = [run["databaseId"] for run in runs if str(run["databaseId"]) != current]
        due, reason = decide(
            run_ids,
            lambda run_id: gh_json("run", "view", str(run_id), "--json", "jobs")["jobs"],
            datetime.now(timezone.utc),
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # Skip rather than risk a burst of runs; the cron schedule still fires.
        detail = getattr(exc, "stderr", "") or exc
        print(f"::warning title=Monitor gate::cannot read run history ({detail}); skipping this pass.")
        due, reason = False, "run history unavailable"
    print(f"monitor gate: due={str(due).lower()} ({reason})")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"due={str(due).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
