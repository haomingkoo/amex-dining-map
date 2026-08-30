"""SQLite idempotency and delivery-state store for private owner alerts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db


SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_alert_deliveries (
  event_id TEXT NOT NULL,
  destination_chat_id INTEGER NOT NULL,
  event_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('sending', 'retry', 'sent', 'unknown', 'dead')),
  attempt_count INTEGER NOT NULL DEFAULT 1,
  telegram_message_id INTEGER,
  error_code TEXT,
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  PRIMARY KEY(event_id, destination_chat_id)
);
CREATE INDEX IF NOT EXISTS idx_owner_alert_state ON owner_alert_deliveries(state, updated_ts);
"""


@dataclass(frozen=True)
class Claim:
    state: str
    attempt_count: int
    should_send: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat()


def init_db(path: Path | str) -> None:
    conn = db.connect(path)
    try:
        conn.executescript(SCHEMA)
        stale_before = _iso(_now() - timedelta(minutes=5))
        conn.execute(
            "UPDATE owner_alert_deliveries SET state = 'unknown', "
            "error_code = 'stale_sending', updated_ts = ? "
            "WHERE state = 'sending' AND updated_ts < ?",
            (_iso(), stale_before),
        )
        conn.commit()
    finally:
        conn.close()


def claim(
    conn: sqlite3.Connection, event_id: str, destination_chat_id: int, digest: str
) -> Claim:
    now = _iso()
    stale_before = _iso(_now() - timedelta(minutes=5))
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT event_digest, state, attempt_count, updated_ts "
            "FROM owner_alert_deliveries WHERE event_id = ? AND destination_chat_id = ?",
            (event_id, destination_chat_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO owner_alert_deliveries "
                "(event_id, destination_chat_id, event_digest, state, attempt_count, "
                "created_ts, updated_ts) VALUES (?, ?, ?, 'sending', 1, ?, ?)",
                (event_id, destination_chat_id, digest, now, now),
            )
            conn.commit()
            return Claim("sending", 1, True)
        if row["event_digest"] != digest:
            conn.rollback()
            return Claim("conflict", int(row["attempt_count"]), False)
        state = str(row["state"])
        attempts = int(row["attempt_count"])
        if state == "sending" and row["updated_ts"] < stale_before:
            conn.execute(
                "UPDATE owner_alert_deliveries SET state = 'unknown', "
                "error_code = 'stale_sending', updated_ts = ? "
                "WHERE event_id = ? AND destination_chat_id = ? AND state = 'sending'",
                (now, event_id, destination_chat_id),
            )
            conn.commit()
            return Claim("unknown", attempts, False)
        if state == "retry":
            attempts += 1
            conn.execute(
                "UPDATE owner_alert_deliveries SET state = 'sending', "
                "attempt_count = ?, error_code = NULL, updated_ts = ? "
                "WHERE event_id = ? AND destination_chat_id = ?",
                (attempts, now, event_id, destination_chat_id),
            )
            conn.commit()
            return Claim("sending", attempts, True)
        conn.commit()
        return Claim(state, attempts, False)
    except Exception:
        conn.rollback()
        raise


def complete(
    conn: sqlite3.Connection,
    event_id: str,
    destination_chat_id: int,
    state: str,
    *,
    message_id: int | None = None,
    error_code: str | None = None,
) -> None:
    if state not in {"retry", "sent", "unknown", "dead"}:
        raise ValueError("invalid owner alert state")
    conn.execute(
        "UPDATE owner_alert_deliveries SET state = ?, telegram_message_id = ?, "
        "error_code = ?, updated_ts = ? WHERE event_id = ? "
        "AND destination_chat_id = ? AND state = 'sending'",
        (state, message_id, error_code, _iso(), event_id, destination_chat_id),
    )
    conn.commit()


def get(
    conn: sqlite3.Connection, event_id: str, destination_chat_id: int
) -> dict | None:
    row = conn.execute(
        "SELECT event_id, state, attempt_count, telegram_message_id, error_code, "
        "created_ts, updated_ts FROM owner_alert_deliveries "
        "WHERE event_id = ? AND destination_chat_id = ?",
        (event_id, destination_chat_id),
    ).fetchone()
    return dict(row) if row else None
