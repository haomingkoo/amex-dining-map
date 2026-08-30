from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import db, telegram_bot_store, telegram_reminders, tft_guide, tft_slot_source
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
    conn = db.connect(settings.db_path)
    try:
        telegram_reminders.init_db(conn)
    finally:
        conn.close()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    app.dependency_overrides.clear()


def _post(client: TestClient, payload: dict, secret: str | None = WEBHOOK_SECRET):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return client.post("/api/telegram/guide/webhook", json=payload, headers=headers)


def _enabled_reminder_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )


def _seed_active_reminder(settings: Settings, now: datetime, requested_date: str):
    conn = db.connect(settings.db_path)
    try:
        principal = telegram_bot_store.identity_key(
            "user", 4444, settings.telegram_identity_hash_salt
        )
        for text in ("/remind", "VUE", "2", "dinner", requested_date, "YES"):
            telegram_reminders.handle_message(
                conn, principal, 4444, text, tft_guide.load_catalog(), now
            )
    finally:
        conn.close()


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


def test_terms_delivery_log_is_diagnostic_without_user_content(
    guide_client, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = guide_client
    question = "/terms eligibility private-note-123"
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message", lambda *_args: 82
    )

    assert _post(client, _update(update_id=1201, text=question)).json() == {"ok": True}

    log_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "amex_reminders.delivery"
    )
    assert '"command_class":"/terms"' in log_text
    assert '"error_code":"sent"' in log_text
    assert '"state":"done"' in log_text
    for private_value in (
        question,
        "private-note-123",
        settings.telegram_guide_bot_token,
        WEBHOOK_SECRET,
        "4444",
        "1201",
    ):
        assert private_value not in log_text


def test_private_slot_query_fetches_once_after_guards_and_replay_deduplicates(
    guide_client, monkeypatch
):
    client, _settings_value = guide_client
    fetches = []
    sends = []
    checked_at = datetime.now(timezone.utc).isoformat()

    def load_slots():
        fetches.append(1)
        return {
            "schema_version": 1,
            "source_project": "AMEXPlatSG",
            "generated_at": checked_at,
            "venues": [
                {
                    "id": "tft-vue",
                    "project": "AMEXPlatSG",
                    "status": "live_available",
                    "checked_at": checked_at,
                    "meals": [
                        {
                            "meal": "Dinner",
                            "status": "available",
                            "slots": [
                                {
                                    "date": "2026-10-29",
                                    "time": "19:00",
                                    "max_seats": 2,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr("app.tft_slot_source.load_snapshot", load_slots)
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or 91,
    )
    update = _update(
        update_id=6001,
        text="/slots VUE | 2 | dinner | 2026-10-29 | 19:00",
    )

    assert _post(client, update).json() == {"ok": True}
    assert _post(client, update).json() == {"ok": True}

    assert len(fetches) == 1
    assert len(sends) == 1
    assert "Observed matching AMEXPlatSG slots" in sends[0][2]
    assert "2026-10-29 19:00" in sends[0][2]


def test_slot_source_failure_is_a_completed_bounded_reply(guide_client, monkeypatch):
    client, settings = guide_client
    sends = []

    def fail():
        raise tft_slot_source.SlotSourceUnavailable

    monkeypatch.setattr("app.tft_slot_source.load_snapshot", fail)
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or 92,
    )
    update = _update(
        update_id=6002,
        text="/slots VUE | 2 | dinner | 2026-10-29",
    )

    assert _post(client, update).json() == {"ok": True}
    assert len(sends) == 1
    assert "will not make an availability claim" in sends[0][2]
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state FROM telegram_webhook_updates WHERE bot_scope = ? AND update_id = ?",
            (BOT_SCOPE, 6002),
        ).fetchone()
    finally:
        conn.close()
    assert row["state"] == "done"


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


def test_rate_limit_runs_before_slot_source_fetch(guide_client, monkeypatch):
    client, settings = guide_client
    app.dependency_overrides[get_settings] = lambda: replace(
        settings, telegram_user_limit_per_minute=1
    )
    fetches = []
    monkeypatch.setattr(
        "app.tft_slot_source.load_snapshot", lambda: fetches.append(1) or {}
    )
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message", lambda *_args: 93
    )

    assert _post(client, _update(6101)).json() == {"ok": True}
    assert _post(
        client,
        _update(
            6102,
            text="/slots VUE | 2 | dinner | 2026-10-29",
        ),
    ).json() == {"ok": True}

    assert fetches == []


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
    log_payloads = [json.loads(record.getMessage()) for record in caplog.records]
    for payload in log_payloads:
        payload.pop("request_id", None)
    log_text = json.dumps(log_payloads, sort_keys=True, separators=(",", ":"))
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


def test_private_guided_reminder_flow_is_replay_safe_and_keeps_guide_commands(
    guide_client, monkeypatch
):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    sends = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or len(sends),
    )
    requested_date = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    steps = [
        "/remind",
        "/venues",
        "VUE",
        "2",
        "dinner",
        requested_date,
        "YES",
    ]
    for index, text in enumerate(steps, start=30_000):
        assert _post(client, _update(update_id=index, text=text)).json() == {"ok": True}
    replay = _post(client, _update(update_id=30_006, text="YES"))

    assert replay.json() == {"ok": True}
    assert len(sends) == len(steps)
    assert "Table for Two — cached roster" in sends[1][2]
    assert "How many people" in sends[2][2]
    assert "store this private chat ID" in sends[0][2]
    assert "Active reminder R" in sends[-1][2]
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state, chat_id, venue_id, party_size, meal FROM telegram_reminders"
        ).fetchone()
        assert tuple(row) == ("active", 4444, "tft-vue", 2, "Dinner")
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminder_conversations"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_reminder_dispatch_auth_precedes_source_loading(guide_client, monkeypatch):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    loads = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot",
        lambda: loads.append(1) or {},
    )

    response = client.post(
        "/api/internal/telegram/reminders/dispatch",
        json={"expected_generated_at": datetime.now(timezone.utc).isoformat()},
        headers={"X-Telegram-Reminder-Dispatch-Token": "wrong"},
    )

    assert response.status_code == 401
    assert loads == []


def test_management_and_delete_confirmation_have_independent_quota(
    guide_client, monkeypatch
):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
        telegram_user_limit_per_minute=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    sends = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or len(sends),
    )

    _post(client, _update(update_id=40_001, text="/remind"))
    _post(client, _update(update_id=40_002, text="spam that exhausts guide quota"))
    _post(client, _update(update_id=40_003, text="/delete_me"))
    _post(client, _update(update_id=40_004, text="DELETE"))

    assert len(sends) == 3
    assert "Delete your Telegram reminder data" in sends[-2][2]
    assert "Email reminders were not changed" in sends[-1][2]


def test_reminder_dispatch_generation_mismatch_fails_before_claim_or_send(
    guide_client, monkeypatch
):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    snapshot = {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": "2026-08-30T04:00:00+00:00",
        "venues": [],
    }
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot",
        lambda force_refresh=False: snapshot,
    )
    sends = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or 1,
    )

    response = client.post(
        "/api/internal/telegram/reminders/dispatch",
        json={"expected_generated_at": "2026-08-30T04:01:00+00:00"},
        headers={"X-Telegram-Reminder-Dispatch-Token": "d" * 43},
    )

    assert response.status_code == 409
    assert sends == []
    conn = db.connect(settings.db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminder_deliveries"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_dispatch_bypasses_prewarmed_old_snapshot_once(guide_client, monkeypatch):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    old = {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": "2026-08-30T04:00:00+00:00",
        "venues": [],
    }
    fresh = {**old, "generated_at": "2026-08-30T04:01:00+00:00"}
    calls = []

    def load(force_refresh=False):
        calls.append(force_refresh)
        return fresh if force_refresh else old

    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot", load
    )
    response = client.post(
        "/api/internal/telegram/reminders/dispatch",
        json={"expected_generated_at": fresh["generated_at"]},
        headers={"X-Telegram-Reminder-Dispatch-Token": "d" * 43},
    )

    assert response.status_code == 200
    assert response.json()["claimed"] == 0
    assert calls == [False, True]


def test_dispatch_source_and_store_failures_have_correlated_privacy_safe_logs(
    guide_client, monkeypatch, caplog
):
    client, settings = guide_client
    settings = _enabled_reminder_settings(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    expected = datetime.now(timezone.utc).isoformat()
    headers = {"X-Telegram-Reminder-Dispatch-Token": "d" * 43}
    body = {"expected_generated_at": expected}

    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot",
        lambda force_refresh=False: (_ for _ in ()).throw(
            tft_slot_source.SlotSourceUnavailable("CANARY_SOURCE_SECRET")
        ),
    )
    source_response = client.post(
        "/api/internal/telegram/reminders/dispatch", json=body, headers=headers
    )
    source_logs = [
        record.getMessage()
        for record in caplog.records
        if '"event":"telegram_reminder_run"' in record.getMessage()
    ]
    assert source_response.status_code == 503
    assert '"error_code":"slot_source_unavailable"' in source_logs[-1]
    assert '"run_id":' in source_logs[-1]
    assert "CANARY_SOURCE_SECRET" not in source_logs[-1]

    caplog.clear()
    snapshot = {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": expected,
        "venues": [],
    }
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot",
        lambda force_refresh=False: snapshot,
    )
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram_reminders.claim_notifications",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("CANARY_STORE_SECRET")
        ),
    )
    store_response = client.post(
        "/api/internal/telegram/reminders/dispatch", json=body, headers=headers
    )
    store_logs = [
        record.getMessage()
        for record in caplog.records
        if '"event":"telegram_reminder_run"' in record.getMessage()
    ]
    assert store_response.status_code == 503
    assert '"error_code":"store_unavailable"' in store_logs[-1]
    assert '"run_id":' in store_logs[-1]
    assert "CANARY_STORE_SECRET" not in store_logs[-1]
    assert "d" * 43 not in "\n".join(source_logs + store_logs)


def test_receipt_conflict_after_send_logs_unknown_and_failed_run_without_pii(
    guide_client, monkeypatch, caplog
):
    client, settings = guide_client
    settings = _enabled_reminder_settings(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    now = datetime.now(timezone.utc)
    requested_date = (now + timedelta(days=10)).date().isoformat()
    _seed_active_reminder(settings, now, requested_date)
    snapshot = {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": now.isoformat(),
        "venues": [
            {
                "id": "tft-vue",
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": (now - timedelta(minutes=2)).isoformat(),
                "meals": [
                    {
                        "meal": "Dinner",
                        "status": "available",
                        "slots": [
                            {"date": requested_date, "time": "19:00", "max_seats": 2}
                        ],
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot",
        lambda force_refresh=False: snapshot,
    )
    sends = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or 900,
    )
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram_reminders.complete_notification",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("CANARY_RECEIPT_SECRET")
        ),
    )
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")

    response = client.post(
        "/api/internal/telegram/reminders/dispatch",
        json={"expected_generated_at": snapshot["generated_at"]},
        headers={"X-Telegram-Reminder-Dispatch-Token": "d" * 43},
    )

    assert response.status_code == 500
    assert len(sends) == 1
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert '"error_code":"receipt_conflict"' in log_text
    assert '"state":"unknown"' in log_text
    assert '"event":"telegram_reminder_run"' in log_text
    for forbidden in (
        "CANARY_RECEIPT_SECRET",
        "4444",
        requested_date,
        "tft-vue",
        "d" * 43,
        sends[0][2],
    ):
        assert forbidden not in log_text


def test_reminder_dispatch_sends_once_then_terminally_closes_destination(
    guide_client, monkeypatch, caplog
):
    client, settings = guide_client
    settings = replace(
        settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="d" * 43,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    now = datetime.now(timezone.utc)
    requested_date = (now + timedelta(days=10)).date().isoformat()
    conn = db.connect(settings.db_path)
    try:
        principal = telegram_bot_store.identity_key(
            "user", 4444, settings.telegram_identity_hash_salt
        )
        for text in ("/remind", "VUE", "2", "dinner", requested_date, "YES"):
            telegram_reminders.handle_message(
                conn, principal, 4444, text, tft_guide.load_catalog(), now
            )
    finally:
        conn.close()
    snapshot = {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": now.isoformat(),
        "venues": [
            {
                "id": "tft-vue",
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": (now - timedelta(minutes=2)).isoformat(),
                "meals": [
                    {
                        "meal": "Dinner",
                        "status": "available",
                        "slots": [
                            {"date": requested_date, "time": "19:00", "max_seats": 2}
                        ],
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        "app.telegram_bot_routes.tft_slot_source.load_snapshot", lambda: snapshot
    )
    sends = []
    monkeypatch.setattr(
        "app.telegram_bot_routes.telegram.send_message",
        lambda *args: sends.append(args) or 501,
    )
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    headers = {"X-Telegram-Reminder-Dispatch-Token": "d" * 43}
    body = {"expected_generated_at": snapshot["generated_at"]}

    first = client.post(
        "/api/internal/telegram/reminders/dispatch", json=body, headers=headers
    )
    replay = client.post(
        "/api/internal/telegram/reminders/dispatch", json=body, headers=headers
    )

    first_payload = first.json()
    replay_payload = replay.json()
    assert {key: first_payload[key] for key in ("ok", "claimed", "sent", "unknown", "dead", "skipped", "more")} == {
        "ok": True, "claimed": 1, "sent": 1, "unknown": 0,
        "dead": 0, "skipped": 0, "more": False,
    }
    assert {key: replay_payload[key] for key in ("ok", "claimed", "sent", "unknown", "dead", "skipped", "more")} == {
        "ok": True, "claimed": 0, "sent": 0, "unknown": 0,
        "dead": 0, "skipped": 0, "more": False,
    }
    assert len(first_payload["run_id"]) == len(replay_payload["run_id"]) == 16
    assert len(sends) == 1
    assert sends[0][1] == 4444
    assert "not a booking guarantee" in sends[0][2]
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT state, chat_id FROM telegram_reminders"
        ).fetchone()
        assert tuple(row) == ("notified", 0)
    finally:
        conn.close()
    logged_values = []
    for record in caplog.records:
        payload = json.loads(record.getMessage())
        pending = [payload]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            else:
                logged_values.append(value)
    for forbidden in (4444, requested_date, "tft-vue", "d" * 43, sends[0][2]):
        assert forbidden not in logged_values
