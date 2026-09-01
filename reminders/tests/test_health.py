from __future__ import annotations

import hashlib
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from app.config import load_settings
from app import tft_guide
from app.main import app, bundle_revision


def test_healthz_ok(monkeypatch):
    monkeypatch.delenv("RAILWAY_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["deployment_id"] == "local"
    assert re.fullmatch(r"bundle:[0-9a-f]{12}", payload["revision"])
    assert payload["revision"] == bundle_revision()
    assert payload["catalog_ok"] is True
    assert payload["catalog_sha256"] == hashlib.sha256(
        tft_guide.CATALOG_PATH.read_bytes()
    ).hexdigest()
    assert payload["catalog_schema_version"] == 4
    assert payload["catalog_release_project"] == "AMEXPlatSG"
    assert payload["catalog_slot_project"] == "AMEXPlatSG"
    assert payload["catalog_slot_stale_after_minutes"] == 30
    assert payload["catalog_release_updated_at"]
    assert payload["catalog_roster_checked_at"]
    assert payload["catalog_menu_checked_at"]
    assert payload["feature_state"] == {
        "email_delivery_configured": False,
        "owner_alerts_enabled": False,
        "telegram_guide_enabled": False,
        "telegram_reminders_enabled": False,
        "tft_live_refresh_enabled": False,
    }
    assert payload["tft_live"] == {
        "status": "unavailable",
        "generated_at": None,
        "age_seconds": None,
        "counts": None,
    }


def test_production_server_disables_query_string_access_logs():
    railway_config = (Path(__file__).parents[1] / "railway.toml").read_text()

    assert "--no-access-log" in railway_config


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


def test_telegram_guide_config_rejects_placeholder_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_GUIDE_ENABLED", "true")
    monkeypatch.setenv(
        "TELEGRAM_GUIDE_BOT_TOKEN",
        "987654321:separatepublicbotabcdefghijklmnopqrstuvwxyz",
    )
    monkeypatch.setenv(
        "TELEGRAM_GUIDE_WEBHOOK_SECRET",
        "REPLACE_ME_WITH_URLSAFE_RANDOM_43_PLUS_CHARS",
    )
    monkeypatch.setenv("TELEGRAM_IDENTITY_HASH_SALT", "s" * 43)

    with pytest.raises(RuntimeError, match="Telegram guide configuration is incomplete"):
        load_settings()


def test_telegram_guide_config_rejects_reused_secrets(monkeypatch):
    shared = "s" * 43
    monkeypatch.setenv("TELEGRAM_GUIDE_ENABLED", "true")
    monkeypatch.setenv(
        "TELEGRAM_GUIDE_BOT_TOKEN",
        "987654321:separatepublicbotabcdefghijklmnopqrstuvwxyz",
    )
    monkeypatch.setenv("TELEGRAM_GUIDE_WEBHOOK_SECRET", shared)
    monkeypatch.setenv("TELEGRAM_IDENTITY_HASH_SALT", shared)

    with pytest.raises(RuntimeError, match="independent Telegram"):
        load_settings()


def test_telegram_reminder_config_requires_independent_dispatch_secret(monkeypatch):
    shared = "s" * 43
    monkeypatch.setenv("TELEGRAM_GUIDE_ENABLED", "true")
    monkeypatch.setenv(
        "TELEGRAM_GUIDE_BOT_TOKEN",
        "987654321:separatepublicbotabcdefghijklmnopqrstuvwxyz",
    )
    monkeypatch.setenv("TELEGRAM_GUIDE_WEBHOOK_SECRET", "w" * 43)
    monkeypatch.setenv("TELEGRAM_IDENTITY_HASH_SALT", shared)
    monkeypatch.setenv("TELEGRAM_REMINDERS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_REMINDER_DISPATCH_TOKEN", shared)

    with pytest.raises(RuntimeError, match="independent Telegram reminder"):
        load_settings()


def test_telegram_reminders_cannot_run_without_guide(monkeypatch):
    monkeypatch.setenv("TELEGRAM_REMINDERS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_REMINDER_DISPATCH_TOKEN", "d" * 43)

    with pytest.raises(RuntimeError, match="TELEGRAM_GUIDE_ENABLED"):
        load_settings()
