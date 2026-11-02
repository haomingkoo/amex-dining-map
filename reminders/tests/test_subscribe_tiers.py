from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app import db
from tests.test_api import _body, _token, client  # noqa: F401  (fixture)


EXPORT = {"Authorization": "Bearer export-secret"}


def _confirm(client):
    client.post(f"/api/confirm?token={_token(client.db_path, 'confirm_token')}")


def test_centurion_signup_accepts_centurion_venues_and_exports_the_card(client):
    response = client.post(
        "/api/subscribe", json=_body(tier="centurion", venues=["JAAN By Kirk Westaway"])
    )
    assert response.status_code == 200
    _confirm(client)
    subs = client.get("/api/subscribers", headers=EXPORT).json()["subscriptions"]
    assert [(s["tier"], s["venues"]) for s in subs] == [("centurion", ["JAAN By Kirk Westaway"])]


def test_platinum_signup_rejects_a_centurion_only_venue(client):
    response = client.post("/api/subscribe", json=_body(venues=["JAAN By Kirk Westaway"]))
    assert response.status_code == 422


def test_signup_without_a_card_is_platinum(client):
    client.post("/api/subscribe", json=_body())
    _confirm(client)
    subs = client.get("/api/subscribers", headers=EXPORT).json()["subscriptions"]
    assert subs[0]["tier"] == "platinum"


def test_changing_card_waits_for_confirmation(client):
    client.post("/api/subscribe", json=_body())
    _confirm(client)
    client.post("/api/subscribe", json=_body(tier="centurion", venues=["VUE"]))
    conn = db.connect(client.db_path)
    assert conn.execute("SELECT tier FROM subscribers").fetchone()[0] == "platinum"
    pending = conn.execute("SELECT confirm_token FROM pending_subscriber_changes").fetchone()[0]
    conn.close()
    client.post(f"/api/confirm?token={pending}")
    conn = db.connect(client.db_path)
    assert conn.execute("SELECT tier FROM subscribers").fetchone()[0] == "centurion"
    conn.close()


def test_manage_page_keeps_the_card_and_lists_its_venues(client):
    client.post("/api/subscribe", json=_body(tier="centurion", venues=["VUE"]))
    token = _token(client.db_path, "manage_token")
    page = client.get(f"/api/manage?token={token}").text
    assert "Centurion" in page and "JAAN By Kirk Westaway" in page
    updated = client.post(
        f"/api/manage?token={token}",
        json={
            "name": "Alice",
            "party_size": 2,
            "sessions": ["Lunch"],
            "venues": ["JAAN By Kirk Westaway"],
            "date_start": (date.today() + timedelta(days=5)).isoformat(),
            "date_end": (date.today() + timedelta(days=15)).isoformat(),
        },
    )
    assert updated.status_code == 200
    conn = db.connect(client.db_path)
    assert conn.execute("SELECT tier FROM subscribers").fetchone()[0] == "centurion"
    conn.close()


def test_existing_subscribers_migrate_to_platinum(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE subscribers (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL, name TEXT, party_size INTEGER NOT NULL,
          sessions TEXT NOT NULL, venues TEXT NOT NULL, date_start TEXT NOT NULL,
          date_end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', confirm_token TEXT,
          confirm_token_expires_ts TEXT, unsubscribe_token TEXT NOT NULL, source_ip TEXT,
          created_ts TEXT NOT NULL, confirmed_ts TEXT, unsubscribed_ts TEXT
        );
        INSERT INTO subscribers (email, party_size, sessions, venues, date_start, date_end,
          status, unsubscribe_token, created_ts)
        VALUES ('a@example.com', 2, '["Dinner"]', '["VUE"]', '2099-01-01', '2099-01-02',
          'active', 'tok', '2026-01-01T00:00:00+00:00');
        """
    )
    old.commit()
    old.close()
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert [row["tier"] for row in db.active_subscribers(conn)] == ["platinum"]
    finally:
        conn.close()
