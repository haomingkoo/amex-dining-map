from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

import pytest
from fastapi.testclient import TestClient

from app import db, telegram_bot_store
from app.config import Settings
from app.main import app
from app.telegram_bot_routes import BOT_SCOPE, get_settings


WEBHOOK_SECRET = "w" * 43


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
        telegram_guide_enabled=True,
        telegram_guide_bot_token="987654321:separatepublicbotabcdefghijklmnopqrstuvwxyz",
        telegram_guide_webhook_secret=WEBHOOK_SECRET,
        telegram_identity_hash_salt="s" * 43,
    )


def _update(update_id=1001, text="/menu VUE platinum", user_id=4444, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id + 10,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": user_id, "type": chat_type, "username": "spoofed"},
            "from": {
                "id": user_id,
                "is_bot": False,
                "username": "spoofed-owner",
            },
            "text": text,
        },
    }


@pytest.fixture()
def guide_client(tmp_path: Path):
    settings = _settings(tmp_path / "guide.db")
    db.init_db(settings.db_path)
    telegram_bot_store.init_db(settings.db_path)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    app.dependency_overrides.clear()


def _post(client: TestClient, payload: dict, secret: str | None = WEBHOOK_SECRET):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return client.post("/api/telegram/guide/webhook", json=payload, headers=headers)


def test_wrong_webhook_secret_has_no_side_effect(guide_client, monkeypatch):
    client, settings = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    response = _post(client, _update(), "wrong")

    assert response.status_code == 401
    assert calls == []
    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM telegram_webhook_updates").fetchone()[0] == 0
    finally:
        conn.close()
    assert WEBHOOK_SECRET not in response.text


def test_wrong_secret_rejects_malformed_json_before_parsing(guide_client):
    client, _settings_value = guide_client
    response = client.post(
        "/api/telegram/guide/webhook",
        content=b"{not-json",
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": "wrong",
        },
    )
    assert response.status_code == 401


def test_disabled_guide_fails_closed_without_side_effect(guide_client, monkeypatch):
    client, settings = guide_client
    app.dependency_overrides[get_settings] = lambda: replace(
        settings, telegram_guide_enabled=False
    )
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    response = _post(client, _update())

    assert response.status_code == 503
    assert calls == []


def test_webhook_body_limit_applies_before_side_effect(guide_client):
    client, settings = guide_client
    response = client.post(
        "/api/telegram/guide/webhook",
        content=b'{' + b'"padding":"' + b"x" * 17_000 + b'"}',
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET,
        },
    )
    assert response.status_code == 413
    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM telegram_webhook_updates").fetchone()[0] == 0
    finally:
        conn.close()


def test_private_menu_query_sends_once_and_replay_is_deduplicated(
    guide_client, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 81,
    )

    first = _post(client, _update())
    replay = _post(client, _update())

    assert first.json() == {"ok": True}
    assert replay.json() == {"ok": True}
    assert len(calls) == 1
    assert calls[0][0] == settings.telegram_guide_bot_token
    assert calls[0][1] == 4444
    assert "VUE — Platinum menu" in calls[0][2]
    assert settings.telegram_guide_webhook_secret not in first.text
    log_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "amex_reminders.delivery"
    )
    assert '"state":"done"' in log_text
    for secret in ("/menu VUE platinum", settings.telegram_guide_bot_token, WEBHOOK_SECRET, "4444", "1001"):
        assert secret not in log_text


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_non_private_updates_are_ignored(guide_client, monkeypatch, chat_type):
    client, _settings_value = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )
    payload = _update(chat_type=chat_type)
    if chat_type != "private":
        payload["message"]["chat"]["id"] = -100555

    assert _post(client, payload).json() == {"ok": True}
    assert calls == []


def test_rate_limited_spam_sends_no_warning_amplification(guide_client, monkeypatch):
    client, settings = guide_client
    limited = replace(
        settings,
        telegram_user_limit_per_minute=1,
    )
    app.dependency_overrides[get_settings] = lambda: limited
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 82,
    )

    assert _post(client, _update(1001)).json() == {"ok": True}
    assert _post(client, _update(1002)).json() == {"ok": True}

    assert len(calls) == 1
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state FROM telegram_webhook_updates "
            "WHERE bot_scope = ? AND update_id = 1002",
            (BOT_SCOPE,),
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_sustained_rate_limited_burst_does_not_grow_replay_table(
    guide_client, monkeypatch
):
    client, settings = guide_client
    app.dependency_overrides[get_settings] = lambda: replace(
        settings,
        telegram_user_limit_per_minute=1,
        telegram_global_limit_per_minute=1,
    )
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message", lambda *_args: 84
    )

    for index in range(25):
        assert _post(client, _update(10_000 + index)).json() == {"ok": True}

    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM telegram_webhook_updates").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM telegram_rate_events").fetchone()[0] == 2
    finally:
        conn.close()


def test_global_limit_blocks_a_different_user_without_reply(guide_client, monkeypatch):
    client, settings = guide_client
    app.dependency_overrides[get_settings] = lambda: replace(
        settings, telegram_global_limit_per_minute=1
    )
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 85,
    )

    _post(client, _update(20_001, user_id=1111))
    _post(client, _update(20_002, user_id=2222))

    assert len(calls) == 1


def test_raw_telegram_identity_is_not_stored(guide_client, monkeypatch):
    client, settings = guide_client
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message", lambda *_args: 83
    )
    _post(client, _update(update_id=8001, user_id=987654321))

    conn = db.connect(settings.db_path)
    try:
        keys = [
            row[0]
            for row in conn.execute(
                "SELECT scope_key FROM telegram_rate_events"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert keys
    assert all("987654321" not in key for key in keys)


def test_oversized_text_is_ignored_without_send_or_claim(guide_client, monkeypatch):
    client, settings = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    assert _post(client, _update(text="x" * 513)).json() == {"ok": True}
    assert calls == []
    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM telegram_webhook_updates").fetchone()[0] == 0
    finally:
        conn.close()


def test_old_message_is_ignored_without_send(guide_client, monkeypatch):
    client, _settings_value = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )
    payload = _update(update_id=7001)
    payload["message"]["date"] = int(
        (datetime.now(timezone.utc) - timedelta(minutes=11)).timestamp()
    )

    assert _post(client, payload).json() == {"ok": True}
    assert calls == []


def test_transport_unknown_is_not_blindly_retried(guide_client, monkeypatch, caplog):
    from app.telegram import TelegramDeliveryError

    client, settings = guide_client
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    calls = []

    def unknown(*args):
        calls.append(args)
        raise TelegramDeliveryError("telegram_transport_unknown", "unknown")

    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", unknown)

    assert _post(client, _update()).json() == {"ok": True}
    assert _post(client, _update()).json() == {"ok": True}
    assert len(calls) == 1
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"state":"unknown"' in log_text
    for secret in (
        "/menu VUE platinum",
        settings.telegram_guide_bot_token,
        WEBHOOK_SECRET,
        "4444",
        "1001",
    ):
        assert secret not in log_text


def test_transport_dead_is_logged_without_identity_or_message(
    guide_client, monkeypatch, caplog
):
    from app.telegram import TelegramDeliveryError

    client, settings = guide_client
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")

    def dead(*args):
        raise TelegramDeliveryError("telegram_rejected", "dead")

    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", dead)

    assert _post(client, _update(update_id=7007)).json() == {"ok": True}
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state, outcome_code FROM telegram_webhook_updates "
            "WHERE bot_scope = ? AND update_id = ?",
            (BOT_SCOPE, 7007),
        ).fetchone()
    finally:
        conn.close()
    assert dict(row) == {"state": "dead", "outcome_code": "telegram_rejected"}
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"state":"dead"' in log_text
    assert '"error_code":"telegram_rejected"' in log_text
    for secret in (
        "/menu VUE platinum",
        settings.telegram_guide_bot_token,
        WEBHOOK_SECRET,
        "4444",
        "7007",
    ):
        assert secret not in log_text


def test_invalid_bundled_catalog_is_quarantined_without_500(
    guide_client, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = guide_client
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_guide.load_catalog",
        lambda: (_ for _ in ()).throw(ValueError("bad catalog")),
    )
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    response = _post(client, _update(update_id=8101))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == []
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state, outcome_code FROM telegram_webhook_updates "
            "WHERE bot_scope = ? AND update_id = 8101",
            (BOT_SCOPE,),
        ).fetchone()
        assert dict(row) == {"state": "dead", "outcome_code": "catalog_invalid"}
    finally:
        conn.close()
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"error_code":"catalog_invalid"' in log_text
    for secret in (
        "/menu VUE platinum",
        settings.telegram_guide_bot_token,
        WEBHOOK_SECRET,
        "4444",
        "8101",
    ):
        assert secret not in log_text


def test_stale_processing_claim_becomes_unknown_without_resend(tmp_path: Path):
    path = tmp_path / "stale-guide.db"
    telegram_bot_store.init_db(path)
    conn = db.connect(path)
    try:
        assert telegram_bot_store.claim_update(conn, BOT_SCOPE, 9001).should_process
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn.execute(
            "UPDATE telegram_webhook_updates SET updated_ts = ? "
            "WHERE bot_scope = ? AND update_id = ?",
            (old, BOT_SCOPE, 9001),
        )
        conn.commit()
        replay = telegram_bot_store.claim_update(conn, BOT_SCOPE, 9001)
    finally:
        conn.close()
    assert replay.should_process is False
    assert replay.state == "unknown"


def test_stale_processing_replay_emits_privacy_safe_unknown_log(
    guide_client, monkeypatch, caplog
):
    client, settings = guide_client
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    conn = db.connect(settings.db_path)
    try:
        telegram_bot_store.claim_update(conn, BOT_SCOPE, 9002)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn.execute(
            "UPDATE telegram_webhook_updates SET updated_ts = ? "
            "WHERE bot_scope = ? AND update_id = ?",
            (old, BOT_SCOPE, 9002),
        )
        conn.commit()
    finally:
        conn.close()
    calls = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: calls.append(args) or 1,
    )

    assert _post(client, _update(update_id=9002)).json() == {"ok": True}
    assert calls == []
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"error_code":"stale_processing"' in log_text
    assert "9002" not in log_text
    assert "/menu VUE platinum" not in log_text


def test_concurrent_duplicate_claim_has_one_winner(tmp_path: Path):
    path = tmp_path / "concurrent-guide.db"
    telegram_bot_store.init_db(path)

    def claim_once():
        conn = db.connect(path)
        try:
            return telegram_bot_store.claim_update(conn, BOT_SCOPE, 9901).should_process
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim_once(), range(2)))

    assert sorted(results) == [False, True]
