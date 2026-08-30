from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, routes
from app.config import Settings
from app.main import app
from app.routes import get_settings


def _body(**overrides) -> dict:
    base = {
        "email": "guest@example.com",
        "name": "Alice",
        "party_size": 2,
        "sessions": ["Dinner"],
        "venues": ["15 Stamford Restaurant"],
        "date_start": (date.today() + timedelta(days=3)).isoformat(),
        "date_end": (date.today() + timedelta(days=20)).isoformat(),
    }
    base.update(overrides)
    return base


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "api.db"
    db.init_db(db_path)
    test_settings = Settings(
        db_path=db_path,
        resend_api_key="re_test",
        resend_from="dinnertime@kooexperience.com",
        alert_export_token="export-secret",
        allowed_origin="https://amex-explorer.kooexperience.com",
        public_base_url="https://svc",
        confirm_token_expiry_hours=168,
        table_data_url="http://example.invalid/data.json",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    sent: list = []
    monkeypatch.setattr(routes, "send_email", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(routes, "open_tables_exist", lambda *a, **k: False)

    test_client = TestClient(app)
    test_client.sent = sent  # type: ignore[attr-defined]
    test_client.db_path = db_path  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def _token(db_path: Path, column: str, email: str = "guest@example.com") -> str:
    conn = db.connect(db_path)
    try:
        return conn.execute(
            f"SELECT {column} FROM subscribers WHERE email = ?", (email,)
        ).fetchone()[column]
    finally:
        conn.close()


def test_subscribe_creates_pending_and_sends_one_email(client):
    response = client.post("/api/subscribe", json=_body())

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(client.sent) == 1
    conn = db.connect(client.db_path)
    assert conn.execute("SELECT status FROM subscribers").fetchone()["status"] == "pending"
    conn.close()


def test_honeypot_is_silent_noop(client):
    response = client.post("/api/subscribe", json=_body(website="http://spam.example"))

    assert response.status_code == 200
    assert client.sent == []
    conn = db.connect(client.db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM subscribers").fetchone()["n"] == 0
    conn.close()


def test_rate_limit_blocks_after_five(client):
    for _ in range(5):
        assert client.post("/api/subscribe", json=_body()).status_code == 200

    sixth = client.post("/api/subscribe", json=_body())

    assert sixth.status_code == 429


def test_confirm_activates_and_appears_in_export(client):
    client.post("/api/subscribe", json=_body())
    token = _token(client.db_path, "confirm_token")

    landing = client.get(f"/api/confirm?token={token}")
    assert landing.status_code == 200
    assert "Confirm reminders" in landing.text

    before = client.get(
        "/api/subscribers", headers={"Authorization": "Bearer export-secret"}
    )
    assert before.json()["subscriptions"] == []

    confirmed = client.post(f"/api/confirm?token={token}")
    assert confirmed.status_code == 200

    export = client.get(
        "/api/subscribers", headers={"Authorization": "Bearer export-secret"}
    )
    assert export.status_code == 200
    subs = export.json()["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["email"] == "guest@example.com"
    assert subs[0]["unsubscribe_url"].startswith("https://svc/api/unsubscribe?token=")


def test_export_requires_valid_token(client):
    assert client.get("/api/subscribers").status_code == 401
    assert (
        client.get(
            "/api/subscribers", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_manage_page_shows_subscription_and_updates(client):
    client.post("/api/subscribe", json=_body())
    token = _token(client.db_path, "manage_token")

    page = client.get(f"/api/manage?token={token}")
    assert page.status_code == 200
    assert "guest@example.com" in page.text

    updated = client.post(
        f"/api/manage?token={token}",
        json={
            "name": "Alice",
            "party_size": 4,
            "sessions": ["Lunch"],
            "venues": ["any"],
            "date_start": (date.today() + timedelta(days=5)).isoformat(),
            "date_end": (date.today() + timedelta(days=15)).isoformat(),
        },
    )
    assert updated.status_code == 200

    conn = db.connect(client.db_path)
    row = conn.execute("SELECT party_size, sessions FROM subscribers").fetchone()
    conn.close()
    assert row["party_size"] == 4


def test_manage_invalid_token_rejected(client):
    assert client.get("/api/manage?token=nope").status_code == 400
    assert client.post("/api/manage?token=nope", json={}).status_code == 400


def test_unsubscribe_removes_from_export(client):
    client.post("/api/subscribe", json=_body())
    confirm_token = _token(client.db_path, "confirm_token")
    client.post(f"/api/confirm?token={confirm_token}")
    unsub_token = _token(client.db_path, "unsubscribe_token")

    landing = client.get(f"/api/unsubscribe?token={unsub_token}")
    assert landing.status_code == 200
    still_active = client.get(
        "/api/subscribers", headers={"Authorization": "Bearer export-secret"}
    )
    assert len(still_active.json()["subscriptions"]) == 1

    unsubscribed = client.post(f"/api/unsubscribe?token={unsub_token}")
    assert unsubscribed.status_code == 200

    export = client.get(
        "/api/subscribers", headers={"Authorization": "Bearer export-secret"}
    )
    assert export.json()["subscriptions"] == []


def test_active_resubscribe_keeps_current_settings_until_confirmed(client):
    client.post("/api/subscribe", json=_body(party_size=2, sessions=["Dinner"]))
    client.post(f"/api/confirm?token={_token(client.db_path, 'confirm_token')}")

    client.post("/api/subscribe", json=_body(party_size=4, sessions=["Lunch"]))
    conn = db.connect(client.db_path)
    current = conn.execute(
        "SELECT status, party_size, sessions FROM subscribers WHERE email = ?",
        ("guest@example.com",),
    ).fetchone()
    pending = conn.execute(
        "SELECT confirm_token FROM pending_subscriber_changes WHERE email = ?",
        ("guest@example.com",),
    ).fetchone()
    conn.close()

    assert current["status"] == "active"
    assert current["party_size"] == 2
    assert current["sessions"] == '["Dinner"]'
    assert pending is not None

    client.post(f"/api/confirm?token={pending['confirm_token']}")
    conn = db.connect(client.db_path)
    changed = conn.execute(
        "SELECT status, party_size, sessions FROM subscribers WHERE email = ?",
        ("guest@example.com",),
    ).fetchone()
    conn.close()
    assert changed["status"] == "active"
    assert changed["party_size"] == 4
    assert changed["sessions"] == '["Lunch"]'


def test_forwarded_for_spoof_prefix_does_not_bypass_rate_limit(client):
    for index in range(5):
        response = client.post(
            "/api/subscribe",
            json=_body(email=f"guest{index}@example.com"),
            headers={"X-Forwarded-For": f"198.51.100.{index}, 203.0.113.10"},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/api/subscribe",
        json=_body(email="another@example.com"),
        headers={"X-Forwarded-For": "192.0.2.99, 203.0.113.10"},
    )
    assert blocked.status_code == 429


def test_api_security_headers_and_body_limit(client):
    response = client.get("/api/manage?token=invalid")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    oversized = client.post(
        "/api/subscribe",
        content=b"x" * 20_000,
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413


def test_openapi_is_not_public(client):
    assert client.get("/openapi.json").status_code == 404
