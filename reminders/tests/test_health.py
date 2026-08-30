from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.config import load_settings
from app.main import app


def test_healthz_ok():
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_owner_alert_config_can_be_disabled(monkeypatch):
    monkeypatch.setenv("OWNER_ALERTS_ENABLED", "false")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert load_settings().owner_alerts_enabled is False


@pytest.mark.parametrize(
    "missing",
    [
        "OWNER_ALERT_INGEST_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_CHAT_ID",
        "OWNER_ALERT_NOT_BEFORE",
    ],
)
def test_owner_alert_config_fails_closed_when_enabled(monkeypatch, missing):
    values = {
        "OWNER_ALERTS_ENABLED": "true",
        "OWNER_ALERT_INGEST_TOKEN": "owner-alert-ingest-token-that-is-long-enough",
        "TELEGRAM_BOT_TOKEN": "123456789:abcdefghijklmnopqrstuvwxyz",
        "TELEGRAM_OWNER_CHAT_ID": "-1009876543210",
        "OWNER_ALERT_NOT_BEFORE": "2026-08-30T00:00:00Z",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match="Owner alert configuration is incomplete"):
        load_settings()


def test_owner_alert_config_rejects_naive_activation_time(monkeypatch):
    monkeypatch.setenv("OWNER_ALERTS_ENABLED", "true")
    monkeypatch.setenv(
        "OWNER_ALERT_INGEST_TOKEN", "owner-alert-ingest-token-that-is-long-enough"
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "-1009876543210")
    monkeypatch.setenv("OWNER_ALERT_NOT_BEFORE", "2026-08-30T00:00:00")

    with pytest.raises(RuntimeError, match="must include a timezone"):
        load_settings()


def test_owner_alert_config_rejects_public_example_ingest_token(monkeypatch):
    monkeypatch.setenv("OWNER_ALERTS_ENABLED", "true")
    monkeypatch.setenv(
        "OWNER_ALERT_INGEST_TOKEN", "REPLACE_ME_WITH_URLSAFE_RANDOM_43_PLUS_CHARS"
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "-1009876543210")
    monkeypatch.setenv("OWNER_ALERT_NOT_BEFORE", "2026-08-30T00:00:00Z")

    with pytest.raises(RuntimeError, match=r"43\+ random URL-safe characters"):
        load_settings()
