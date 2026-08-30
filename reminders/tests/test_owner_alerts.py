from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

import pytest
from fastapi.testclient import TestClient

from app import db, owner_alert_store
from app.config import Settings
from app.main import app
from app.owner_alert_routes import get_settings
from app.owner_alerts import OwnerAlertEvent, format_owner_alert
from app.telegram import TelegramDeliveryError


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


def _post(client: TestClient, event: dict, token: str = TOKEN):
    return client.post(
        "/api/owner-alerts/events",
        json={"event": event},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_published_event_sends_once_and_replay_is_deduplicated(
    owner_client, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = owner_client
    calls = []

    def fake_send(bot_token, chat_id, text):
        calls.append((bot_token, chat_id, text))
        return 77

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", fake_send)

    first = _post(client, _event())
    replay = _post(client, _event())

    assert first.status_code == 200
    assert first.json()["state"] == "sent"
    assert replay.status_code == 200
    assert replay.json()["state"] == "sent"
    assert len(calls) == 1
    assert calls[0][0] == settings.telegram_bot_token
    assert calls[0][1] == settings.telegram_owner_chat_id
    assert "Before: Not listed" in calls[0][2]
    assert "After: Listed" in calls[0][2]
    assert str(settings.telegram_owner_chat_id) not in first.text
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"state":"sent"' in log_text
    for secret in (
        settings.telegram_bot_token,
        str(settings.telegram_owner_chat_id),
        "event-12345678",
        "Mandai Rainforest Resort by Banyan Tree",
    ):
        assert secret not in log_text


def test_review_required_does_not_send_or_consume_event_id(owner_client, monkeypatch):
    client, settings = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 78,
    )

    withheld = _post(client, _event("review_required"))
    published = _post(client, _event("published"))

    assert withheld.json() == {
        "ok": True, "id": "event-12345678", "state": "withheld"
    }
    assert published.json()["state"] == "sent"
    assert len(calls) == 1
    conn = db.connect(settings.db_path)
    try:
        assert owner_alert_store.get(
            conn, "event-12345678", settings.telegram_owner_chat_id
        )["state"] == "sent"
    finally:
        conn.close()


def test_invalid_auth_has_no_delivery_side_effect(owner_client, monkeypatch):
    client, settings = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    response = _post(client, _event(), token="wrong")

    assert response.status_code == 401
    assert calls == []
    conn = db.connect(settings.db_path)
    try:
        assert owner_alert_store.get(
            conn, "event-12345678", settings.telegram_owner_chat_id
        ) is None
    finally:
        conn.close()


def test_authentication_precedes_payload_validation(owner_client):
    client, _settings_value = owner_client

    unauthorized = client.post(
        "/api/owner-alerts/events",
        content=b"not-json",
        headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"},
    )
    authorized = client.post(
        "/api/owner-alerts/events",
        content=b"not-json",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Unauthorized"}
    assert authorized.status_code == 422
    assert authorized.json() == {"detail": "Invalid owner alert payload."}


def test_disabled_owner_ingress_precedes_payload_validation(tmp_path: Path):
    settings = _settings(tmp_path / "disabled.db")
    settings = replace(settings, owner_alerts_enabled=False)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/owner-alerts/events",
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Owner alerts are not enabled."}


def test_same_id_with_changed_payload_fails_closed(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 80,
    )
    assert _post(client, _event()).status_code == 200
    changed = _event()
    changed["changes"][0]["after"] = "Different listing"

    response = _post(client, changed)

    assert response.status_code == 409
    assert len(calls) == 1


def test_ambiguous_transport_is_not_blindly_retried(owner_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = owner_client
    calls = []

    def fail_unknown(*args):
        calls.append(args)
        raise TelegramDeliveryError("telegram_transport_unknown", "unknown")

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", fail_unknown)

    first = _post(client, _event())
    replay = _post(client, _event())

    assert first.json()["state"] == "unknown"
    assert replay.json()["state"] == "unknown"
    assert len(calls) == 1
    assert settings.telegram_bot_token not in first.text
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"state":"unknown"' in log_text
    assert "event-12345678" not in log_text


def test_validation_rejects_unsafe_source_and_extra_destination(owner_client):
    client, _settings_value = owner_client
    unsafe = _event()
    unsafe["source_url"] = "javascript:alert(1)"
    unsafe["chat_id"] = -1001111111111

    response = _post(client, unsafe)

    assert response.status_code == 422


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
def test_validation_rejects_alert_line_spoofing(owner_client, mutate):
    client, _settings_value = owner_client
    event = _event()
    mutate(event)

    assert _post(client, event).status_code == 422


def test_activation_cutoff_blocks_history_but_allows_later_review(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 81,
    )
    historical = _event()
    historical["detected_at"] = "2026-07-01T00:00:00Z"

    before_activation = _post(client, historical)
    historical["reviewed_at"] = "2026-08-30T00:00:00Z"
    approved_later = _post(client, historical)

    assert before_activation.json()["state"] == "before_activation"
    assert approved_later.json()["state"] == "sent"
    assert len(calls) == 1


def test_definite_retry_is_sent_on_later_replay(owner_client, monkeypatch):
    client, _settings_value = owner_client
    outcomes = [TelegramDeliveryError("telegram_http_503", "retry"), 82]

    def retry_then_send(*_args):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", retry_then_send)

    first = _post(client, _event())
    replay = _post(client, _event())

    assert first.json()["state"] == "retry"
    assert replay.json()["state"] == "sent"
    assert replay.json()["attempt"] == 2


def test_channel_rotation_has_independent_delivery_key(owner_client, monkeypatch):
    client, settings = owner_client
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or len(calls),
    )
    assert _post(client, _event()).json()["state"] == "sent"
    rotated = Settings(
        **{
            **settings.__dict__,
            "telegram_owner_chat_id": -1009876543211,
        }
    )
    app.dependency_overrides[get_settings] = lambda: rotated

    assert _post(client, _event()).json()["state"] == "sent"
    assert [call[1] for call in calls] == [-1009876543210, -1009876543211]


def test_plain_text_formatter_bounds_and_preserves_before_after():
    raw = _event()
    raw["subject"] = "<b>not markup</b>"
    raw["changes"] = [
        {"field": f"Field {index}", "before": "b" * 500, "after": "a" * 500}
        for index in range(20)
    ]
    event = OwnerAlertEvent.model_validate(raw)

    message = format_owner_alert(event, "https://amex-explorer.kooexperience.com")

    assert "<b>not markup</b>" in message
    assert "After: " in message
    assert len(message) <= 3900
    assert "Detected: 2026-08-30 00:00 UTC" in message
    assert "Source: https://www.americanexpress.com/" in message
    assert "Explorer: https://amex-explorer.kooexperience.com/#/stays" in message


def test_offset_timestamp_is_rendered_as_utc():
    raw = _event()
    raw["detected_at"] = "2026-08-30T08:00:00+08:00"
    event = OwnerAlertEvent.model_validate(raw)
    message = format_owner_alert(event, "https://amex-explorer.kooexperience.com")
    assert "Detected: 2026-08-30 00:00 UTC" in message


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


def test_stale_sending_replay_emits_privacy_safe_unknown_log(
    owner_client, monkeypatch, caplog
):
    client, settings = owner_client
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    event = _event(event_id="event-stale-route-1234")
    parsed = OwnerAlertEvent.model_validate(event)
    conn = db.connect(settings.db_path)
    try:
        owner_alert_store.claim(
            conn,
            parsed.id,
            settings.telegram_owner_chat_id,
            parsed.digest(),
        )
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn.execute(
            "UPDATE owner_alert_deliveries SET updated_ts = ? WHERE event_id = ?",
            (old, parsed.id),
        )
        conn.commit()
    finally:
        conn.close()
    calls = []
    monkeypatch.setattr(
        "app.owner_alert_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    response = _post(client, event)
    assert response.json()["state"] == "unknown"
    assert calls == []
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"error_code":"stale_sending"' in log_text
    assert parsed.id not in log_text
    assert str(settings.telegram_owner_chat_id) not in log_text
