"""Private one-shot Telegram reminder lifecycle and deterministic matching."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app import tft_guide, tft_slots


CONVERSATION_TTL = timedelta(minutes=15)
MAX_ACTIVE_REMINDERS = 5
MAX_LIVE_REMINDERS = 1_000
MAX_SPECIFIC_DATES = 10
MAX_SCAN_BATCH = 1_000
MAX_CLAIMS_PER_RUN = 2
MAX_NOTIFICATION_SLOTS = 8
REMINDER_ID_RE = re.compile(r"R[0-9A-F]{6}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_reminder_conversations (
  principal_key TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK(state IN ('venue', 'party', 'meal', 'dates', 'confirm', 'delete_confirm')),
  venue_id TEXT,
  venue_name TEXT,
  party_size INTEGER,
  meal TEXT,
  date_start TEXT,
  date_end TEXT,
  dates TEXT NOT NULL DEFAULT '[]',
  created_ts TEXT NOT NULL,
  expires_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_reminders (
  id TEXT PRIMARY KEY,
  principal_key TEXT NOT NULL,
  chat_id INTEGER NOT NULL,
  venue_id TEXT NOT NULL,
  venue_name TEXT NOT NULL,
  party_size INTEGER NOT NULL CHECK(party_size BETWEEN 1 AND 10),
  meal TEXT NOT NULL CHECK(meal IN ('Lunch', 'Dinner')),
  date_start TEXT NOT NULL,
  date_end TEXT NOT NULL,
  dates TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL CHECK(state IN ('active', 'claimed', 'sending', 'notified', 'cancelled', 'unknown', 'dead')),
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telegram_reminders_principal_state
ON telegram_reminders(principal_key, state, created_ts);
CREATE TABLE IF NOT EXISTS telegram_reminder_deliveries (
  reminder_id TEXT PRIMARY KEY,
  slot_fingerprint TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('claimed', 'sending', 'done', 'unknown', 'dead')),
  outcome_code TEXT,
  response_message_id INTEGER,
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  FOREIGN KEY(reminder_id) REFERENCES telegram_reminders(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS telegram_reminder_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Notification:
    reminder_id: str
    chat_id: int
    text: str


@dataclass(frozen=True)
class ClaimResult:
    notifications: list[Notification]
    active_scanned_count: int
    matched_count: int
    no_match_count: int
    stale_venue_count: int
    expired_count: int
    reconciled_claimed_count: int
    reconciled_unknown_count: int
    batch_limited: bool
    more_matches: bool


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def init_db(conn: sqlite3.Connection, identity_salt: str = "") -> None:
    conn.executescript(SCHEMA)
    if identity_salt:
        fingerprint = hashlib.sha256(identity_salt.encode()).hexdigest()
        current = conn.execute(
            "SELECT value FROM telegram_reminder_meta WHERE key = 'identity_salt'"
        ).fetchone()
        if current is None:
            conn.execute(
                "INSERT INTO telegram_reminder_meta (key, value) VALUES ('identity_salt', ?)",
                (fingerprint,),
            )
        elif current["value"] != fingerprint:
            live = conn.execute(
                "SELECT COUNT(*) FROM telegram_reminders "
                "WHERE state IN ('active', 'claimed', 'sending')"
            ).fetchone()[0]
            if int(live):
                raise RuntimeError(
                    "drain Telegram reminders before rotating the identity salt"
                )
            conn.execute(
                "UPDATE telegram_reminder_meta SET value = ? WHERE key = 'identity_salt'",
                (fingerprint,),
            )
    conn.commit()


def _purge(conn: sqlite3.Connection, now: datetime) -> tuple[int, int, int]:
    now_iso = _iso(now)
    stale = _iso(now - timedelta(minutes=5))
    conn.execute(
        "DELETE FROM telegram_reminder_conversations WHERE expires_ts < ?",
        (now_iso,),
    )
    reconciled_claimed = conn.execute(
        "UPDATE telegram_reminders SET state = 'active', updated_ts = ? "
        "WHERE state = 'claimed' AND updated_ts < ?",
        (now_iso, stale),
    ).rowcount
    conn.execute(
        "DELETE FROM telegram_reminder_deliveries "
        "WHERE state = 'claimed' AND updated_ts < ?",
        (stale,),
    )
    reconciled_unknown = conn.execute(
        "UPDATE telegram_reminders SET state = 'unknown', chat_id = 0, updated_ts = ? "
        "WHERE state = 'sending' AND updated_ts < ?",
        (now_iso, stale),
    ).rowcount
    conn.execute(
        "UPDATE telegram_reminder_deliveries SET state = 'unknown', "
        "outcome_code = 'stale_processing', updated_ts = ? "
        "WHERE state = 'sending' AND updated_ts < ?",
        (now_iso, stale),
    )
    today = now.astimezone(tft_slots.SGT).date().isoformat()
    expired = conn.execute(
        "UPDATE telegram_reminders SET state = 'cancelled', chat_id = 0, updated_ts = ? "
        "WHERE state = 'active' AND date_end < ?",
        (now_iso, today),
    ).rowcount
    conn.execute(
        "DELETE FROM telegram_reminders WHERE state IN ('notified', 'cancelled', 'dead') "
        "AND updated_ts < ?",
        (_iso(now - timedelta(days=30)),),
    )
    conn.execute(
        "DELETE FROM telegram_reminders WHERE state = 'unknown' AND updated_ts < ?",
        (_iso(now - timedelta(days=90)),),
    )
    return expired, reconciled_claimed, reconciled_unknown


def _save_conversation(
    conn: sqlite3.Connection,
    principal_key: str,
    state: str,
    now: datetime,
    **fields: Any,
) -> None:
    current = conn.execute(
        "SELECT * FROM telegram_reminder_conversations WHERE principal_key = ?",
        (principal_key,),
    ).fetchone()
    values = dict(current) if current else {}
    values.update(fields)
    created = str(values.get("created_ts") or _iso(now))
    absolute_expiry = datetime.fromisoformat(created) + timedelta(minutes=60)
    expiry = min(now + CONVERSATION_TTL, absolute_expiry)
    conn.execute(
        """
        INSERT INTO telegram_reminder_conversations (
          principal_key, state, venue_id, venue_name, party_size, meal,
          date_start, date_end, dates, created_ts, expires_ts, updated_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(principal_key) DO UPDATE SET
          state=excluded.state, venue_id=excluded.venue_id,
          venue_name=excluded.venue_name, party_size=excluded.party_size,
          meal=excluded.meal, date_start=excluded.date_start,
          date_end=excluded.date_end, dates=excluded.dates,
          created_ts=excluded.created_ts, expires_ts=excluded.expires_ts,
          updated_ts=excluded.updated_ts
        """,
        (
            principal_key,
            state,
            values.get("venue_id"),
            values.get("venue_name"),
            values.get("party_size"),
            values.get("meal"),
            values.get("date_start"),
            values.get("date_end"),
            values.get("dates", "[]"),
            created,
            _iso(expiry),
            _iso(now),
        ),
    )
    conn.commit()


def _confirmation_prompt(draft: sqlite3.Row) -> str:
    return (
        "Confirm this one-shot reminder:\n"
        f"{_summary(draft)}\n"
        "Timezone: Singapore (SGT, UTC+8).\n"
        "Reply YES to activate or /cancel. I will store this private chat ID and the confirmed criteria until the reminder ends or is cancelled; /delete_me removes your Telegram reminder data. I will notify once only when the first fresh cached AMEXPlatSG observation matches, then close it. This is not a reservation or booking guarantee."
    )


def _parse_dates(value: str, today: date) -> tuple[str, str, list[str]] | None:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) > 1:
        if len(parts) > MAX_SPECIFIC_DATES or any(
            DATE_RE.fullmatch(part) is None for part in parts
        ):
            return None
        try:
            parsed = sorted({date.fromisoformat(part) for part in parts})
        except ValueError:
            return None
        if not parsed or parsed[0] < today or parsed[-1] > today + timedelta(days=365):
            return None
        values = [item.isoformat() for item in parsed]
        return values[0], values[-1], values
    range_parts = value.split("..")
    if len(range_parts) not in {1, 2} or any(
        DATE_RE.fullmatch(part) is None for part in range_parts
    ):
        return None
    try:
        start = date.fromisoformat(range_parts[0])
        end = date.fromisoformat(range_parts[-1])
    except ValueError:
        return None
    if (
        start < today
        or end < start
        or end > today + timedelta(days=365)
        or (end - start).days + 1 > tft_slots.MAX_RANGE_DAYS
    ):
        return None
    return start.isoformat(), end.isoformat(), []


def _summary(row: sqlite3.Row | dict[str, Any]) -> str:
    dates = json.loads(row["dates"] or "[]")
    date_label = ", ".join(dates) if dates else (
        row["date_start"]
        if row["date_start"] == row["date_end"]
        else f"{row['date_start']} to {row['date_end']}"
    )
    return (
        f"{row['venue_name']} · {row['party_size']} pax · {row['meal']} · "
        f"{date_label}"
    )


def _new_id(conn: sqlite3.Connection) -> str:
    for _attempt in range(10):
        reminder_id = "R" + secrets.token_hex(3).upper()
        if conn.execute(
            "SELECT 1 FROM telegram_reminders WHERE id = ?", (reminder_id,)
        ).fetchone() is None:
            return reminder_id
    raise RuntimeError("could not allocate reminder id")


def handle_message(
    conn: sqlite3.Connection,
    principal_key: str,
    chat_id: int,
    text: str,
    catalog: dict,
    now: datetime,
) -> str | None:
    """Handle reminder commands/state; return None when the guide should answer."""
    message = " ".join(text.strip().split())
    lowered = message.casefold()
    expired_conversation = conn.execute(
        "SELECT 1 FROM telegram_reminder_conversations "
        "WHERE principal_key = ? AND expires_ts < ?",
        (principal_key, _iso(now)),
    ).fetchone() is not None
    _purge(conn, now)
    conn.commit()

    conversation = conn.execute(
        "SELECT * FROM telegram_reminder_conversations WHERE principal_key = ?",
        (principal_key,),
    ).fetchone()
    first_word = lowered.split(maxsplit=1)[0] if lowered else ""
    if conversation is not None and first_word in {
        "/start", "/help", "/venues", "/menu", "/release", "/slots"
    }:
        return None
    start_reminder = re.fullmatch(r"/start remind_([a-z0-9-]{1,80})", lowered)
    is_command = lowered in {
        "/remind", "/reminders", "/cancel", "/delete_me", "/confirm"
    } or lowered.startswith("/cancel ") or start_reminder is not None
    if conversation is None and not is_command:
        if expired_conversation:
            return "Reminder setup expired. Send /remind to start again."
        return None

    if start_reminder is not None:
        matches = tft_guide.resolve_venue(start_reminder.group(1), catalog)
        if len(matches) != 1:
            return "That venue link is not in the reviewed TFT roster. Use /venues."
        venue = matches[0]
        _save_conversation(
            conn, principal_key, "party", now,
            venue_id=venue["id"], venue_name=venue["name"],
        )
        return (
            f"Create one Table for Two reminder for {venue['name']} (2/4). "
            "Setup expires after 15 idle minutes.\n"
            "How many people (1–10)?\n"
            "If you confirm, I will store this private chat ID and the criteria until the reminder ends or is cancelled. /delete_me removes your Telegram reminder data; email reminders are separate."
        )

    if lowered == "/remind":
        if conversation is None:
            _save_conversation(conn, principal_key, "venue", now)
        else:
            prompts = {
                "venue": "Continue setup: send one exact venue name, or /cancel.",
                "party": "Continue setup: send a whole-number party size from 1 to 10, or /cancel.",
                "meal": "Continue setup: reply lunch or dinner, or /cancel.",
                "dates": "Continue setup: send future Singapore date(s), or /cancel.",
                "confirm": _confirmation_prompt(conversation),
                "delete_confirm": "Deletion is waiting: reply DELETE exactly, or /cancel.",
            }
            return prompts[conversation["state"]]
        return (
            "Create one Table for Two reminder (1/4). Setup expires after 15 idle minutes.\n"
            "Venue: send one exact venue name. Use /venues to browse, or /cancel.\n"
            "If you confirm, I will store this private chat ID and the criteria until the reminder ends or is cancelled. /delete_me removes your Telegram reminder data; email reminders are separate."
        )

    if lowered == "/reminders":
        rows = conn.execute(
            "SELECT * FROM telegram_reminders WHERE principal_key = ? "
            "AND state = 'active' ORDER BY created_ts LIMIT ?",
            (principal_key, MAX_ACTIVE_REMINDERS),
        ).fetchall()
        if not rows:
            return "You have no active TFT reminders. Send /remind to create one."
        return "Your active TFT reminders:\n" + "\n".join(
            f"• {row['id']} — {_summary(row)}" for row in rows
        ) + "\nCancel one with /cancel RXXXXXX."

    if lowered.startswith("/cancel "):
        reminder_id = message.split(maxsplit=1)[1].upper()
        if REMINDER_ID_RE.fullmatch(reminder_id) is None:
            return "Use /cancel RXXXXXX with an ID from /reminders."
        conn.execute("BEGIN IMMEDIATE")
        try:
            owned = conn.execute(
                "SELECT state FROM telegram_reminders WHERE id = ? AND principal_key = ?",
                (reminder_id, principal_key),
            ).fetchone()
            changed = 0
            if owned and owned["state"] in {"active", "claimed"}:
                changed = conn.execute(
                    "UPDATE telegram_reminders SET state = 'cancelled', "
                    "updated_ts = ?, chat_id = 0 WHERE id = ? AND principal_key = ? "
                    "AND state IN ('active', 'claimed')",
                    (_iso(now), reminder_id, principal_key),
                ).rowcount
                conn.execute(
                    "DELETE FROM telegram_reminder_deliveries "
                    "WHERE reminder_id = ? AND state = 'claimed'",
                    (reminder_id,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if changed:
            return f"Cancelled {reminder_id}. No future alert will be sent."
        if owned and owned["state"] == "sending":
            return "That reminder is already being delivered and cannot be cancelled now."
        return "No active reminder matched that code."

    if lowered == "/cancel":
        conn.execute(
            "DELETE FROM telegram_reminder_conversations WHERE principal_key = ?",
            (principal_key,),
        )
        conn.commit()
        return "Reminder setup cancelled."

    if lowered == "/delete_me":
        _save_conversation(
            conn, principal_key, "delete_confirm", now, created_ts=_iso(now)
        )
        return "Delete your Telegram reminder data? This removes active reminders, setup state, stored delivery chat ID, reminder receipts, and rate keys. It does not affect email reminders. Reply DELETE within 15 minutes or /cancel."

    if conversation and conversation["state"] == "delete_confirm":
        if message != "DELETE":
            return "Reply DELETE exactly to remove your reminder data, or /cancel."
        conn.execute("BEGIN IMMEDIATE")
        try:
            sending = conn.execute(
                "SELECT COUNT(*) FROM telegram_reminders "
                "WHERE principal_key = ? AND state = 'sending'",
                (principal_key,),
            ).fetchone()[0]
            if int(sending):
                conn.rollback()
                return "A reminder notification is finishing. Reply DELETE again shortly, or /cancel."
            conn.execute(
                "DELETE FROM telegram_reminder_conversations WHERE principal_key = ?",
                (principal_key,),
            )
            conn.execute(
                "DELETE FROM telegram_reminders WHERE principal_key = ?",
                (principal_key,),
            )
            conn.execute(
                "DELETE FROM telegram_rate_events WHERE scope_key = ?",
                (principal_key,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return "Deleted. Email reminders were not changed. Telegram may retain chat messages under its own policy."

    if conversation is None:
        return "No reminder setup is active. Send /remind to begin."

    state = conversation["state"]
    if state == "venue":
        matches = tft_guide.resolve_venue(message, catalog)
        if len(matches) != 1:
            return "I need one exact TFT venue. Use /venues, then reply with its name, or /cancel."
        venue = matches[0]
        _save_conversation(
            conn, principal_key, "party", now,
            venue_id=venue["id"], venue_name=venue["name"],
        )
        return f"{venue['name']}. How many people (1–10)?"
    if state == "party":
        if re.fullmatch(r"\d{1,2}", message) is None or not 1 <= int(message) <= 10:
            return "Reply with a whole-number party size from 1 to 10, or /cancel."
        _save_conversation(
            conn, principal_key, "meal", now, party_size=int(message)
        )
        return "Lunch or dinner?"
    if state == "meal":
        if lowered not in {"lunch", "dinner"}:
            return "Reply lunch or dinner, or /cancel."
        _save_conversation(
            conn, principal_key, "dates", now, meal=lowered.title()
        )
        return "Which date(s)? Use YYYY-MM-DD, a range like YYYY-MM-DD..YYYY-MM-DD (max 31 days), or up to 10 comma-separated dates. Singapore dates only."
    if state == "dates":
        parsed = _parse_dates(message, now.astimezone(tft_slots.SGT).date())
        if parsed is None:
            return "I could not validate those future Singapore dates. Use YYYY-MM-DD, a max-31-day range, or up to 10 comma-separated dates."
        start, end, dates = parsed
        _save_conversation(
            conn, principal_key, "confirm", now,
            date_start=start, date_end=end, dates=json.dumps(dates),
        )
        draft = conn.execute(
            "SELECT * FROM telegram_reminder_conversations WHERE principal_key = ?",
            (principal_key,),
        ).fetchone()
        return _confirmation_prompt(draft)
    if state == "confirm":
        if lowered != "yes":
            return "Reply YES to activate this reminder, or /cancel."
        now_iso = _iso(now)
        conn.execute("BEGIN IMMEDIATE")
        try:
            draft = conn.execute(
                "SELECT * FROM telegram_reminder_conversations "
                "WHERE principal_key = ? AND state = 'confirm'",
                (principal_key,),
            ).fetchone()
            if draft is None:
                conn.rollback()
                return "No reminder setup is awaiting confirmation. Send /remind to begin."
            active = conn.execute(
                "SELECT COUNT(*) FROM telegram_reminders "
                "WHERE principal_key = ? AND state IN ('active', 'claimed', 'sending')",
                (principal_key,),
            ).fetchone()[0]
            if int(active) >= MAX_ACTIVE_REMINDERS:
                conn.rollback()
                return "You already have 5 active reminders. Cancel one with /reminders before adding another."
            live = conn.execute(
                "SELECT COUNT(*) FROM telegram_reminders "
                "WHERE state IN ('active', 'claimed', 'sending')"
            ).fetchone()[0]
            if int(live) >= MAX_LIVE_REMINDERS:
                conn.rollback()
                return "Reminder capacity is temporarily full. Please try again after current reminders finish."
            reminder_id = _new_id(conn)
            conn.execute(
                """INSERT INTO telegram_reminders (
                  id, principal_key, chat_id, venue_id, venue_name, party_size,
                  meal, date_start, date_end, dates, state, created_ts, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    reminder_id, principal_key, chat_id, draft["venue_id"],
                    draft["venue_name"], draft["party_size"],
                    draft["meal"], draft["date_start"],
                    draft["date_end"], draft["dates"], now_iso, now_iso,
                ),
            )
            conn.execute(
                "DELETE FROM telegram_reminder_conversations WHERE principal_key = ?",
                (principal_key,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return f"Active reminder {reminder_id}: {_summary(draft)}\nIt expires after the final requested date in Singapore time. List with /reminders or cancel with /cancel {reminder_id}."
    return None


def is_management_message(
    conn: sqlite3.Connection, principal_key: str, text: str, now: datetime
) -> bool:
    lowered = " ".join(text.strip().split()).casefold()
    if lowered in {"/reminders", "/cancel", "/delete_me"} or lowered.startswith(
        "/cancel "
    ):
        return True
    if lowered != "delete":
        return False
    row = conn.execute(
        "SELECT 1 FROM telegram_reminder_conversations "
        "WHERE principal_key = ? AND state = 'delete_confirm' AND expires_ts >= ?",
        (principal_key, _iso(now)),
    ).fetchone()
    return row is not None


def _matching_slots(
    row: sqlite3.Row, venue: dict, now: datetime
) -> tuple[list[dict], bool]:
    checked = tft_slots._timestamp(venue.get("checked_at"))
    stale = checked is not None and now - checked > tft_slots.STALE_AFTER
    if (
        venue.get("project") != tft_slots.PROJECT
        or venue.get("status") != "live_available"
        or checked is None
        or checked > now + timedelta(minutes=5)
        or now - checked > tft_slots.STALE_AFTER
    ):
        return [], stale
    specific = set(json.loads(row["dates"] or "[]"))
    matches = []
    for meal in venue.get("meals") or []:
        if meal.get("meal") != row["meal"] or meal.get("status") != "available":
            continue
        for slot in meal.get("slots") or []:
            slot_date = str(slot.get("date") or "")
            if specific:
                date_matches = slot_date in specific
            else:
                date_matches = row["date_start"] <= slot_date <= row["date_end"]
            if (
                not date_matches
                or int(slot.get("max_seats") or 0) < row["party_size"]
                or tft_slots._minutes(slot.get("time")) is None
            ):
                continue
            matches.append(
                {
                    "date": slot_date,
                    "time": str(slot["time"]),
                    "max_seats": int(slot["max_seats"]),
                    "checked_at": checked,
                }
            )
    return sorted(matches, key=lambda item: (item["date"], item["time"])), False


def claim_notifications(
    conn: sqlite3.Connection, snapshot: dict, now: datetime
) -> ClaimResult:
    """Atomically claim at most one terminal delivery attempt per matching reminder."""
    if snapshot.get("source_project") != tft_slots.PROJECT:
        raise ValueError("unverified slot source")
    expired, reconciled_claimed, reconciled_unknown = _purge(conn, now)
    conn.commit()
    venues = {str(item.get("id")): item for item in snapshot.get("venues") or []}
    rows = conn.execute(
        "SELECT * FROM telegram_reminders WHERE state = 'active' "
        "ORDER BY created_ts LIMIT ?",
        (MAX_SCAN_BATCH + 1,),
    ).fetchall()
    batch_limited = len(rows) > MAX_SCAN_BATCH
    rows = rows[:MAX_SCAN_BATCH]
    notifications = []
    matched_count = 0
    stale_venue_count = 0
    more_matches = False
    for row in rows:
        matches, stale = _matching_slots(
            row, venues.get(row["venue_id"], {}), now
        )
        stale_venue_count += int(stale)
        if not matches:
            continue
        matched_count += 1
        if len(notifications) >= MAX_CLAIMS_PER_RUN:
            more_matches = True
            continue
        selected = matches[:MAX_NOTIFICATION_SLOTS]
        fingerprint = hashlib.sha256(
            json.dumps(selected, default=str, sort_keys=True).encode()
        ).hexdigest()
        now_iso = _iso(now)
        conn.execute("BEGIN IMMEDIATE")
        try:
            claimed = conn.execute(
                "UPDATE telegram_reminders SET state = 'claimed', updated_ts = ? "
                "WHERE id = ? AND state = 'active'",
                (now_iso, row["id"]),
            ).rowcount
            if claimed:
                conn.execute(
                    "INSERT INTO telegram_reminder_deliveries "
                    "(reminder_id, slot_fingerprint, state, created_ts, updated_ts) "
                    "VALUES (?, ?, 'claimed', ?, ?)",
                    (row["id"], fingerprint, now_iso, now_iso),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if not claimed:
            continue
        checked = selected[0]["checked_at"].astimezone(tft_slots.SGT).strftime(
            "%d %b %Y, %H:%M SGT"
        )
        lines = [
            f"• {item['date']} {item['time']} — up to {item['max_seats']} pax"
            for item in selected
        ]
        more = (
            f"\n• {len(matches) - len(selected)} more matching observations"
            if len(matches) > len(selected)
            else ""
        )
        text = (
            f"TFT reminder {row['id']} matched\n\n{_summary(row)}\n"
            + "\n".join(lines)
            + more
            + f"\n\nObserved in cached AMEXPlatSG data checked {checked}. Availability can change and this is not a booking guarantee. Book and redeem in the Amex Experiences App.\nOpen filtered venue: {tft_guide.explorer_url(venue_id=row['venue_id'], party_size=row['party_size'], meal=row['meal'], date_value=row['date_start'])}"
        )
        notifications.append(
            Notification(
                row["id"], int(row["chat_id"]), text[: tft_guide.MAX_REPLY_LENGTH]
            )
        )
    return ClaimResult(
        notifications=notifications,
        active_scanned_count=len(rows),
        matched_count=matched_count,
        no_match_count=len(rows) - matched_count,
        stale_venue_count=stale_venue_count,
        expired_count=expired,
        reconciled_claimed_count=reconciled_claimed,
        reconciled_unknown_count=reconciled_unknown,
        batch_limited=batch_limited,
        more_matches=more_matches,
    )


def begin_notification(
    conn: sqlite3.Connection, reminder_id: str, chat_id: int, now: datetime
) -> bool:
    now_iso = _iso(now)
    conn.execute("BEGIN IMMEDIATE")
    try:
        reminder_changed = conn.execute(
            "UPDATE telegram_reminders SET state = 'sending', updated_ts = ? "
            "WHERE id = ? AND chat_id = ? AND state = 'claimed'",
            (now_iso, reminder_id, chat_id),
        ).rowcount
        delivery_changed = conn.execute(
            "UPDATE telegram_reminder_deliveries SET state = 'sending', updated_ts = ? "
            "WHERE reminder_id = ? AND state = 'claimed'",
            (now_iso, reminder_id),
        ).rowcount
        if reminder_changed != delivery_changed:
            raise RuntimeError("reminder send claim conflict")
        conn.commit()
        return reminder_changed == 1
    except Exception:
        conn.rollback()
        raise


def complete_notification(
    conn: sqlite3.Connection,
    reminder_id: str,
    state: str,
    outcome_code: str,
    now: datetime,
    message_id: int | None = None,
) -> None:
    if state not in {"done", "unknown", "dead"}:
        raise ValueError("invalid reminder delivery state")
    reminder_state = "notified" if state == "done" else state
    now_iso = _iso(now)
    conn.execute("BEGIN IMMEDIATE")
    try:
        delivery_changed = conn.execute(
            "UPDATE telegram_reminder_deliveries SET state = ?, outcome_code = ?, "
            "response_message_id = ?, updated_ts = ? WHERE reminder_id = ? "
            "AND state = 'sending'",
            (state, outcome_code, message_id, now_iso, reminder_id),
        ).rowcount
        reminder_changed = conn.execute(
            "UPDATE telegram_reminders SET state = ?, chat_id = 0, updated_ts = ? "
            "WHERE id = ? AND state = 'sending'",
            (reminder_state, now_iso, reminder_id),
        ).rowcount
        if delivery_changed != 1 or reminder_changed != 1:
            raise RuntimeError("reminder delivery receipt conflict")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
