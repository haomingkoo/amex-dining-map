from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db, telegram_bot_store, telegram_reminders, tft_guide


NOW = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
PRINCIPAL_A = "user:" + "a" * 64
PRINCIPAL_B = "user:" + "b" * 64


def connection(path: Path):
    conn = db.connect(path)
    telegram_bot_store.init_db(path)
    telegram_reminders.init_db(conn)
    return conn


def create_reminder(conn, principal=PRINCIPAL_A, chat_id=111, date_value="2026-10-29"):
    catalog = tft_guide.load_catalog()
    replies = [
        telegram_reminders.handle_message(conn, principal, chat_id, "/remind", catalog, NOW),
        telegram_reminders.handle_message(conn, principal, chat_id, "VUE", catalog, NOW),
        telegram_reminders.handle_message(conn, principal, chat_id, "2", catalog, NOW),
        telegram_reminders.handle_message(conn, principal, chat_id, "dinner", catalog, NOW),
        telegram_reminders.handle_message(conn, principal, chat_id, date_value, catalog, NOW),
    ]
    confirmation = telegram_reminders.handle_message(
        conn, principal, chat_id, "YES", catalog, NOW
    )
    return replies, confirmation


def fresh_snapshot():
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": NOW.isoformat(),
        "venues": [
            {
                "id": "tft-vue",
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
                "meals": [
                    {
                        "meal": "Dinner",
                        "status": "available",
                        "slots": [
                            {"date": "2026-10-29", "time": "19:00", "max_seats": 2},
                            {"date": "2026-10-29", "time": "19:30", "max_seats": 4},
                        ],
                    }
                ],
            }
        ],
    }


def test_guided_confirmation_stores_chat_only_after_explicit_yes(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    try:
        replies, confirmation = create_reminder(conn)
        assert "stored delivery chat ID" not in " ".join(reply or "" for reply in replies)
        assert "store this private chat ID" in replies[0]
        assert "store this private chat ID" in replies[-1]
        assert "/delete_me" in replies[-1]
        assert "Timezone: Singapore" in replies[-1]
        assert "notify once only" in replies[-1]
        assert "Active reminder R" in confirmation
        conversation_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(telegram_reminder_conversations)"
            ).fetchall()
        }
        assert "chat_id" not in conversation_columns
        row = conn.execute("SELECT * FROM telegram_reminders").fetchone()
        assert row["chat_id"] == 111
        assert row["state"] == "active"
    finally:
        conn.close()


def test_resumed_confirmation_repeats_chat_storage_and_deletion_consent(
    tmp_path: Path,
):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        for text in ("/remind", "VUE", "2", "dinner", "2026-10-29"):
            telegram_reminders.handle_message(
                conn, PRINCIPAL_A, 111, text, catalog, NOW
            )
        resumed = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "/remind", catalog, NOW
        )
        assert "store this private chat ID" in resumed
        assert "until the reminder ends or is cancelled" in resumed
        assert "/delete_me" in resumed
        activated = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "YES", catalog, NOW
        )
        assert "Active reminder" in activated
    finally:
        conn.close()


def test_invalid_steps_do_not_save_and_idle_state_expires(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        telegram_reminders.handle_message(conn, PRINCIPAL_A, 111, "/remind", catalog, NOW)
        assert "one exact" in telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "not a venue", catalog, NOW
        )
        assert "How many people" in telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "VUE", catalog, NOW
        )
        assert "whole-number" in telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "11", catalog, NOW
        )
        expired = telegram_reminders.handle_message(
            conn,
            PRINCIPAL_A,
            111,
            "2",
            catalog,
            NOW + timedelta(minutes=16),
        )
        assert expired == "Reminder setup expired. Send /remind to start again."
        assert conn.execute("SELECT COUNT(*) FROM telegram_reminders").fetchone()[0] == 0
    finally:
        conn.close()


def test_delete_confirmation_gets_fresh_fifteen_minute_window(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        moments = [0, 14, 28, 42, 55]
        messages = ["/remind", "VUE", "2", "dinner", "2026-10-29"]
        for minutes, message in zip(moments, messages, strict=True):
            telegram_reminders.handle_message(
                conn,
                PRINCIPAL_A,
                111,
                message,
                catalog,
                NOW + timedelta(minutes=minutes),
            )
        prompt = telegram_reminders.handle_message(
            conn,
            PRINCIPAL_A,
            111,
            "/delete_me",
            catalog,
            NOW + timedelta(minutes=56),
        )
        assert "within 15 minutes" in prompt
        conversation = conn.execute(
            "SELECT created_ts, expires_ts FROM telegram_reminder_conversations "
            "WHERE principal_key = ?",
            (PRINCIPAL_A,),
        ).fetchone()
        assert conversation["created_ts"] == (
            NOW + timedelta(minutes=56)
        ).isoformat()
        assert conversation["expires_ts"] == (
            NOW + timedelta(minutes=71)
        ).isoformat()
        deleted = telegram_reminders.handle_message(
            conn,
            PRINCIPAL_A,
            111,
            "DELETE",
            catalog,
            NOW + timedelta(minutes=61),
        )
        assert "Email reminders were not changed" in deleted
    finally:
        conn.close()


def test_list_and_cancel_are_owned_and_non_enumerating(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        create_reminder(conn)
        row = conn.execute("SELECT id FROM telegram_reminders").fetchone()
        reminder_id = row["id"]
        own = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "/reminders", catalog, NOW
        )
        foreign = telegram_reminders.handle_message(
            conn, PRINCIPAL_B, 222, f"/cancel {reminder_id}", catalog, NOW
        )
        missing = telegram_reminders.handle_message(
            conn, PRINCIPAL_B, 222, "/cancel RFFFFFF", catalog, NOW
        )
        assert reminder_id in own and "VUE" in own
        assert foreign == missing == "No active reminder matched that code."
        assert conn.execute(
            "SELECT state FROM telegram_reminders WHERE id = ?", (reminder_id,)
        ).fetchone()[0] == "active"
        cancelled = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, f"/cancel {reminder_id}", catalog, NOW
        )
        assert "Cancelled" in cancelled
        row = conn.execute(
            "SELECT state, chat_id FROM telegram_reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        assert tuple(row) == ("cancelled", 0)
    finally:
        conn.close()


def test_delete_me_cascades_only_requesting_principal_and_keeps_email(tmp_path: Path):
    path = tmp_path / "reminders.db"
    db.init_db(path)
    conn = connection(path)
    catalog = tft_guide.load_catalog()
    try:
        create_reminder(conn, PRINCIPAL_A, 111)
        create_reminder(conn, PRINCIPAL_B, 222)
        conn.execute(
            "INSERT INTO subscribers (email, party_size, sessions, venues, date_start, date_end, dates, unsubscribe_token, manage_token, created_ts) VALUES ('keep@example.com', 2, '[]', '[]', '2026-10-29', '2026-10-29', '[]', 'u', 'm', ?)",
            (NOW.isoformat(),),
        )
        conn.execute(
            "INSERT INTO telegram_rate_events (scope_key, event_type, created_ts) VALUES (?, 'guide', ?)",
            (PRINCIPAL_A, NOW.isoformat()),
        )
        conn.commit()
        prompt = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "/delete_me", catalog, NOW
        )
        deleted = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "DELETE", catalog, NOW
        )
        assert "does not affect email" in prompt
        assert "Email reminders were not changed" in deleted
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminders WHERE principal_key = ?",
            (PRINCIPAL_A,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminders WHERE principal_key = ?",
            (PRINCIPAL_B,),
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_rate_events WHERE scope_key = ?",
            (PRINCIPAL_A,),
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_fresh_match_claims_one_bounded_notification_and_replay_none(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    try:
        create_reminder(conn)
        first = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        replay = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(first.notifications) == 1
        assert replay.notifications == []
        notification = first.notifications[0]
        assert "19:00" in notification.text and "19:30" in notification.text
        assert "not a booking guarantee" in notification.text
        assert "checked 30 Aug 2026, 11:55 SGT" in notification.text
        assert telegram_reminders.begin_notification(
            conn, notification.reminder_id, notification.chat_id, NOW
        )
        telegram_reminders.complete_notification(
            conn, notification.reminder_id, "done", "sent", NOW, 99
        )
        row = conn.execute(
            "SELECT state, chat_id FROM telegram_reminders"
        ).fetchone()
        assert tuple(row) == ("notified", 0)
    finally:
        conn.close()


def test_wrong_project_stale_and_ambiguous_delivery_never_replay(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    try:
        create_reminder(conn)
        wrong = fresh_snapshot()
        wrong["source_project"] = "GenericDiningCity"
        try:
            telegram_reminders.claim_notifications(conn, wrong, NOW)
            raise AssertionError("wrong source should fail")
        except ValueError:
            pass
        stale = fresh_snapshot()
        stale["venues"][0]["checked_at"] = (NOW - timedelta(minutes=31)).isoformat()
        stale_result = telegram_reminders.claim_notifications(conn, stale, NOW)
        assert stale_result.notifications == []
        assert stale_result.stale_venue_count == 1
        claimed = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        notification = claimed.notifications[0]
        assert telegram_reminders.begin_notification(
            conn, notification.reminder_id, notification.chat_id, NOW
        )
        telegram_reminders.complete_notification(
            conn,
            notification.reminder_id,
            "unknown",
            "telegram_transport_unknown",
            NOW,
        )
        assert telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW
        ).notifications == []
        row = conn.execute(
            "SELECT state, chat_id FROM telegram_reminders"
        ).fetchone()
        assert tuple(row) == ("unknown", 0)
    finally:
        conn.close()


def test_concurrent_confirmation_and_dispatch_each_have_one_winner(tmp_path: Path):
    path = tmp_path / "reminders.db"
    conn = connection(path)
    catalog = tft_guide.load_catalog()
    try:
        for text in ("/remind", "VUE", "2", "dinner", "2026-10-29"):
            telegram_reminders.handle_message(
                conn, PRINCIPAL_A, 111, text, catalog, NOW
            )
    finally:
        conn.close()

    def confirm():
        local = db.connect(path)
        try:
            return telegram_reminders.handle_message(
                local, PRINCIPAL_A, 111, "YES", catalog, NOW
            )
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        confirmation_results = list(pool.map(lambda _index: confirm(), range(2)))
    assert sum("Active reminder" in (result or "") for result in confirmation_results) == 1

    def claim():
        local = db.connect(path)
        try:
            return telegram_reminders.claim_notifications(local, fresh_snapshot(), NOW)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_results = list(pool.map(lambda _index: claim(), range(2)))
    assert sorted(len(result.notifications) for result in claim_results) == [0, 1]


def test_delete_after_claim_prevents_dispatch_send_check(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        create_reminder(conn)
        notification = telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW
        ).notifications[0]
        telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "/delete_me", catalog, NOW
        )
        telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "DELETE", catalog, NOW
        )
        assert not telegram_reminders.begin_notification(
            conn, notification.reminder_id, notification.chat_id, NOW
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminder_deliveries"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_stale_claimed_is_requeued_but_stale_sending_is_terminal_unknown(
    tmp_path: Path,
):
    conn = connection(tmp_path / "reminders.db")
    try:
        create_reminder(conn, PRINCIPAL_A, 111)
        create_reminder(conn, PRINCIPAL_B, 222)
        claimed = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(claimed.notifications) == 2
        first, second = claimed.notifications
        assert telegram_reminders.begin_notification(
            conn, first.reminder_id, first.chat_id, NOW
        )
        telegram_reminders.complete_notification(
            conn, first.reminder_id, "done", "sent", NOW, 10
        )

        recovered = telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW + timedelta(minutes=6)
        )
        assert recovered.reconciled_claimed_count == 1
        assert [item.reminder_id for item in recovered.notifications] == [
            second.reminder_id
        ]
        assert telegram_reminders.begin_notification(
            conn,
            second.reminder_id,
            second.chat_id,
            NOW + timedelta(minutes=6),
        )

        quarantined = telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW + timedelta(minutes=12)
        )
        assert quarantined.reconciled_unknown_count == 1
        assert quarantined.notifications == []
        row = conn.execute(
            "SELECT state, chat_id FROM telegram_reminders WHERE id = ?",
            (second.reminder_id,),
        ).fetchone()
        assert tuple(row) == ("unknown", 0)
    finally:
        conn.close()


def test_owner_can_cancel_claimed_notification_before_send(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        create_reminder(conn)
        notification = telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW
        ).notifications[0]
        reply = telegram_reminders.handle_message(
            conn,
            PRINCIPAL_A,
            111,
            f"/cancel {notification.reminder_id}",
            catalog,
            NOW,
        )
        assert "Cancelled" in reply
        assert not telegram_reminders.begin_notification(
            conn, notification.reminder_id, notification.chat_id, NOW
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminder_deliveries"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_delete_waits_for_inflight_send_before_acknowledging_erasure(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    try:
        create_reminder(conn)
        notification = telegram_reminders.claim_notifications(
            conn, fresh_snapshot(), NOW
        ).notifications[0]
        assert telegram_reminders.begin_notification(
            conn, notification.reminder_id, notification.chat_id, NOW
        )
        telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "/delete_me", catalog, NOW
        )
        waiting = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "DELETE", catalog, NOW
        )
        assert "finishing" in waiting
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminders"
        ).fetchone()[0] == 1
        telegram_reminders.complete_notification(
            conn, notification.reminder_id, "done", "sent", NOW, 22
        )
        deleted = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "DELETE", catalog, NOW
        )
        assert "Email reminders were not changed" in deleted
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminders"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_identity_salt_rotation_requires_drained_reminders(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    try:
        telegram_reminders.init_db(conn, "a" * 43)
        create_reminder(conn)
        try:
            telegram_reminders.init_db(conn, "b" * 43)
            raise AssertionError("active reminder should block salt rotation")
        except RuntimeError as exc:
            assert "drain Telegram reminders" in str(exc)
        reminder_id = conn.execute("SELECT id FROM telegram_reminders").fetchone()[0]
        telegram_reminders.handle_message(
            conn,
            PRINCIPAL_A,
            111,
            f"/cancel {reminder_id}",
            tft_guide.load_catalog(),
            NOW,
        )
        telegram_reminders.init_db(conn, "b" * 43)
    finally:
        conn.close()


def test_dispatch_claims_at_most_two_and_reports_more_matching_work(tmp_path: Path):
    conn = connection(tmp_path / "reminders.db")
    try:
        for index in range(3):
            create_reminder(
                conn,
                f"user:{index}" + "c" * 60,
                100 + index,
            )
        first = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(first.notifications) == 2
        assert first.matched_count == 3
        assert first.more_matches is True
        for notification in first.notifications:
            assert telegram_reminders.begin_notification(
                conn, notification.reminder_id, notification.chat_id, NOW
            )
            telegram_reminders.complete_notification(
                conn, notification.reminder_id, "done", "sent", NOW, 1
            )
        second = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(second.notifications) == 1
        assert second.more_matches is False
    finally:
        conn.close()


def test_global_live_cap_prevents_unscannable_newer_matching_reminder(
    tmp_path: Path,
):
    conn = connection(tmp_path / "reminders.db")
    catalog = tft_guide.load_catalog()
    now_iso = NOW.isoformat()
    try:
        conn.executemany(
            """INSERT INTO telegram_reminders (
              id, principal_key, chat_id, venue_id, venue_name, party_size,
              meal, date_start, date_end, dates, state, created_ts, updated_ts
            ) VALUES (?, ?, ?, 'tft-nonmatch', 'Nonmatch', 2, 'Dinner',
              '2026-10-29', '2026-10-29', '[]', 'active', ?, ?)""",
            (
                (f"R{index:06X}", f"user:cap-{index}", index + 1, now_iso, now_iso)
                for index in range(telegram_reminders.MAX_LIVE_REMINDERS)
            ),
        )
        conn.commit()
        for text in ("/remind", "VUE", "2", "dinner", "2026-10-29"):
            telegram_reminders.handle_message(
                conn, PRINCIPAL_A, 111, text, catalog, NOW
            )
        refused = telegram_reminders.handle_message(
            conn, PRINCIPAL_A, 111, "YES", catalog, NOW
        )
        assert "capacity is temporarily full" in refused
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_reminders "
            "WHERE state IN ('active', 'claimed', 'sending')"
        ).fetchone()[0] == telegram_reminders.MAX_SCAN_BATCH
        result = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert result.active_scanned_count == telegram_reminders.MAX_SCAN_BATCH
        assert result.batch_limited is False
        assert result.notifications == []
    finally:
        conn.close()
