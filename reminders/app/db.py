"""SQLite storage for reminder subscriptions (stdlib sqlite3, no ORM)."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT,
  party_size INTEGER NOT NULL,
  sessions TEXT NOT NULL,
  venues TEXT NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  confirm_token TEXT,
  confirm_token_expires_ts TEXT,
  unsubscribe_token TEXT NOT NULL,
  source_ip TEXT,
  created_ts TEXT NOT NULL,
  confirmed_ts TEXT,
  unsubscribed_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers(status);
CREATE INDEX IF NOT EXISTS idx_subscribers_confirm_token ON subscribers(confirm_token);
CREATE INDEX IF NOT EXISTS idx_subscribers_unsub_token ON subscribers(unsubscribe_token);

CREATE TABLE IF NOT EXISTS subscribe_events (
  id INTEGER PRIMARY KEY,
  source_ip TEXT,
  event_type TEXT NOT NULL,
  created_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ip_ts ON subscribe_events(source_ip, created_ts);
"""


@dataclass(frozen=True)
class SubscriberInput:
    email: str
    name: str | None
    party_size: int
    sessions: list[str]
    venues: list[str]
    date_start: str
    date_end: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def _is_expired(expires_ts: str | None) -> bool:
    if not expires_ts:
        return True
    return _now() > datetime.fromisoformat(expires_ts)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_pending(
    conn: sqlite3.Connection,
    sub: SubscriberInput,
    ip: str,
    expiry_hours: int = 168,
) -> str:
    """Insert or refresh a subscriber as pending; return the new confirm token.

    Re-subscribing an existing email replaces its preferences, resets it to
    pending, and issues a fresh confirm token (the unsubscribe token is kept).
    """
    now = _now()
    confirm_token = new_token()
    confirm_expires = _iso(now + timedelta(hours=expiry_hours))
    now_iso = _iso(now)
    sessions = json.dumps(sub.sessions)
    venues = json.dumps(sub.venues)
    existing = conn.execute(
        "SELECT id FROM subscribers WHERE email = ?", (sub.email,)
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE subscribers
            SET name = ?, party_size = ?, sessions = ?, venues = ?,
                date_start = ?, date_end = ?, status = 'pending',
                confirm_token = ?, confirm_token_expires_ts = ?, source_ip = ?,
                created_ts = ?, confirmed_ts = NULL, unsubscribed_ts = NULL
            WHERE id = ?
            """,
            (
                sub.name, sub.party_size, sessions, venues, sub.date_start,
                sub.date_end, confirm_token, confirm_expires, ip, now_iso,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO subscribers (
                email, name, party_size, sessions, venues, date_start, date_end,
                status, confirm_token, confirm_token_expires_ts, unsubscribe_token,
                source_ip, created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                sub.email, sub.name, sub.party_size, sessions, venues,
                sub.date_start, sub.date_end, confirm_token, confirm_expires,
                new_token(), ip, now_iso,
            ),
        )
    conn.commit()
    return confirm_token


def confirm(conn: sqlite3.Connection, token: str) -> bool:
    if not token:
        return False
    row = conn.execute(
        "SELECT id, confirm_token_expires_ts FROM subscribers WHERE confirm_token = ?",
        (token,),
    ).fetchone()
    if not row or _is_expired(row["confirm_token_expires_ts"]):
        return False
    conn.execute(
        "UPDATE subscribers SET status = 'active', confirmed_ts = ?, "
        "confirm_token = NULL WHERE id = ?",
        (_iso(_now()), row["id"]),
    )
    conn.commit()
    return True


def unsubscribe(conn: sqlite3.Connection, token: str) -> bool:
    if not token:
        return False
    cur = conn.execute(
        "UPDATE subscribers SET status = 'unsubscribed', unsubscribed_ts = ? "
        "WHERE unsubscribe_token = ?",
        (_iso(_now()), token),
    )
    conn.commit()
    return cur.rowcount > 0


def active_subscribers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT email, name, party_size, sessions, venues, date_start, date_end,
               unsubscribe_token
        FROM subscribers WHERE status = 'active' ORDER BY id
        """
    ).fetchall()
    return [
        {
            "email": row["email"],
            "name": row["name"],
            "party_size": row["party_size"],
            "sessions": json.loads(row["sessions"]),
            "venues": json.loads(row["venues"]),
            "date_start": row["date_start"],
            "date_end": row["date_end"],
            "unsubscribe_token": row["unsubscribe_token"],
        }
        for row in rows
    ]


def get_by_unsubscribe_token(conn: sqlite3.Connection, token: str) -> dict | None:
    """Look up a subscriber by their secret unsubscribe/manage token."""
    if not token:
        return None
    row = conn.execute(
        """
        SELECT email, name, party_size, sessions, venues, date_start, date_end, status
        FROM subscribers WHERE unsubscribe_token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return None
    return {
        "email": row["email"],
        "name": row["name"],
        "party_size": row["party_size"],
        "sessions": json.loads(row["sessions"]),
        "venues": json.loads(row["venues"]),
        "date_start": row["date_start"],
        "date_end": row["date_end"],
        "status": row["status"],
    }


def update_preferences(
    conn: sqlite3.Connection, token: str, sub: SubscriberInput
) -> bool:
    """Update an active/pending subscriber's preferences in place (email unchanged)."""
    if not token:
        return False
    cur = conn.execute(
        """
        UPDATE subscribers
        SET name = ?, party_size = ?, sessions = ?, venues = ?,
            date_start = ?, date_end = ?
        WHERE unsubscribe_token = ? AND status != 'unsubscribed'
        """,
        (
            sub.name, sub.party_size, json.dumps(sub.sessions), json.dumps(sub.venues),
            sub.date_start, sub.date_end, token,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def log_event(conn: sqlite3.Connection, ip: str, event_type: str) -> None:
    conn.execute(
        "INSERT INTO subscribe_events (source_ip, event_type, created_ts) "
        "VALUES (?, ?, ?)",
        (ip, event_type, _iso(_now())),
    )
    conn.commit()


def count_recent_events(
    conn: sqlite3.Connection, ip: str, event_type: str, within_minutes: int
) -> int:
    cutoff = _iso(_now() - timedelta(minutes=within_minutes))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM subscribe_events "
        "WHERE source_ip = ? AND event_type = ? AND created_ts >= ?",
        (ip, event_type, cutoff),
    ).fetchone()
    return int(row["n"])
