"""Replay and abuse metadata for the public Telegram guide webhook."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db


SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_webhook_updates (
  bot_scope TEXT NOT NULL,
  update_id INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('processing', 'done', 'ignored', 'unknown', 'dead')),
  outcome_code TEXT,
  response_message_id INTEGER,
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  PRIMARY KEY(bot_scope, update_id)
);
CREATE TABLE IF NOT EXISTS telegram_rate_events (
  id INTEGER PRIMARY KEY,
  scope_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  created_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telegram_rate_scope_ts
ON telegram_rate_events(scope_key, event_type, created_ts);
"""


@dataclass(frozen=True)
class UpdateClaim:
    should_process: bool
    state: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat()


def init_db(path: Path | str) -> None:
    conn = db.connect(path)
    try:
        conn.executescript(SCHEMA)
        purge(conn)
        conn.commit()
    finally:
        conn.close()


def identity_key(kind: str, numeric_id: int, salt: str) -> str:
    digest = hmac.new(
        salt.encode(), f"{kind}:{numeric_id}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{kind}:{digest}"


def purge(conn: sqlite3.Connection) -> None:
    now = _now()
    conn.execute(
        "DELETE FROM telegram_rate_events WHERE created_ts < ?",
        (_iso(now - timedelta(hours=24)),),
    )
    conn.execute(
        "DELETE FROM telegram_webhook_updates WHERE updated_ts < ?",
        (_iso(now - timedelta(days=7)),),
    )


def claim_update(conn: sqlite3.Connection, bot_scope: str, update_id: int) -> UpdateClaim:
    now = _iso()
    stale_before = _iso(_now() - timedelta(minutes=5))
    purge(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT state, updated_ts FROM telegram_webhook_updates "
            "WHERE bot_scope = ? AND update_id = ?",
            (bot_scope, update_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO telegram_webhook_updates "
                "(bot_scope, update_id, state, created_ts, updated_ts) "
                "VALUES (?, ?, 'processing', ?, ?)",
                (bot_scope, update_id, now, now),
            )
            conn.commit()
            return UpdateClaim(True, "processing")
        if row["state"] == "processing" and row["updated_ts"] < stale_before:
            conn.execute(
                "UPDATE telegram_webhook_updates SET state = 'unknown', "
                "outcome_code = 'stale_processing', updated_ts = ? "
                "WHERE bot_scope = ? AND update_id = ? AND state = 'processing'",
                (now, bot_scope, update_id),
            )
            conn.commit()
            return UpdateClaim(False, "unknown")
        conn.commit()
        return UpdateClaim(False, str(row["state"]))
    except Exception:
        conn.rollback()
        raise


def complete_update(
    conn: sqlite3.Connection,
    bot_scope: str,
    update_id: int,
    state: str,
    outcome_code: str,
    message_id: int | None = None,
) -> None:
    if state not in {"done", "ignored", "unknown", "dead"}:
        raise ValueError("invalid Telegram update state")
    conn.execute(
        "UPDATE telegram_webhook_updates SET state = ?, outcome_code = ?, "
        "response_message_id = ?, updated_ts = ? WHERE bot_scope = ? "
        "AND update_id = ? AND state = 'processing'",
        (state, outcome_code, message_id, _iso(), bot_scope, update_id),
    )
    conn.commit()


def discard_update(conn: sqlite3.Connection, bot_scope: str, update_id: int) -> None:
    conn.execute(
        "DELETE FROM telegram_webhook_updates WHERE bot_scope = ? "
        "AND update_id = ? AND state = 'processing'",
        (bot_scope, update_id),
    )
    conn.commit()


def consume_limits(
    conn: sqlite3.Connection,
    policies: list[tuple[str, int, int]],
    event_type: str = "guide",
) -> bool:
    if event_type not in {"guide", "management"}:
        raise ValueError("invalid Telegram rate event type")
    now = _now()
    purge(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for key, maximum, within_minutes in policies:
            cutoff = _iso(now - timedelta(minutes=within_minutes))
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM telegram_rate_events "
                "WHERE scope_key = ? AND event_type = ? AND created_ts >= ?",
                (key, event_type, cutoff),
            ).fetchone()["n"]
            if int(count) >= maximum:
                conn.rollback()
                return False
        unique_keys = sorted({key for key, _maximum, _minutes in policies})
        conn.executemany(
            "INSERT INTO telegram_rate_events (scope_key, event_type, created_ts) "
            "VALUES (?, ?, ?)",
            [(key, event_type, _iso(now)) for key in unique_keys],
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
