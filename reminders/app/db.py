"""SQLite storage for reminder subscriptions (stdlib sqlite3, no ORM)."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from dataclasses import dataclass, field
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
  dates TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  confirm_token TEXT,
  confirm_token_expires_ts TEXT,
  unsubscribe_token TEXT NOT NULL,
  manage_token TEXT NOT NULL,
  source_ip TEXT,
  created_ts TEXT NOT NULL,
  confirmed_ts TEXT,
  unsubscribed_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers(status);
CREATE INDEX IF NOT EXISTS idx_subscribers_confirm_token ON subscribers(confirm_token);
CREATE INDEX IF NOT EXISTS idx_subscribers_unsub_token ON subscribers(unsubscribe_token);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_email_unique ON subscribers(email);

CREATE TABLE IF NOT EXISTS pending_subscriber_changes (
  email TEXT PRIMARY KEY,
  name TEXT,
  party_size INTEGER NOT NULL,
  sessions TEXT NOT NULL,
  venues TEXT NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT NOT NULL,
  dates TEXT NOT NULL DEFAULT '[]',
  confirm_token TEXT NOT NULL UNIQUE,
  confirm_token_expires_ts TEXT NOT NULL,
  source_ip TEXT,
  created_ts TEXT NOT NULL,
  FOREIGN KEY(email) REFERENCES subscribers(email) ON DELETE CASCADE
);

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
    dates: list[str] = field(default_factory=list)


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
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        os.chmod(path, 0o600)
    return conn


def init_db(path: Path | str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(subscribers)").fetchall()
        }
        if "dates" not in columns:  # migrate older DBs created before specific dates
            conn.execute(
                "ALTER TABLE subscribers ADD COLUMN dates TEXT NOT NULL DEFAULT '[]'"
            )
        if "manage_token" not in columns:
            conn.execute("ALTER TABLE subscribers ADD COLUMN manage_token TEXT")
        for row in conn.execute(
            "SELECT id, unsubscribe_token FROM subscribers "
            "WHERE manage_token IS NULL OR manage_token = ''"
        ).fetchall():
            conn.execute(
                "UPDATE subscribers SET manage_token = ? WHERE id = ?",
                (row["unsubscribe_token"], row["id"]),
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_manage_token "
            "ON subscribers(manage_token)"
        )
        purge_expired_records(conn)
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
    dates = json.dumps(sub.dates)
    existing = conn.execute(
        "SELECT id, status FROM subscribers WHERE email = ?", (sub.email,)
    ).fetchone()
    if existing and existing["status"] == "active":
        conn.execute(
            """
            INSERT INTO pending_subscriber_changes (
                email, name, party_size, sessions, venues, date_start, date_end,
                dates, confirm_token, confirm_token_expires_ts, source_ip, created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name = excluded.name,
                party_size = excluded.party_size,
                sessions = excluded.sessions,
                venues = excluded.venues,
                date_start = excluded.date_start,
                date_end = excluded.date_end,
                dates = excluded.dates,
                confirm_token = excluded.confirm_token,
                confirm_token_expires_ts = excluded.confirm_token_expires_ts,
                source_ip = excluded.source_ip,
                created_ts = excluded.created_ts
            """,
            (
                sub.email, sub.name, sub.party_size, sessions, venues,
                sub.date_start, sub.date_end, dates, confirm_token,
                confirm_expires, ip, now_iso,
            ),
        )
        conn.commit()
        return confirm_token
    if existing:
        conn.execute(
            """
            UPDATE subscribers
            SET name = ?, party_size = ?, sessions = ?, venues = ?,
                date_start = ?, date_end = ?, dates = ?, status = 'pending',
                confirm_token = ?, confirm_token_expires_ts = ?, source_ip = ?,
                created_ts = ?, confirmed_ts = NULL, unsubscribed_ts = NULL
            WHERE id = ?
            """,
            (
                sub.name, sub.party_size, sessions, venues, sub.date_start,
                sub.date_end, dates, confirm_token, confirm_expires, ip, now_iso,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO subscribers (
                email, name, party_size, sessions, venues, date_start, date_end,
                dates, status, confirm_token, confirm_token_expires_ts,
                unsubscribe_token, manage_token, source_ip, created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                sub.email, sub.name, sub.party_size, sessions, venues,
                sub.date_start, sub.date_end, dates, confirm_token, confirm_expires,
                new_token(), new_token(), ip, now_iso,
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
    if row:
        if _is_expired(row["confirm_token_expires_ts"]):
            return False
        conn.execute(
            "UPDATE subscribers SET status = 'active', confirmed_ts = ?, "
            "confirm_token = NULL, source_ip = NULL WHERE id = ?",
            (_iso(_now()), row["id"]),
        )
        conn.commit()
        return True

    pending = conn.execute(
        "SELECT * FROM pending_subscriber_changes WHERE confirm_token = ?",
        (token,),
    ).fetchone()
    if not pending or _is_expired(pending["confirm_token_expires_ts"]):
        return False
    conn.execute(
        """
        UPDATE subscribers
        SET name = ?, party_size = ?, sessions = ?, venues = ?, date_start = ?,
            date_end = ?, dates = ?, status = 'active', confirmed_ts = ?
        WHERE email = ? AND status = 'active'
        """,
        (
            pending["name"], pending["party_size"], pending["sessions"],
            pending["venues"], pending["date_start"], pending["date_end"],
            pending["dates"], _iso(_now()), pending["email"],
        ),
    )
    conn.execute(
        "DELETE FROM pending_subscriber_changes WHERE email = ?",
        (pending["email"],),
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
    if cur.rowcount > 0:
        conn.execute(
            "DELETE FROM pending_subscriber_changes WHERE email IN "
            "(SELECT email FROM subscribers WHERE unsubscribe_token = ?)",
            (token,),
        )
        conn.commit()
    return cur.rowcount > 0


def active_subscribers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT email, name, party_size, sessions, venues, date_start, date_end,
               dates, unsubscribe_token
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
            "dates": json.loads(row["dates"]),
            "unsubscribe_token": row["unsubscribe_token"],
        }
        for row in rows
    ]


def get_by_manage_token(conn: sqlite3.Connection, token: str) -> dict | None:
    """Look up a subscriber by their dedicated secret management token."""
    if not token:
        return None
    row = conn.execute(
        """
        SELECT email, name, party_size, sessions, venues, date_start, date_end,
               dates, status
        FROM subscribers WHERE manage_token = ?
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
        "dates": json.loads(row["dates"]),
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
            date_start = ?, date_end = ?, dates = ?
        WHERE manage_token = ? AND status != 'unsubscribed'
        """,
        (
            sub.name, sub.party_size, json.dumps(sub.sessions), json.dumps(sub.venues),
            sub.date_start, sub.date_end, json.dumps(sub.dates), token,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def purge_expired_records(
    conn: sqlite3.Connection,
    *,
    unsubscribed_retention_days: int = 30,
    event_retention_hours: int = 24,
) -> None:
    now = _now()
    conn.execute(
        "DELETE FROM pending_subscriber_changes WHERE confirm_token_expires_ts < ?",
        (_iso(now),),
    )
    conn.execute(
        "DELETE FROM subscribers WHERE status = 'pending' "
        "AND confirm_token_expires_ts IS NOT NULL AND confirm_token_expires_ts < ?",
        (_iso(now),),
    )
    conn.execute(
        "DELETE FROM subscribers WHERE status = 'unsubscribed' "
        "AND unsubscribed_ts IS NOT NULL AND unsubscribed_ts < ?",
        (_iso(now - timedelta(days=unsubscribed_retention_days)),),
    )
    conn.execute(
        "DELETE FROM subscribe_events WHERE created_ts < ?",
        (_iso(now - timedelta(hours=event_retention_hours)),),
    )


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


def consume_rate_limits(
    conn: sqlite3.Connection,
    limits: list[tuple[str, str, int]],
    within_minutes: int,
    retention_hours: int = 24,
) -> bool:
    """Atomically consume one event for every limit key, or none when blocked."""
    now = _now()
    cutoff = _iso(now - timedelta(minutes=within_minutes))
    retention_cutoff = _iso(now - timedelta(hours=retention_hours))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "DELETE FROM subscribe_events WHERE created_ts < ?",
            (retention_cutoff,),
        )
        for source_key, event_type, maximum in limits:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM subscribe_events "
                "WHERE source_ip = ? AND event_type = ? AND created_ts >= ?",
                (source_key, event_type, cutoff),
            ).fetchone()
            if int(row["n"]) >= maximum:
                conn.rollback()
                return False
        now_iso = _iso(now)
        conn.executemany(
            "INSERT INTO subscribe_events (source_ip, event_type, created_ts) "
            "VALUES (?, ?, ?)",
            [(source_key, event_type, now_iso) for source_key, event_type, _ in limits],
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
