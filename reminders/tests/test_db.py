from __future__ import annotations

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


def test_event_count_window(conn):
    db.log_event(conn, "9.9.9.9", "subscribe_attempt")
    db.log_event(conn, "9.9.9.9", "subscribe_attempt")

    assert db.count_recent_events(conn, "9.9.9.9", "subscribe_attempt", 60) == 2
    assert db.count_recent_events(conn, "8.8.8.8", "subscribe_attempt", 60) == 0
