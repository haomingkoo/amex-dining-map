"""How long Table for Two slots stay open, recorded from each live snapshot.

Each fresh venue in a snapshot is diffed against the slots still open from the
previous one. A slot that appears beyond the furthest date already open is a new
release; one that appears inside the open window came back, usually a cancellation.
Times are bounded by the previous check, so durations are upper bounds.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


SGT = ZoneInfo("Asia/Singapore")
logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tft_slot_spans (
  id INTEGER PRIMARY KEY,
  venue_id TEXT NOT NULL,
  meal TEXT NOT NULL,
  slot_date TEXT NOT NULL,
  slot_time TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('baseline', 'new', 'return')),
  opened_at TEXT NOT NULL,
  opened_after TEXT,
  closed_at TEXT,
  closed_after TEXT,
  close_reason TEXT CHECK(close_reason IN ('gone', 'expired'))
);
CREATE INDEX IF NOT EXISTS idx_tft_spans_open ON tft_slot_spans(venue_id, closed_at);
CREATE INDEX IF NOT EXISTS idx_tft_spans_closed ON tft_slot_spans(closed_at);
CREATE TABLE IF NOT EXISTS tft_slot_cursor (
  venue_id TEXT NOT NULL,
  meal TEXT NOT NULL,
  max_date TEXT NOT NULL,
  PRIMARY KEY(venue_id, meal)
);
CREATE TABLE IF NOT EXISTS tft_slot_checks (
  venue_id TEXT PRIMARY KEY,
  last_checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tft_slot_history_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

RETENTION = timedelta(days=180)
# A venue losing this many open slots at once looks like a bad read, not bookings.
SUSPECT_DROP_COUNT = 40
SUSPECT_DROP_SHARE = 0.5
MIN_LASTED_FOR_VERDICT = 5
MIN_RETURNS_FOR_VERDICT = 10
RETURN_BUCKET_SHARE = 0.35
DAYPARTS = (("night", 0, 6), ("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 24))


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _slot_keys(venue: dict) -> set[tuple[str, str, str]]:
    keys = set()
    for meal in venue.get("meals") or []:
        for slot in meal.get("slots") or []:
            if slot.get("date") and slot.get("time"):
                keys.add((str(meal.get("meal")), str(slot["date"]), str(slot["time"])))
    return keys


def _slot_moment(slot_date: str, slot_time: str) -> datetime | None:
    try:
        return datetime.combine(
            date.fromisoformat(slot_date), time.fromisoformat(slot_time), SGT
        ).astimezone(timezone.utc)
    except ValueError:
        return None


def record(conn: sqlite3.Connection, snapshot: dict) -> dict[str, int]:
    """Apply one validated live snapshot. Returns counts of what changed."""
    checked = _parse(snapshot.get("generated_at"))
    counts = Counter()
    if checked is None:
        return dict(counts)
    stamp = _iso(checked)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO tft_slot_history_meta(key, value) VALUES ('started_at', ?)",
            (stamp,),
        )
        for venue in snapshot.get("venues") or []:
            if venue.get("result") != "fresh" or venue.get("status") not in {"live_available", "live_no_seats"}:
                continue
            venue_id = str(venue.get("id") or "")
            if not venue_id or _parse(venue.get("checked_at")) != checked:
                continue
            _record_venue(conn, venue_id, _slot_keys(venue), checked, counts)
        conn.execute(
            "DELETE FROM tft_slot_spans WHERE closed_at IS NOT NULL AND closed_at < ?",
            (_iso(checked - RETENTION),),
        )
    return dict(counts)


def _record_venue(
    conn: sqlite3.Connection,
    venue_id: str,
    current: set[tuple[str, str, str]],
    checked: datetime,
    counts: Counter,
) -> None:
    stamp = _iso(checked)
    row = conn.execute(
        "SELECT last_checked_at FROM tft_slot_checks WHERE venue_id = ?", (venue_id,)
    ).fetchone()
    previous = row[0] if row else None
    if previous is not None and previous >= stamp:
        return
    open_rows = {
        (meal, slot_date, slot_time): span_id
        for span_id, meal, slot_date, slot_time in conn.execute(
            "SELECT id, meal, slot_date, slot_time FROM tft_slot_spans "
            "WHERE venue_id = ? AND closed_at IS NULL",
            (venue_id,),
        )
    }
    vanished = set(open_rows) - current
    if len(vanished) >= SUSPECT_DROP_COUNT and len(vanished) >= SUSPECT_DROP_SHARE * len(open_rows):
        logger.warning("tft_slot_history skipped venue=%s reason=suspect_drop", venue_id)
        counts["skipped"] += 1
        return
    max_dates = dict(
        conn.execute("SELECT meal, max_date FROM tft_slot_cursor WHERE venue_id = ?", (venue_id,))
    )
    for key in vanished:
        moment = _slot_moment(key[1], key[2])
        reason = "expired" if moment is None or moment <= checked else "gone"
        conn.execute(
            "UPDATE tft_slot_spans SET closed_at = ?, closed_after = ?, close_reason = ? WHERE id = ?",
            (stamp, previous, reason, open_rows[key]),
        )
        counts[reason] += 1
    for meal, slot_date, slot_time in sorted(current - set(open_rows)):
        if previous is None:
            kind = "baseline"
        elif meal not in max_dates or slot_date > max_dates[meal]:
            kind = "new"
        else:
            kind = "return"
        conn.execute(
            "INSERT INTO tft_slot_spans(venue_id, meal, slot_date, slot_time, kind, opened_at, opened_after) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (venue_id, meal, slot_date, slot_time, kind, stamp, previous),
        )
        counts[kind] += 1
    furthest: dict[str, str] = {}
    for meal, slot_date, _slot_time in current:
        furthest[meal] = max(slot_date, furthest.get(meal, ""))
    for meal, slot_date in furthest.items():
        conn.execute(
            "INSERT INTO tft_slot_cursor(venue_id, meal, max_date) VALUES (?, ?, ?) "
            "ON CONFLICT(venue_id, meal) DO UPDATE SET max_date = MAX(max_date, excluded.max_date)",
            (venue_id, meal, slot_date),
        )
    conn.execute(
        "INSERT INTO tft_slot_checks(venue_id, last_checked_at) VALUES (?, ?) "
        "ON CONFLICT(venue_id) DO UPDATE SET last_checked_at = excluded.last_checked_at",
        (venue_id, stamp),
    )


def _daypart(moment: datetime) -> str:
    local = moment.astimezone(SGT)
    part = next(name for name, start, end in DAYPARTS if start <= local.hour < end)
    return f"{'weekend' if local.weekday() >= 5 else 'weekday'} {part}"


def _round_up(minutes: float, step: int = 5) -> int:
    return max(step, int(-(-minutes // step) * step))


def _lasted_line(minutes: list[float], noun: str) -> str | None:
    if len(minutes) < MIN_LASTED_FOR_VERDICT:
        return None
    median = statistics.median(minutes)
    if median <= 60:
        return f"{noun} have usually gone within {_round_up(median)} minutes."
    if median <= 24 * 60:
        return f"{noun} have usually lasted under {int(-(-median // 60))} hours."
    return f"{noun} have usually stayed open for more than a day."


def summary(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    """Per-venue durations and returns since recording started."""
    started_row = conn.execute(
        "SELECT value FROM tft_slot_history_meta WHERE key = 'started_at'"
    ).fetchone()
    started = _parse(started_row[0]) if started_row else None
    venues: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"new_lasted": [], "return_lasted": [], "returns": 0, "new": 0, "buckets": Counter()}
    )
    for venue_id, kind, opened_at, opened_after, closed_at, reason in conn.execute(
        "SELECT venue_id, kind, opened_at, opened_after, closed_at, close_reason "
        "FROM tft_slot_spans WHERE kind IN ('new', 'return')"
    ):
        entry = venues[venue_id]
        opened = _parse(opened_at)
        if opened is None:
            continue
        entry[kind if kind == "new" else "returns"] += 1
        if kind == "return":
            entry["buckets"][_daypart(opened)] += 1
        closed, after = _parse(closed_at), _parse(opened_after)
        if reason == "gone" and closed and after:
            entry["new_lasted" if kind == "new" else "return_lasted"].append(
                (closed - after).total_seconds() / 60
            )
    days = max(1.0, (now - started).total_seconds() / 86_400) if started else 1.0
    result = {}
    for venue_id, entry in venues.items():
        buckets = entry["buckets"]
        top = buckets.most_common(1)[0] if buckets else None
        lines = [
            line
            for line in (
                _lasted_line(entry["new_lasted"], "New tables"),
                _lasted_line(entry["return_lasted"], "Tables that came back"),
            )
            if line
        ]
        best_return = None
        if top and entry["returns"] >= MIN_RETURNS_FOR_VERDICT and top[1] / entry["returns"] >= RETURN_BUCKET_SHARE:
            best_return = top[0]
            lines.append(f"Cancellations have come back most often on {best_return}s.")
        result[venue_id] = {
            "new_tables": entry["new"],
            "returned_tables": entry["returns"],
            "returns_per_day": round(entry["returns"] / days, 1),
            "new_lasted_minutes": [round(value) for value in sorted(entry["new_lasted"])][:200],
            "return_buckets": {name: buckets.get(name, 0) for name in _bucket_names()},
            "best_return_bucket": best_return,
            "lines": lines,
        }
    return {"started_at": _iso(started) if started else None, "venues": result}


def _bucket_names() -> list[str]:
    return [f"{kind} {name}" for kind in ("weekday", "weekend") for name, _s, _e in DAYPARTS]
