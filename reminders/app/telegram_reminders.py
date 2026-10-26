"""Private one-shot Telegram reminder lifecycle and deterministic matching."""

from __future__ import annotations

import hashlib
import json
import calendar
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app import telegram_digest, tft_guide, tft_slots


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
    telegram_digest.init_db(conn)
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
        f"Set this reminder?\n{_summary(draft)} (Singapore time)\n\n"
        "Reply YES to turn it on, or /cancel. I'll notify once only when a matching slot "
        "appears, then close it. If you confirm, I will store this private chat ID until the "
        "reminder ends or is cancelled; /delete_me removes it. Not a booking guarantee."
    )


MONTHS = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name} | {
    name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name
} | {"sept": 9}
_MONTH = r"(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")"
DAY_MONTH_RE = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}(?:\s+(\d{{4}}))?$")
MONTH_DAY_RE = re.compile(rf"^{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?$")
SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$")
MONTH_ONLY_RE = re.compile(rf"^(?:all of |whole of |in )?{_MONTH}(?:\s+(\d{{4}}))?$")
WEEKDAYS = {name.casefold(): i for i, name in enumerate(calendar.day_name)}
EVERY_RE = re.compile(
    rf"^(?:every |any |all )?(weekend|saturday|sunday|friday|{'|'.join(WEEKDAYS)})s?"
    rf"(?: in {_MONTH}(?:\s+(\d{{4}}))?)?$"
)


def _next_date(day: int, month: int, year: str | None, today: date) -> date | None:
    try:
        if year:
            return date(int(year), month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _one_date(text: str, today: date) -> date | None:
    text = text.strip()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if DATE_RE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    if m := DAY_MONTH_RE.match(text):
        return _next_date(int(m.group(1)), MONTHS[m.group(2)], m.group(3), today)
    if m := MONTH_DAY_RE.match(text):
        return _next_date(int(m.group(2)), MONTHS[m.group(1)], m.group(3), today)
    if m := SLASH_RE.match(text):
        return _next_date(int(m.group(1)), int(m.group(2)), m.group(3), today)
    return None


def _month_bounds(month: int, year: str | None, today: date) -> tuple[date, date]:
    y = int(year) if year else (today.year if month >= today.month else today.year + 1)
    return max(date(y, month, 1), today), date(y, month, calendar.monthrange(y, month)[1])


def date_examples(today: date) -> dict[str, str]:
    """Examples drawn from next month, so prompts never name a past or stale month."""
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    abbr, name = calendar.month_abbr[m], calendar.month_name[m]
    return {"month": name.lower(), "day": f"14 {abbr}", "range": f"1 {abbr} to 15 {abbr}",
            "weekends": f"weekends in {name}", "list": f"14 {abbr}, 21 {abbr}", "Month": name}


def _normalize_dates(value: str, today: date) -> str:
    """Turn 'november', '1 Nov to 15 Nov' or 'weekends in nov' into the strict syntax."""
    text = re.sub(r"\s+", " ", value.casefold().strip().rstrip("?.!")).strip()
    if m := MONTH_ONLY_RE.match(text):
        start, end = _month_bounds(MONTHS[m.group(1)], m.group(2), today)
        return f"{start.isoformat()}..{end.isoformat()}"
    if text in {"any", "anytime", "any time", "any date", "whenever possible"}:
        text = f"next {tft_slots.MAX_RANGE_DAYS} days"
    if m := re.fullmatch(r"(?:the )?next (?:(\d{1,2}|a|one|two) )?(day|week)s?", text):
        n = {"a": 1, "one": 1, "two": 2, None: 1}.get(m.group(1)) or int(m.group(1))
        days = n * (7 if m.group(2) == "week" else 1)
        return f"{today.isoformat()}..{(today + timedelta(days=days - 1)).isoformat()}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{4}-\d{2}-\d{2}", text):
        text = text.replace(" ", "..")
    if text in {"this weekend", "next weekend"}:
        # Saturday of the current weekend (today's, if it is already the weekend).
        saturday = today - timedelta(days=1) if today.weekday() == 6 else today + timedelta(days=(5 - today.weekday()) % 7)
        if text == "next weekend":
            saturday += timedelta(days=7)
        days = [d for d in (saturday, saturday + timedelta(days=1)) if d >= today]
        return ", ".join(d.isoformat() for d in days)
    if m := EVERY_RE.match(text):
        kind, month, year = m.group(1), m.group(2), m.group(3)
        start, end = _month_bounds(MONTHS[month], year, today) if month else (today, today + timedelta(days=29))
        wanted = {5, 6} if kind == "weekend" else {WEEKDAYS[kind]}
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return ", ".join(d.isoformat() for d in days if d.weekday() in wanted)
    for sep in (" to ", " until ", " till ", "..", " - ", "–", "—"):
        if sep in text:
            left, right = text.split(sep, 1)
            a, b = _one_date(left, today), _one_date(right, today)
            if a is None and left.strip().isdigit() and (m := DAY_MONTH_RE.match(right.strip())):
                a = _next_date(int(left), MONTHS[m.group(2)], m.group(3), today)
            if a and b:
                return f"{a.isoformat()}..{b.isoformat()}"
            return value
    parts = [part for part in re.split(r",| and ", text) if part.strip()]
    dates = [_one_date(part, today) for part in parts]
    if dates and all(dates):
        return ", ".join(d.isoformat() for d in dates)
    return value


def _parse_dates(value: str, today: date) -> tuple[str, str, list[str]] | None:
    value = _normalize_dates(value, today)
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


def _day(value: str) -> str:
    return date.fromisoformat(value).strftime("%a %d %b")


def _summary(row: sqlite3.Row | dict[str, Any]) -> str:
    dates = json.loads(row["dates"] or "[]")
    date_label = ", ".join(_day(d) for d in dates) if dates else (
        _day(row["date_start"])
        if row["date_start"] == row["date_end"]
        else f"{_day(row['date_start'])} to {_day(row['date_end'])}"
    )
    # Table for Two covers two diners; only mention party size when someone asked for more.
    party = f" · {row['party_size']} pax" if int(row["party_size"] or 2) != 2 else ""
    return f"{row['venue_name']} · {str(row['meal']).lower()}{party} · {date_label}"


PARTY_RE = re.compile(r"\s*\b(?:for\s+(\d{1,2})(?:\s*(?:pax|people|persons|diners))?|(\d{1,2})\s*(?:pax|people|persons|diners))\b", re.I)


def _venue_and_party(message: str) -> tuple[str, int | None]:
    """'Latido for 4' -> ('Latido', 4); plain venue names default to Table for Two's 2."""
    match = PARTY_RE.search(message)
    if not match:
        return message, 2
    party = int(match.group(1) or match.group(2))
    return (message[: match.start()] + message[match.end():]).strip(), party if 1 <= party <= 10 else None


def _new_id(conn: sqlite3.Connection) -> str:
    for _attempt in range(10):
        reminder_id = "R" + secrets.token_hex(3).upper()
        if conn.execute(
            "SELECT 1 FROM telegram_reminders WHERE id = ?", (reminder_id,)
        ).fetchone() is None:
            return reminder_id
    raise RuntimeError("could not allocate reminder id")


PRIVACY_LINE = "If you confirm, I will store this private chat ID until the reminder ends; /delete_me removes it."
VENUE_PROMPT = (
    "New reminder. Which venue? Send its name, e.g. Colony (add 'for 4' if you're bringing paying guests). "
    "/venues lists them all, /cancel stops."
)
VENUE_REPROMPT = "I need one exact Table for Two venue. Use /venues, then reply with its name, or /cancel."
PARTY_REPROMPT = "Party size must be 1 to 10. Send the venue again, e.g. Colony for 4, or /cancel."


def _dates_prompt(today: date) -> str:
    ex = date_examples(today)
    return (
        f"Which date(s)? For example: {ex['month']}, {ex['day']}, {ex['range']}, "
        f"{ex['weekends']}, or {ex['list']}. Up to {tft_slots.MAX_RANGE_DAYS} days, or up to 10 separate dates."
    )


def _dates_reprompt(today: date) -> str:
    ex = date_examples(today)
    return (
        f"I couldn't read those dates. Try: {ex['month']}, {ex['day']}, {ex['range']}, "
        f"or {ex['weekends']}. Dates must be in the future, up to {tft_slots.MAX_RANGE_DAYS} days, or up to 10 separate dates."
    )


def start_from_fields(
    conn: sqlite3.Connection,
    principal_key: str,
    catalog: dict,
    now: datetime,
    fields: dict[str, Any],
) -> str:
    """Pre-fill the /remind flow (venue, meal, dates; party defaults to 2) and prompt the first gap."""
    _purge(conn, now)
    conn.commit()
    if conn.execute(
        "SELECT 1 FROM telegram_reminder_conversations WHERE principal_key = ?",
        (principal_key,),
    ).fetchone():
        return "A reminder setup is already in progress. Send /remind to continue, or /cancel."
    today = now.astimezone(tft_slots.SGT).date()
    venue, party, meal, dates = (fields.get(key) for key in ("venue", "party", "meal", "dates"))
    known: dict[str, Any] = {}
    matches = tft_guide.resolve_venue(str(venue), catalog) if venue else []
    if len(matches) == 1:
        known.update(venue_id=matches[0]["id"], venue_name=matches[0]["name"])
    party_ok = party is None or (isinstance(party, int) and 1 <= party <= 10)
    if "venue_id" in known and party_ok:
        known["party_size"] = party or 2
    if isinstance(meal, str) and meal.casefold() in {"lunch", "dinner"}:
        known["meal"] = meal.casefold().title()
    parsed = _parse_dates(str(dates), today) if dates else None
    if parsed is not None:
        known.update(date_start=parsed[0], date_end=parsed[1], dates=json.dumps(parsed[2]))
    # A bad party size reopens the venue step, as typing "Colony for 12" does.
    state = next(
        (step for step, key in (("venue", "party_size"), ("meal", "meal"), ("dates", "date_start"))
         if key not in known),
        "confirm",
    )
    _save_conversation(conn, principal_key, state, now, created_ts=_iso(now), **known)
    if state == "confirm":
        draft = conn.execute(
            "SELECT * FROM telegram_reminder_conversations WHERE principal_key = ?",
            (principal_key,),
        ).fetchone()
        return _confirmation_prompt(draft)
    if state == "venue":
        prompt = PARTY_REPROMPT if not party_ok else VENUE_REPROMPT if venue else VENUE_PROMPT
    elif state == "meal":
        prompt = f"Reminder for {known['venue_name']}. Lunch or dinner?"
    else:
        prefix = f"Reminder for {known['venue_name']}, {known['meal'].lower()}. "
        prompt = prefix + (_dates_reprompt(today) if dates else _dates_prompt(today))
    return f"{prompt}\n{PRIVACY_LINE}"


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
            return "That venue isn't on the Table for Two list. Use /venues to see the list."
        venue = matches[0]
        _save_conversation(
            conn, principal_key, "meal", now,
            venue_id=venue["id"], venue_name=venue["name"], party_size=2,
        )
        return (
            f"Reminder for {venue['name']}. Lunch or dinner?\n"
            "If you confirm, I will store this private chat ID until the reminder ends; /delete_me removes it."
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
        return f"{VENUE_PROMPT}\n{PRIVACY_LINE}"

    if lowered == "/reminders":
        rows = conn.execute(
            "SELECT * FROM telegram_reminders WHERE principal_key = ? "
            "AND state = 'active' ORDER BY created_ts LIMIT ?",
            (principal_key, MAX_ACTIVE_REMINDERS),
        ).fetchall()
        if not rows:
            return "You have no active Table for Two reminders. Send /remind to create one."
        return "Your active Table for Two reminders:\n" + "\n".join(
            f"• {row['id']}: {_summary(row)}" for row in rows
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
        return "Delete your Telegram reminder data? This removes your reminders, any reminder you are setting up, your daily digest, your saved chat ID, delivery records, your recent conversation with the guide and rate-limit records. It does not affect email reminders. Reply DELETE within 15 minutes or /cancel."

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
            conn.execute(
                "DELETE FROM telegram_guide_context WHERE principal_key = ?",
                (principal_key,),
            )
            telegram_digest.forget(conn, principal_key)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return "Deleted. Email reminders were not changed. Telegram may retain chat messages under its own policy."

    if conversation is None:
        return "No reminder setup is active. Send /remind to begin."

    state = conversation["state"]
    if state == "venue":
        venue_text, party = _venue_and_party(message)
        if party is None:
            return PARTY_REPROMPT
        matches = tft_guide.resolve_venue(venue_text, catalog)
        if len(matches) != 1:
            return VENUE_REPROMPT
        venue = matches[0]
        _save_conversation(
            conn, principal_key, "meal", now,
            venue_id=venue["id"], venue_name=venue["name"], party_size=party,
        )
        return f"{venue['name']}. Lunch or dinner?"
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
        return _dates_prompt(now.astimezone(tft_slots.SGT).date())
    if state == "dates":
        parsed = _parse_dates(message, now.astimezone(tft_slots.SGT).date())
        if parsed is None:
            return _dates_reprompt(now.astimezone(tft_slots.SGT).date())
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
        return f"Reminder {reminder_id} is on: {_summary(draft)}\nChecking now, then every few minutes. /reminders lists yours, /cancel {reminder_id} stops it."
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
        checked = tft_slots.checked_label(selected[0]["checked_at"])
        by_day: dict[str, list[str]] = {}
        for item in matches:
            by_day.setdefault(item["date"], []).append(item["time"])
        lines = []
        for slot_date, times in list(by_day.items())[:MAX_NOTIFICATION_SLOTS]:
            span = tft_slots.clock(min(times))
            if len(times) > 1:
                span += f"–{tft_slots.clock(max(times))}"
            day = tft_slots._day(date.fromisoformat(slot_date))
            lines.append(f"• {day}: {span} ({len(times)} time{'s' if len(times) > 1 else ''})")
        if len(by_day) > MAX_NOTIFICATION_SLOTS:
            lines.append(f"• {len(by_day) - MAX_NOTIFICATION_SLOTS} more dates")
        first = next(iter(by_day))
        text = (
            f"🔔 {row['venue_name']} has {str(row['meal']).lower()} open\n"
            + "\n".join(lines)
            + f"\n\nTables go fast. Last checked {checked}. {tft_slots.SOURCE_NOTE}\n"
            f"{tft_guide.EXPLORER_PREFIX}{tft_guide.explorer_url(venue_id=row['venue_id'], party_size=row['party_size'], meal=row['meal'], date_value=first)}\n"
            f"Reminder {row['id']} is now closed. Send /remind to set another."
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
