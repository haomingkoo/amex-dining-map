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

    confirmed = client.get(f"/api/confirm?token={token}")
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
    token = _token(client.db_path, "unsubscribe_token")

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
    client.get(f"/api/confirm?token={confirm_token}")
    unsub_token = _token(client.db_path, "unsubscribe_token")

    unsubscribed = client.get(f"/api/unsubscribe?token={unsub_token}")
    assert unsubscribed.status_code == 200

    export = client.get(
        "/api/subscribers", headers={"Authorization": "Bearer export-secret"}
    )
    assert export.json()["subscriptions"] == []
