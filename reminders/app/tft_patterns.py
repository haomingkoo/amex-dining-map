"""Release-pattern replies: committed first-seen history plus Railway slot spans."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time as monotonic_time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app import db, tft_slot_history


logger = logging.getLogger(__name__)
SUMMARY_TTL_SECONDS = 60
MAX_LINE = 200
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "path": None, "value": None}
last_record: dict[str, Any] = {"at": None, "counts": None, "error": None}


def record_snapshot(db_path: Path | str, snapshot: dict) -> None:
    """Record one live snapshot; failures are logged and shown in health, never raised."""
    try:
        conn = db.connect(db_path)
        try:
            tft_slot_history.init_db(conn)
            counts = tft_slot_history.record(conn, snapshot)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.error("tft_slot_history record failed error=%s", type(exc).__name__)
        last_record.update(at=datetime.now(timezone.utc).isoformat(), error=type(exc).__name__)
        return
    last_record.update(at=datetime.now(timezone.utc).isoformat(), counts=counts, error=None)
    with _cache_lock:
        _cache["value"] = None


def live_summary(db_path: Path | str, now: datetime | None = None) -> dict[str, Any]:
    """Span summary, cached for a minute; empty when nothing is recorded yet."""
    with _cache_lock:
        fresh = (
            _cache["value"] is not None
            and _cache["path"] == str(db_path)
            and monotonic_time.monotonic() - _cache["at"] < SUMMARY_TTL_SECONDS
        )
        if fresh:
            return _cache["value"]
    try:
        conn = db.connect(db_path)
        try:
            tft_slot_history.init_db(conn)
            value = tft_slot_history.summary(conn, now or datetime.now(timezone.utc))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.error("tft_slot_history summary failed error=%s", type(exc).__name__)
        return {"started_at": None, "venues": {}}
    with _cache_lock:
        _cache.update(at=monotonic_time.monotonic(), path=str(db_path), value=value)
    return value


def _safe(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_LINE:
        return None
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        return None
    return value


def _day(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return None
    parsed = date.fromisoformat(value[:10])
    return f"{parsed.day} {parsed:%b %Y}"


def _quiet(release: dict) -> bool:
    meals = [meal for meal in release.get("meals") or [] if meal.get("rolling_lead_days") is not None]
    return bool(meals) and all(meal.get("quiet_days", 0) >= 7 for meal in meals)


def best_time_line(venue: dict, live_venue: dict | None) -> str:
    release = venue.get("release") or {}
    new_dates = _safe(release.get("best_time"))
    bucket = (live_venue or {}).get("best_return_bucket")
    returns = f"{bucket}s" if isinstance(bucket, str) and re.fullmatch(r"week(?:day|end) [a-z]+", bucket) else None
    if new_dates and returns:
        return f"Best time to look: {new_dates} for new dates; {returns} for cancellations."
    if new_dates:
        return f"Best time to look: {new_dates}."
    if returns:
        return f"Best time to look: {returns}, when cancellations have come back most often."
    if _quiet(release):
        return (
            "Best time to look: no new dates are opening right now, so cancellations are the "
            "main chance. /remind messages you when one opens."
        )
    return "Best time to look: not enough history yet to say."


def furthest_line(venue: dict) -> str | None:
    furthest = (venue.get("release") or {}).get("furthest_open_dates") or {}
    values = sorted({value for value in furthest.values() if isinstance(value, str) and _day(value)})
    if not values:
        return None
    last = date.fromisoformat(values[-1])
    return f"Open dates currently run to {last.day} {last:%b}."


def release_reply(venue: dict, catalog: dict, live: dict, explorer_line: str) -> str:
    name = venue.get("name") or "This venue"
    release = venue.get("release") or {}
    source = catalog.get("eligibility_source") or {}
    since = _day(source.get("new_dates_since"))
    lines = [f"{name}: when tables appear", ""]
    new_lines = [text for value in release.get("lines") or [] if (text := _safe(value))]
    lines.append(f"New dates{f' (tracked since {since})' if since else ''}:")
    if new_lines:
        lines.extend(f"• {text}" for text in new_lines)
    else:
        lines.append("• No steady pattern yet.")
    if furthest := furthest_line(venue):
        lines.append(furthest)
    live_venue = (live.get("venues") or {}).get(str(venue.get("id")))
    started = _day(live.get("started_at"))
    if started:
        lines += ["", f"How long tables last (tracked since {started}):"]
        live_lines = [text for value in (live_venue or {}).get("lines") or [] if (text := _safe(value))]
        if live_lines:
            lines.extend(f"• {text}" for text in live_lines)
        else:
            came_back = int((live_venue or {}).get("returned_tables") or 0)
            lines.append(
                f"• Too early to say. {came_back} table{'s have' if came_back != 1 else ' has'} come back so far."
            )
    lines += [
        "",
        best_time_line(venue, live_venue),
        "Times come from our checks, so they are approximate. Book in the Amex Experiences app.",
        explorer_line,
    ]
    return "\n".join(lines)
