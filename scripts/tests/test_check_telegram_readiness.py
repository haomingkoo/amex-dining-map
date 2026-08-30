from __future__ import annotations

import pytest

from scripts import check_telegram_readiness as readiness


def configured(monkeypatch):
    values = {
        "TELEGRAM_BOT_TOKEN": "123456789:ownerbotabcdefghijklmnop",
        "TELEGRAM_GUIDE_BOT_TOKEN": "987654321:guidebotabcdefghijklmnop",
        "TELEGRAM_OWNER_CHAT_ID": "-1001234567890",
        "OWNER_ALERT_NOT_BEFORE": "2026-08-30T08:00:00Z",
        "OWNER_ALERT_INGEST_TOKEN": "o" * 43,
        "TELEGRAM_GUIDE_WEBHOOK_SECRET": "w" * 43,
        "TELEGRAM_IDENTITY_HASH_SALT": "i" * 43,
        "TELEGRAM_REMINDER_DISPATCH_TOKEN": "d" * 43,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_config_check_returns_values_without_printing_secrets(monkeypatch, capsys):
    values = configured(monkeypatch)
    result = readiness.config_values()

    assert result["owner_chat_id"] == -1001234567890
    assert result["owner_token"] == values["TELEGRAM_BOT_TOKEN"]
    assert capsys.readouterr().out == ""


def test_config_check_rejects_reused_secrets(monkeypatch):
    configured(monkeypatch)
    monkeypatch.setenv("TELEGRAM_REMINDER_DISPATCH_TOKEN", "o" * 43)

    with pytest.raises(readiness.ReadinessError, match="must be independent"):
        readiness.config_values()


def test_identity_check_enforces_distinct_bots_channel_and_least_privilege(monkeypatch):
    values = {
        "owner_token": "owner",
        "guide_token": "guide",
        "owner_chat_id": -1001234567890,
    }

    def call(token, method, data=None, allow_absent=False):
        if method == "getMe":
            return {"id": 1 if token == "owner" else 2, "is_bot": True}
        if method == "getChat":
            return {"id": -1001234567890, "type": "channel"}
        if method == "getChatMember" and data["user_id"] == 1:
            return {"status": "administrator", "can_post_messages": True}
        if method == "getChatMember":
            return None
        if method == "getWebhookInfo":
            return {"url": ""}
        raise AssertionError((token, method, data, allow_absent))

    monkeypatch.setattr(readiness, "telegram_call", call)
    readiness.check_identities(values)


def test_identity_check_rejects_extra_owner_permission(monkeypatch):
    values = {"owner_token": "owner", "guide_token": "guide", "owner_chat_id": -1001234567890}

    def call(token, method, data=None, allow_absent=False):
        if method == "getMe":
            return {"id": 1 if token == "owner" else 2, "is_bot": True}
        if method == "getChat":
            return {"id": -1001234567890, "type": "channel"}
        if method == "getChatMember" and data["user_id"] == 1:
            return {
                "status": "administrator",
                "can_post_messages": True,
                "can_delete_messages": True,
            }
        return None

    monkeypatch.setattr(readiness, "telegram_call", call)
    with pytest.raises(readiness.ReadinessError, match="unnecessary can_delete_messages"):
        readiness.check_identities(values)


def test_owner_readiness_uses_only_health_and_wrong_credential_probe(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "health",
        lambda _base: {"feature_state": {"owner_alerts_enabled": True}},
    )
    calls = []
    monkeypatch.setattr(
        readiness,
        "expect_status",
        lambda url, headers, status: calls.append((url, headers, status)),
    )

    readiness.check_owner("https://reminders.example")
    assert calls[0][2] == 401
    assert calls[0][1]["Authorization"] == "Bearer deliberately-wrong"
