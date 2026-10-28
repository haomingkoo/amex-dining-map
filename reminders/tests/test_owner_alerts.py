from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import db, owner_alert_store
from app.config import Settings
from app.main import app
from app.owner_alert_routes import get_settings
from app.owner_alerts import OwnerAlertEvent


TOKEN = "owner-alert-ingest-token-that-is-long-enough"


def _settings(path: Path) -> Settings:
    return Settings(
        db_path=path,
        resend_api_key="",
        resend_from="test@example.com",
        alert_export_token="test-export-token",
        allowed_origin="https://amex-explorer.kooexperience.com",
        public_base_url="http://testserver",
        confirm_token_expiry_hours=168,
        table_data_url="https://example.test/table-for-two.json",
        abuse_hash_salt="test-abuse-salt",
        owner_alerts_enabled=True,
        owner_alert_ingest_token=TOKEN,
        telegram_bot_token="123456789:abcdefghijklmnopqrstuvwxyz",
        telegram_owner_chat_id=-1009876543210,
        owner_alert_not_before=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def _event(status: str = "published", event_id: str = "event-12345678") -> dict:
    return {
        "id": event_id,
        "program": "Plat Stay",
        "program_id": "plat-stay",
        "route": "#/stays",
        "kind": "added",
        "subject": "Mandai Rainforest Resort by Banyan Tree",
        "detected_at": "2026-08-30T00:00:00Z",
        "status": status,
        "before": {"state": "not_listed", "fields": {}},
        "after": {
            "state": "available",
            "fields": {"Name": "Mandai Rainforest Resort by Banyan Tree"},
        },
        "changes": [
            {"field": "Listing", "before": "Not listed", "after": "Listed"}
        ],
        "source_url": "https://www.americanexpress.com/en-sg/benefits/plat-stay/",
    }


@pytest.fixture()
def owner_client(tmp_path: Path):
    settings = _settings(tmp_path / "alerts.db")
    db.init_db(settings.db_path)
    owner_alert_store.init_db(settings.db_path)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    app.dependency_overrides.clear()


def _post(client: TestClient, event: dict, token: str = TOKEN) -> str:
    response = client.post(
        "/api/owner-alerts/batch",
        json={"events": [event]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()["results"][0]["state"]


def test_review_required_does_not_send_or_consume_event_id(owner_client, monkeypatch):
    client, settings = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 78,
    )

    assert _post(client, _event("review_required")) == "withheld"
    assert _post(client, _event("published")) == "sent"
    assert len(calls) == 1
    conn = db.connect(settings.db_path)
    try:
        assert owner_alert_store.get(
            conn, "event-12345678", settings.telegram_owner_chat_id
        )["state"] == "sent"
    finally:
        conn.close()


def test_validation_rejects_unsafe_source_and_extra_destination():
    unsafe = _event()
    unsafe["source_url"] = "javascript:alert(1)"
    unsafe["chat_id"] = -1001111111111

    with pytest.raises(ValidationError):
        OwnerAlertEvent.model_validate(unsafe)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://www.google.com/maps/place/example",
        "https://tabelog.com/tokyo/A1301/A130101/12345678/",
    ],
)
def test_source_health_accepts_reviewed_rating_hosts(source_url):
    event = _event()
    event.update(
        kind="source_health",
        subject="Ratings source health",
        source_url=source_url,
    )

    assert OwnerAlertEvent.model_validate(event).source_url == source_url


@pytest.mark.parametrize(
    "mutate",
    [
        lambda event: event.__setitem__(
            "subject", "Venue\nSource: https://evil.example"
        ),
        lambda event: event["changes"][0].__setitem__(
            "field", "Listing\nSource: https://evil.example"
        ),
    ],
)
def test_validation_rejects_alert_line_spoofing(mutate):
    event = _event()
    mutate(event)

    with pytest.raises(ValidationError):
        OwnerAlertEvent.model_validate(event)


def test_activation_cutoff_blocks_history_but_allows_later_review(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 81,
    )
    historical = _event()
    historical["detected_at"] = "2026-07-01T00:00:00Z"

    assert _post(client, historical) == "before_activation"
    historical["reviewed_at"] = "2026-08-30T00:00:00Z"
    assert _post(client, historical) == "sent"
    assert len(calls) == 1


def test_channel_rotation_has_independent_delivery_key(owner_client, monkeypatch):
    client, settings = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or len(calls),
    )
    assert _post(client, _event()) == "sent"
    rotated = Settings(
        **{
            **settings.__dict__,
            "telegram_owner_chat_id": -1009876543211,
        }
    )
    app.dependency_overrides[get_settings] = lambda: rotated

    assert _post(client, _event()) == "sent"
    assert [call[1] for call in calls] == [-1009876543210, -1009876543211]


def test_stale_sending_lease_becomes_unknown_without_restart(tmp_path: Path):
    path = tmp_path / "stale.db"
    owner_alert_store.init_db(path)
    conn = db.connect(path)
    chat_id = -1009876543210
    try:
        owner_alert_store.claim(conn, "event-stale-1234", chat_id, "a" * 64)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn.execute(
            "UPDATE owner_alert_deliveries SET updated_ts = ? WHERE event_id = ?",
            (old, "event-stale-1234"),
        )
        conn.commit()
        claim = owner_alert_store.claim(conn, "event-stale-1234", chat_id, "a" * 64)
    finally:
        conn.close()
    assert claim.state == "unknown"
    assert claim.should_send is False

