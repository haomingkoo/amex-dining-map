from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import db
from app.db import SubscriberInput


def _sub(email: str = "a@example.com") -> SubscriberInput:
    return SubscriberInput(
        email=email,
        name="Alice",
        party_size=2,
        sessions=["Dinner"],
        venues=["15 Stamford Restaurant"],
        date_start="2026-07-01",
        date_end="2026-07-10",
    )


@pytest.fixture()
def conn(tmp_path: Path):
    path = tmp_path / "test.db"
    db.init_db(path)
    connection = db.connect(path)
    yield connection
    connection.close()


def test_init_db_creates_tables(conn):
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert {"subscribers", "subscribe_events"} <= names


def test_upsert_pending_creates_pending_row(conn):
    token = db.upsert_pending(conn, _sub(), ip="1.2.3.4")

    row = conn.execute("SELECT status, confirm_token FROM subscribers").fetchone()
    assert token
    assert row["status"] == "pending"
    assert row["confirm_token"] == token


def test_upsert_same_email_replaces_and_keeps_unsub_token(conn):
    db.upsert_pending(conn, _sub(), ip="1.2.3.4")
    first_unsub = conn.execute(
        "SELECT unsubscribe_token FROM subscribers"
    ).fetchone()["unsubscribe_token"]

    db.upsert_pending(conn, _sub(), ip="1.2.3.4")

    rows = conn.execute("SELECT unsubscribe_token FROM subscribers").fetchall()
    assert len(rows) == 1
    assert rows[0]["unsubscribe_token"] == first_unsub


def test_confirm_activates_with_valid_token(conn):
    token = db.upsert_pending(conn, _sub(), ip="1.2.3.4")

    assert db.confirm(conn, token) is True
    row = conn.execute("SELECT status, confirm_token FROM subscribers").fetchone()
    assert row["status"] == "active"
    assert row["confirm_token"] is None


def test_confirm_rejects_invalid_and_expired_token(conn):
    assert db.confirm(conn, "nope") is False

    expired = db.upsert_pending(conn, _sub("b@example.com"), ip="1.2.3.4", expiry_hours=-1)
    assert db.confirm(conn, expired) is False


def test_unsubscribe_excludes_from_active(conn):
    token = db.upsert_pending(conn, _sub(), ip="1.2.3.4")
    db.confirm(conn, token)
    unsub = conn.execute(
        "SELECT unsubscribe_token FROM subscribers"
    ).fetchone()["unsubscribe_token"]

    assert db.unsubscribe(conn, unsub) is True
    assert db.active_subscribers(conn) == []


def test_active_subscribers_export_shape(conn):
    token = db.upsert_pending(conn, _sub(), ip="1.2.3.4")
    db.confirm(conn, token)

    active = db.active_subscribers(conn)
    assert len(active) == 1
    record = active[0]
    assert record["email"] == "a@example.com"
    assert record["sessions"] == ["Dinner"]
    assert record["venues"] == ["15 Stamford Restaurant"]
    assert record["party_size"] == 2
    assert "unsubscribe_token" in record


def test_get_by_unsubscribe_token(conn):
    db.upsert_pending(conn, _sub(), ip="1.2.3.4")
    token = conn.execute(
        "SELECT unsubscribe_token FROM subscribers"
    ).fetchone()["unsubscribe_token"]

    record = db.get_by_unsubscribe_token(conn, token)

    assert record is not None
    assert record["email"] == "a@example.com"
    assert record["status"] == "pending"
    assert db.get_by_unsubscribe_token(conn, "nope") is None


def test_update_preferences(conn):
    db.upsert_pending(conn, _sub(), ip="1.2.3.4")
    token = conn.execute(
        "SELECT unsubscribe_token FROM subscribers"
    ).fetchone()["unsubscribe_token"]

    changed = SubscriberInput(
        email="a@example.com",
        name="Alice",
        party_size=4,
        sessions=["Lunch"],
        venues=["any"],
        date_start="2026-08-01",
        date_end="2026-08-10",
    )
    assert db.update_preferences(conn, token, changed) is True

    record = db.get_by_unsubscribe_token(conn, token)
    assert record["party_size"] == 4
    assert record["sessions"] == ["Lunch"]


def test_init_db_migrates_missing_dates_column(tmp_path: Path):
    path = tmp_path / "old.db"
    conn = db.connect(path)
    conn.executescript(
        """
        CREATE TABLE subscribers (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL, name TEXT,
          party_size INTEGER NOT NULL, sessions TEXT NOT NULL, venues TEXT NOT NULL,
          date_start TEXT NOT NULL, date_end TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', confirm_token TEXT,
          confirm_token_expires_ts TEXT, unsubscribe_token TEXT NOT NULL,
          source_ip TEXT, created_ts TEXT NOT NULL, confirmed_ts TEXT,
          unsubscribed_ts TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO subscribers (email, party_size, sessions, venues, date_start, "
        "date_end, unsubscribe_token, created_ts) VALUES "
        "('x@e.com', 2, '[\"Dinner\"]', '[\"any\"]', '2026-07-01', '2026-07-10', "
        "'tok', '2026-06-24T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    db.init_db(path)  # must add the missing 'dates' column without losing data

    conn = db.connect(path)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(subscribers)").fetchall()
    }
    assert "dates" in columns
    row = conn.execute("SELECT dates FROM subscribers").fetchone()
    assert json.loads(row["dates"]) == []
    conn.close()


def test_specific_dates_round_trip(conn):
    sub = SubscriberInput(
        email="d@example.com",
        name="Dee",
        party_size=2,
        sessions=["Dinner"],
        venues=["any"],
        date_start="2026-07-04",
        date_end="2026-07-18",
        dates=["2026-07-04", "2026-07-18"],
    )
    token = db.upsert_pending(conn, sub, ip="1.2.3.4")
    db.confirm(conn, token)

    assert db.active_subscribers(conn)[0]["dates"] == ["2026-07-04", "2026-07-18"]


def test_event_count_window(conn):
    db.log_event(conn, "9.9.9.9", "subscribe_attempt")
    db.log_event(conn, "9.9.9.9", "subscribe_attempt")

    assert db.count_recent_events(conn, "9.9.9.9", "subscribe_attempt", 60) == 2
    assert db.count_recent_events(conn, "8.8.8.8", "subscribe_attempt", 60) == 0
