"""Opt-in daily digest: one quiet message listing new tables at the venues you follow.

Same consent model as reminders: nothing is stored until the user confirms with
/digest yes, the chat ID is kept only while the digest is on, /digest stop and
/delete_me erase it, and every message says how to stop.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app import db, telegram, tft_guide, tft_slot_history, tft_slots


SGT = ZoneInfo("Asia/Singapore")
SEND_HOUR_SGT = 9
DRAFT_TTL = timedelta(minutes=30)
DISPATCH_INTERVAL_SECONDS = 600
MAX_ROWS = 14
MAX_VENUES = 10
logger = logging.getLogger("amex_reminders.delivery")
last_dispatch: dict[str, Any] = {"at": None, "sent": 0, "dead": 0, "error": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_digests (
  principal_key TEXT PRIMARY KEY,
  chat_id INTEGER,
  venues TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('draft', 'active')),
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  expires_ts TEXT,
  last_sent_day TEXT,
  cursor_ts TEXT
);
"""

INTRO = (
    "The daily digest is one calm message a day, around 9am, listing new Table for Two "
    "tables at the venues you follow. Nothing is sent on days with nothing new.\n\n"
    "Pick venues: /digest Colony, VUE\nOr every venue: /digest all"
)
STOP = "/digest stop turns this off."


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _names(venue_ids: list[str], catalog: dict) -> str:
    if venue_ids == ["*"]:
        return "every venue"
    by_id = {str(venue.get("id")): str(venue.get("name")) for venue in catalog.get("venues") or []}
    names = [by_id.get(venue_id, venue_id) for venue_id in venue_ids]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _resolve(text: str, catalog: dict) -> tuple[list[str], list[str]]:
    if text.strip().casefold() in {"all", "every venue", "everything"}:
        return ["*"], []
    found, missing = [], []
    for part in re.split(r",|\band\b|&", text):
        part = part.strip()
        if not part:
            continue
        matches = tft_guide.resolve_venue(part, catalog)
        if len(matches) == 1:
            if matches[0]["id"] not in found:
                found.append(str(matches[0]["id"]))
        else:
            missing.append(part[:40])
    return found, missing


def handle(
    conn: sqlite3.Connection,
    principal_key: str,
    chat_id: int,
    text: str,
    catalog: dict,
    now: datetime,
) -> str | None:
    """Reply to /digest commands; None for anything else."""
    message = " ".join(text.strip().split())
    lowered = message.casefold()
    if not (lowered == "/digest" or lowered.startswith("/digest ")):
        return None
    arg = message[len("/digest"):].strip()
    row = conn.execute(
        "SELECT * FROM telegram_digests WHERE principal_key = ?", (principal_key,)
    ).fetchone()
    if row is not None and row["state"] == "draft" and row["expires_ts"] < _iso(now):
        conn.execute("DELETE FROM telegram_digests WHERE principal_key = ?", (principal_key,))
        conn.commit()
        row = None
    venues = json.loads(row["venues"]) if row is not None else []

    if arg.casefold() in {"stop", "off", "cancel", "unsubscribe"}:
        conn.execute("DELETE FROM telegram_digests WHERE principal_key = ?", (principal_key,))
        conn.commit()
        return (
            "Daily digest is off, and the chat ID it used is deleted."
            if row is not None
            else "You don't have a daily digest. /digest explains it."
        )
    if arg.casefold() in {"yes", "confirm"}:
        if row is None or row["state"] != "draft":
            return "Nothing is waiting to confirm. Send /digest to set one up."
        conn.execute(
            "UPDATE telegram_digests SET state = 'active', chat_id = ?, expires_ts = NULL, "
            "cursor_ts = ?, updated_ts = ? WHERE principal_key = ?",
            (chat_id, _iso(now), _iso(now), principal_key),
        )
        conn.commit()
        return (
            f"Daily digest is on for {_names(venues, catalog)}. From tomorrow I'll message you "
            f"once a day around 9am when new tables have opened, and stay quiet when nothing has. {STOP}"
        )
    if not arg:
        if row is not None and row["state"] == "active":
            return (
                f"Your daily digest covers {_names(venues, catalog)}, around 9am when something is new.\n"
                f"Change venues: /digest Colony, VUE. {STOP}"
            )
        if row is not None:
            return f"Your digest for {_names(venues, catalog)} is waiting. Reply /digest yes to start, or /digest stop."
        return INTRO

    chosen, missing = _resolve(arg, catalog)
    if missing:
        return (
            f"I couldn't match {', '.join(missing)} to a Table for Two venue. "
            "Use /venues for the list, then try again, e.g. /digest Colony, VUE."
        )
    if not chosen:
        return INTRO
    if len(chosen) > MAX_VENUES:
        return f"Pick up to {MAX_VENUES} venues, or /digest all."
    if row is not None and row["state"] == "active":
        conn.execute(
            "UPDATE telegram_digests SET venues = ?, updated_ts = ? WHERE principal_key = ?",
            (json.dumps(chosen), _iso(now), principal_key),
        )
        conn.commit()
        return f"Updated. Your daily digest now covers {_names(chosen, catalog)}. {STOP}"
    conn.execute(
        "INSERT INTO telegram_digests(principal_key, chat_id, venues, state, created_ts, updated_ts, expires_ts) "
        "VALUES (?, NULL, ?, 'draft', ?, ?, ?) ON CONFLICT(principal_key) DO UPDATE SET "
        "venues = excluded.venues, updated_ts = excluded.updated_ts, expires_ts = excluded.expires_ts",
        (principal_key, json.dumps(chosen), _iso(now), _iso(now), _iso(now + DRAFT_TTL)),
    )
    conn.commit()
    return (
        f"Daily digest for {_names(chosen, catalog)}: one message around 9am Singapore time on days "
        "with new tables.\nReply /digest yes to start. If you confirm, I will store this private "
        "chat ID until you turn the digest off; /delete_me removes it."
    )


def forget(conn: sqlite3.Connection, principal_key: str) -> None:
    conn.execute("DELETE FROM telegram_digests WHERE principal_key = ?", (principal_key,))


def _clock(value: str) -> str:
    return tft_slots.clock(value)


def compose(
    conn: sqlite3.Connection, venue_ids: list[str], since: str, catalog: dict, now: datetime
) -> str | None:
    """The digest text, or None when nothing new is still open."""
    today = now.astimezone(SGT).date().isoformat()
    names = {str(venue.get("id")): venue for venue in catalog.get("venues") or []}
    wanted = set(names) if venue_ids == ["*"] else set(venue_ids) & set(names)
    rows = conn.execute(
        "SELECT venue_id, meal, slot_date, slot_time, kind FROM tft_slot_spans "
        "WHERE closed_at IS NULL AND kind IN ('new', 'return') AND opened_at > ? AND slot_date >= ? "
        "ORDER BY slot_date, slot_time",
        (since, today),
    ).fetchall()
    grouped: dict[str, dict[tuple[str, str], list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for venue_id, meal, slot_date, slot_time, kind in rows:
        if venue_id in wanted:
            grouped[venue_id][(slot_date, meal)].append((slot_time, kind))
    if not grouped:
        return None
    local = now.astimezone(SGT)
    lines = [f"Table for Two digest, {local:%a} {local.day} {local:%b}", "New since your last digest and still open now:", ""]
    shown = 0
    hidden = 0
    for venue_id in sorted(grouped, key=lambda key: str(names[key].get("name")).casefold()):
        venue = names[venue_id]
        venue_lines = []
        for (slot_date, meal), items in sorted(grouped[venue_id].items()):
            if shown >= MAX_ROWS:
                hidden += 1
                continue
            day = date.fromisoformat(slot_date)
            times = ", ".join(_clock(slot_time) for slot_time, _kind in items[:4])
            more = f" and {len(items) - 4} more" if len(items) > 4 else ""
            note = " (new date)" if all(kind == "new" for _t, kind in items) else ""
            reason = tft_guide.blackout_reason(venue, slot_date)
            blackout = f". Blackout day in the Amex terms ({reason})" if reason else ""
            venue_lines.append(f"• {meal} {day:%a} {day.day} {day:%b}: {times}{more}{note}{blackout}")
            shown += 1
        if venue_lines:
            lines.append(str(venue.get("name")))
            lines.extend(venue_lines)
            lines.append("")
    if hidden:
        lines.append(f"And {hidden} more. /slots shows them all.")
        lines.append("")
    lines.append(f"Book in the Amex Experiences app. {STOP}")
    return "\n".join(lines)


def run_dispatch(settings: Any, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(SGT)
    counts = {"sent": 0, "dead": 0, "quiet": 0}
    if local.hour < SEND_HOUR_SGT:
        return counts
    today = local.date().isoformat()
    catalog = tft_guide.load_catalog()
    conn = db.connect(settings.db_path)
    try:
        init_db(conn)
        tft_slot_history.init_db(conn)
        due = conn.execute(
            "SELECT principal_key, chat_id, venues, cursor_ts FROM telegram_digests "
            "WHERE state = 'active' AND chat_id IS NOT NULL "
            "AND (last_sent_day IS NULL OR last_sent_day < ?)",
            (today,),
        ).fetchall()
        for principal_key, chat_id, venues, cursor_ts in due:
            text = compose(conn, json.loads(venues), cursor_ts or "", catalog, current)
            # Mark the day first: a lost reply must not become a second message.
            conn.execute(
                "UPDATE telegram_digests SET last_sent_day = ?, cursor_ts = ?, updated_ts = ? "
                "WHERE principal_key = ?",
                (today, _iso(current), _iso(current), principal_key),
            )
            conn.commit()
            if text is None:
                counts["quiet"] += 1
                continue
            try:
                telegram.send_message(settings.telegram_guide_bot_token, int(chat_id), text)
                counts["sent"] += 1
            except telegram.TelegramDeliveryError as exc:
                if exc.state == "dead":
                    forget(conn, principal_key)
                    conn.commit()
                    counts["dead"] += 1
                logger.warning("telegram_digest delivery failed error_code=%s", exc.code)
    finally:
        conn.close()
    return counts


def dispatch_and_record(settings: Any) -> None:
    try:
        counts = run_dispatch(settings)
    except sqlite3.Error as exc:
        logger.error("telegram_digest dispatch failed error=%s", type(exc).__name__)
        last_dispatch.update(at=datetime.now(timezone.utc).isoformat(), error=type(exc).__name__)
        return
    last_dispatch.update(
        at=datetime.now(timezone.utc).isoformat(), sent=counts["sent"], dead=counts["dead"], error=None
    )
