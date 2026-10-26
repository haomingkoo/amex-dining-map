#!/usr/bin/env python3
"""Track when Table for Two venue/date/session availability first appears."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from collections import Counter, defaultdict
import bisect
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

try:
    from scripts.jsonio import load_json
except ImportError:  # running as `python3 scripts/<file>.py`
    from jsonio import load_json

try:
    from scripts.timeutil import parse_utc
except ImportError:  # running as `python3 scripts/<file>.py`
    from timeutil import parse_utc


SGT = ZoneInfo("Asia/Singapore")
SOURCE_PROJECT = "AMEXPlatSG"
# The alert run reads Railway's snapshot, which is up to five minutes older than the run.
LIVE_SNAPSHOT_MAX_AGE = timedelta(minutes=6)


def parse_time(value: str | None) -> datetime | None:
    return parse_utc(value)


def snapshot_time(payload: dict[str, Any]) -> datetime | None:
    candidates = [payload.get("availability_last_checked_at"), payload.get("last_verified_at")]
    for venue in payload.get("venues") or []:
        availability = venue.get("availability") or {}
        candidates.extend((availability.get("captured_at"), availability.get("checked_at")))
    parsed = [parsed for value in candidates if (parsed := parse_time(value))]
    return max(parsed) if parsed else None


def require_source_project(payload: dict[str, Any]) -> None:
    project = (payload.get("availability_source") or {}).get("project")
    if project != SOURCE_PROJECT:
        raise ValueError(f"release history requires {SOURCE_PROJECT} availability")


def require_history_project(history: dict[str, Any]) -> None:
    declared = history.get("source_project")
    has_observations = bool(history.get("observations"))
    if (declared is not None and declared != SOURCE_PROJECT) or (
        has_observations and declared is None
    ):
        raise ValueError(
            f"existing release history must declare source_project={SOURCE_PROJECT}"
        )
    history["source_project"] = SOURCE_PROJECT


def availability_keys(payload: dict[str, Any]) -> Iterable[tuple[str, str, str, str]]:
    for venue in payload.get("venues") or []:
        venue_id = str(venue.get("id") or "")
        venue_name = str(venue.get("app_name") or venue.get("name") or venue_id)
        if not venue_id:
            continue
        availability = venue.get("availability") or {}
        if availability.get("project") != SOURCE_PROJECT:
            continue
        for meal in availability.get("meals") or []:
            meal_name = str(meal.get("meal") or "Any session")
            dates = set(meal.get("dates") or [])
            dates.update(slot.get("date") for slot in meal.get("slots") or [] if slot.get("date"))
            for slot_date in sorted(dates):
                yield venue_id, venue_name, meal_name, str(slot_date)


def observation_id(venue_id: str, meal: str, slot_date: str) -> str:
    return hashlib.sha256(f"{venue_id}|{meal}|{slot_date}".encode()).hexdigest()[:20]


def iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_observation(
    key: tuple[str, str, str, str], observed_at: datetime, checked_after: datetime | None = None
) -> dict[str, Any]:
    venue_id, venue_name, meal, slot_date = key
    observed_sgt = observed_at.astimezone(SGT)
    lead_days = (date.fromisoformat(slot_date) - observed_sgt.date()).days
    return {
        "id": observation_id(venue_id, meal, slot_date),
        "venue_id": venue_id,
        "venue_name": venue_name,
        "meal": meal,
        "slot_date": slot_date,
        "first_seen_at": observed_at.isoformat().replace("+00:00", "Z"),
        "first_seen_sgt": observed_sgt.strftime("%Y-%m-%d %H:%M"),
        "lead_days": lead_days,
    } | ({"checked_after": iso_z(checked_after)} if checked_after and checked_after < observed_at else {})


def annotate_checked_after(
    observations: list[dict[str, Any]], checks: list[tuple[datetime, datetime]]
) -> int:
    """Give each observation the check before it, bounding when it really appeared.

    checks holds (started, observed_from) pairs: a run that read Railway's snapshot
    started after the snapshot it saw, so it only proves availability from a little
    before it started.
    """
    ordered = sorted(set(checks))
    starts = [started for started, _ in ordered]
    annotated = 0
    for item in observations:
        if item.get("baseline") or item.get("checked_after"):
            continue
        seen = parse_time(item.get("first_seen_at"))
        index = bisect.bisect_left(starts, seen) if seen else 0
        if index:
            item["checked_after"] = iso_z(min(ordered[index - 1][1], seen))
            annotated += 1
    return annotated


def half_hour_bucket(observation: dict[str, Any]) -> str:
    value = observation.get("first_seen_sgt") or ""
    try:
        observed = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    minute = 30 if observed.minute >= 30 else 0
    return f"{observed.hour:02d}:{minute:02d}"


def build_patterns(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        if observation.get("baseline") or observation.get("lead_days", -1) < 0:
            continue
        grouped[(observation["venue_id"], observation["meal"])].append(observation)

    patterns = []
    for (venue_id, meal), group in sorted(grouped.items()):
        if len(group) < 3:
            continue
        lead_days = [int(item["lead_days"]) for item in group]
        buckets = Counter(filter(None, (half_hour_bucket(item) for item in group)))
        count = len(group)
        common_time, common_time_count = buckets.most_common(1)[0] if buckets else (None, 0)
        time_share = common_time_count / count if count else 0
        typical_time = common_time if time_share >= 0.6 else None
        patterns.append({
            "venue_id": venue_id,
            "venue_name": group[0]["venue_name"],
            "meal": meal,
            "observation_count": count,
            "median_lead_days": round(float(statistics.median(lead_days)), 1),
            "lead_days_min": min(lead_days),
            "lead_days_max": max(lead_days),
            "typical_first_seen_sgt": typical_time,
            "typical_time_observation_share": round(time_share, 2),
            "confidence": "high" if count >= 15 else "medium" if count >= 6 else "early",
        })
    return patterns


def append_current(
    payload: dict[str, Any], history: dict[str, Any], checked_after: datetime | None = None
) -> int:
    require_source_project(payload)
    require_history_project(history)
    observed_at = snapshot_time(payload)
    if not observed_at:
        return 0
    known = {item["id"] for item in history.get("observations") or []}
    additions = []
    for key in availability_keys(payload):
        item = build_observation(key, observed_at, checked_after)
        if item["id"] not in known:
            additions.append(item)
            known.add(item["id"])
    history.setdefault("observations", []).extend(additions)
    return len(additions)


def rebuild_from_git(path: str, limit: int) -> dict[str, Any]:
    commits = subprocess.check_output(
        ["git", "log", f"-n{limit}", "--format=%H", "--reverse", "--", path], text=True
    ).splitlines()
    history: dict[str, Any] = {
        "schema_version": 1,
        "source_project": SOURCE_PROJECT,
        "observations": [],
    }
    accepted_snapshots = 0
    for commit in commits:
        try:
            raw = subprocess.check_output(["git", "show", f"{commit}:{path}"], text=True, stderr=subprocess.DEVNULL)
            payload = json.loads(raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        before = len(history["observations"])
        try:
            append_current(payload, history)
        except ValueError:
            continue
        if accepted_snapshots == 0:
            for observation in history["observations"][before:]:
                observation["baseline"] = True
        accepted_snapshots += 1
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/table-for-two.json")
    parser.add_argument("--output", default="data/table-for-two-release-history.json")
    parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--history-limit", type=int, default=300)
    parser.add_argument(
        "--previous-run-at",
        help="start of the previous successful check run (ISO); bounds when new dates appeared",
    )
    args = parser.parse_args()

    data_path = Path(args.data)
    output_path = Path(args.output)
    history = rebuild_from_git(args.data, args.history_limit) if args.from_git else (
        load_json(output_path) if output_path.exists() else {"schema_version": 1, "observations": []}
    )
    previous = parse_time(args.previous_run_at) if args.previous_run_at else None
    added = append_current(
        load_json(data_path), history, previous - LIVE_SNAPSHOT_MAX_AGE if previous else None
    )
    observations = history.get("observations") or []
    # Patterns derive only from observations, so an unchanged set needs no rewrite or commit.
    if not added and not args.from_git and output_path.exists():
        print(f"{len(observations)} observations, 0 new; history unchanged")
        return 0
    history["schema_version"] = 1
    history["updated_at"] = (snapshot_time(load_json(data_path)) or datetime.now(SGT)).isoformat()
    history["patterns"] = build_patterns(observations)
    output_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(observations)} observations, {len(history['patterns'])} patterns, {added} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
