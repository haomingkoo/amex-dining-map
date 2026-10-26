"""Inline buttons, button taps through the webhook, and the opt-in daily digest."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import db, telegram, telegram_bot_store, telegram_digest, telegram_keyboards, telegram_reminders, tft_guide, tft_slot_history
from tests.test_telegram_bot import WEBHOOK_SECRET, _enabled_reminder_settings, _post, _update, guide_client  # noqa: F401
from app.main import app
from app.telegram_bot_routes import get_settings


SGT_NINE_THIRTY = datetime(2026, 11, 2, 1, 30, tzinfo=timezone.utc)
PRINCIPAL = "user:" + "e" * 64


def _callback(data: str, update_id=5001, user_id=4444, chat_id=None, chat_type="private"):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id, "is_bot": False},
            "message": {"message_id": 7, "chat": {"id": chat_id or user_id, "type": chat_type}},
            "data": data,
        },
    }


# ---------------------------------------------------------------- keyboards

def test_callback_data_maps_to_existing_commands():
    assert telegram_keyboards.callback_text("slots:any") == "/slots any this week"
    assert telegram_keyboards.callback_text("slots:tft-colony") == "/slots tft-colony this week"
    assert telegram_keyboards.callback_text("remind:tft-colony") == "/start remind_tft-colony"
    assert telegram_keyboards.callback_text("venue:tft-vue") == "/venue tft-vue"
    assert telegram_keyboards.callback_text("best:tft-vue") == "/release tft-vue"
    assert telegram_keyboards.callback_text("remind") == "/remind"
    assert telegram_keyboards.callback_text("venue:../x") is None
    assert telegram_keyboards.callback_text("drop:tft-vue") is None


def test_help_and_venue_replies_carry_buttons():
    catalog = tft_guide.load_catalog()
    labels = [b["text"] for row in telegram_keyboards.markup_for("/start", catalog)["inline_keyboard"] for b in row]
    assert labels == ["Slots this week", "Set a reminder", "Venue info", "Best time to look"]
    venue = telegram_keyboards.markup_for("/venue Colony", catalog)
    assert venue["inline_keyboard"][0][0]["callback_data"] == "slots:tft-colony"
    assert telegram_keyboards.markup_for("/menu VUE", catalog) is None
    picker = telegram_keyboards.venue_picker("best", catalog)["inline_keyboard"]
    assert all(len(row) <= 2 for row in picker)
    assert all(len(b["callback_data"]) <= 64 for row in picker for b in row)


# ---------------------------------------------------------------- webhook taps

def test_button_tap_answers_like_the_command_with_buttons(guide_client, monkeypatch):
    client, settings = guide_client
    sends, acks = [], []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: sends.append(args) or 9)
    monkeypatch.setattr("app.telegram_bot_routes.telegram.answer_callback_query", lambda *args: acks.append(args))

    assert _post(client, _callback("venue:tft-colony")).json() == {"ok": True}

    assert acks == [(settings.telegram_guide_bot_token, "cb-1")]
    token, chat_id, text, markup = sends[0]
    assert chat_id == 4444
    assert text.startswith("Colony\n")
    assert markup["inline_keyboard"][1][1]["callback_data"] == "best:tft-colony"


def test_picker_tap_lists_venues_as_buttons(guide_client, monkeypatch):
    client, _settings = guide_client
    sends = []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: sends.append(args) or 9)
    monkeypatch.setattr("app.telegram_bot_routes.telegram.answer_callback_query", lambda *args: None)

    _post(client, _callback("pick:best"))

    assert sends[0][2] == telegram_keyboards.PICK_VENUE
    assert sends[0][3]["inline_keyboard"][0][0]["callback_data"].startswith("best:tft-")


@pytest.mark.parametrize(
    "payload",
    [
        _callback("venue:tft-colony", chat_type="group"),
        _callback("venue:tft-colony", chat_id=999),
        _callback("unknown:thing"),
    ],
)
def test_taps_outside_private_chat_or_unknown_are_ignored(guide_client, monkeypatch, payload):
    client, _settings = guide_client
    sends = []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: sends.append(args) or 9)
    monkeypatch.setattr("app.telegram_bot_routes.telegram.answer_callback_query", lambda *args: None)
    assert _post(client, payload).json() == {"ok": True}
    assert sends == []


def test_replayed_tap_is_answered_once(guide_client, monkeypatch):
    client, _settings = guide_client
    sends = []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: sends.append(args) or 9)
    monkeypatch.setattr("app.telegram_bot_routes.telegram.answer_callback_query", lambda *args: None)
    _post(client, _callback("venue:tft-colony", update_id=6001))
    _post(client, _callback("venue:tft-colony", update_id=6001))
    assert len(sends) == 1


# ---------------------------------------------------------------- digest flow

@pytest.fixture()
def conn(tmp_path):
    telegram_bot_store.init_db(tmp_path / "digest.db")
    connection = db.connect(tmp_path / "digest.db")
    telegram_reminders.init_db(connection)
    tft_slot_history.init_db(connection)
    yield connection
    connection.close()


def _say(conn, text, now=SGT_NINE_THIRTY):
    return telegram_digest.handle(conn, PRINCIPAL, 4444, text, tft_guide.load_catalog(), now)


def test_digest_needs_explicit_yes_before_storing_the_chat(conn):
    assert _say(conn, "/digest").startswith("The daily digest is one calm message a day")
    reply = _say(conn, "/digest Colony, VUE")
    assert "Daily digest for Colony and VUE" in reply and "/digest yes" in reply
    row = conn.execute("SELECT state, chat_id FROM telegram_digests").fetchone()
    assert (row["state"], row["chat_id"]) == ("draft", None)
    assert "Daily digest is on for Colony and VUE" in _say(conn, "/digest yes")
    row = conn.execute("SELECT state, chat_id FROM telegram_digests").fetchone()
    assert (row["state"], row["chat_id"]) == ("active", 4444)
    assert "covers Colony and VUE" in _say(conn, "/digest")


def test_unknown_venue_and_expired_draft(conn):
    assert "couldn't match Noma" in _say(conn, "/digest Colony, Noma")
    _say(conn, "/digest all")
    later = SGT_NINE_THIRTY + timedelta(hours=1)
    assert _say(conn, "/digest yes", later).startswith("Nothing is waiting")


def test_stop_and_delete_me_erase_the_digest(conn):
    _say(conn, "/digest all")
    _say(conn, "/digest yes")
    assert "chat ID it used is deleted" in _say(conn, "/digest stop")
    assert conn.execute("SELECT COUNT(*) FROM telegram_digests").fetchone()[0] == 0
    _say(conn, "/digest all")
    _say(conn, "/digest yes")
    catalog = tft_guide.load_catalog()
    telegram_reminders.handle_message(conn, PRINCIPAL, 4444, "/delete_me", catalog, SGT_NINE_THIRTY)
    telegram_reminders.handle_message(conn, PRINCIPAL, 4444, "DELETE", catalog, SGT_NINE_THIRTY)
    assert conn.execute("SELECT COUNT(*) FROM telegram_digests").fetchone()[0] == 0


def _span(conn, venue_id, slot_date, slot_time, kind, opened, closed=None):
    conn.execute(
        "INSERT INTO tft_slot_spans(venue_id, meal, slot_date, slot_time, kind, opened_at, closed_at) "
        "VALUES (?, 'Lunch', ?, ?, ?, ?, ?)",
        (venue_id, slot_date, slot_time, kind, opened, closed),
    )
    conn.commit()


def test_compose_lists_only_new_open_tables_for_followed_venues(conn):
    since = "2026-11-01T01:00:00Z"
    _span(conn, "tft-colony", "2026-11-10", "12:45", "return", "2026-11-01T05:00:00Z")
    _span(conn, "tft-colony", "2026-11-10", "13:00", "return", "2026-11-01T05:00:00Z", closed="2026-11-01T05:10:00Z")
    _span(conn, "tft-colony", "2026-11-12", "12:45", "return", "2026-10-31T05:00:00Z")
    _span(conn, "tft-vue", "2026-12-31", "12:00", "new", "2026-11-01T16:00:00Z")
    text = telegram_digest.compose(conn, ["tft-colony"], since, tft_guide.load_catalog(), SGT_NINE_THIRTY)
    assert "Colony\n• Lunch Tue 10 Nov: 12:45pm" in text
    assert "1:00pm" not in text and "12 Nov" not in text and "VUE" not in text
    assert text.endswith("/digest stop turns this off.")
    assert telegram_digest.compose(conn, ["tft-vue"], "2026-11-02T00:00:00Z", tft_guide.load_catalog(), SGT_NINE_THIRTY) is None


def test_dispatch_sends_once_a_day_after_nine_and_stays_quiet_otherwise(tmp_path, monkeypatch):
    settings = replace(_enabled_reminder_settings(_settings_for(tmp_path)), db_path=tmp_path / "d.db")
    c = db.connect(settings.db_path)
    telegram_reminders.init_db(c)
    tft_slot_history.init_db(c)
    telegram_digest.handle(c, PRINCIPAL, 4444, "/digest Colony", tft_guide.load_catalog(), SGT_NINE_THIRTY - timedelta(days=1))
    telegram_digest.handle(c, PRINCIPAL, 4444, "/digest yes", tft_guide.load_catalog(), SGT_NINE_THIRTY - timedelta(days=1))
    _span(c, "tft-colony", "2026-11-10", "12:45", "return", "2026-11-01T05:00:00Z")
    c.close()
    sent = []
    monkeypatch.setattr(telegram, "send_message", lambda *args: sent.append(args) or 1)

    early = SGT_NINE_THIRTY - timedelta(hours=1)  # 8:30am SGT
    assert telegram_digest.run_dispatch(settings, early)["sent"] == 0
    assert telegram_digest.run_dispatch(settings, SGT_NINE_THIRTY)["sent"] == 1
    assert telegram_digest.run_dispatch(settings, SGT_NINE_THIRTY + timedelta(hours=2))["sent"] == 0
    assert sent[0][1] == 4444 and "Tue 10 Nov" in sent[0][2]
    # Next day, nothing new: no message.
    assert telegram_digest.run_dispatch(settings, SGT_NINE_THIRTY + timedelta(days=1))["quiet"] == 1


def test_blocked_chat_removes_the_digest(tmp_path, monkeypatch):
    settings = replace(_enabled_reminder_settings(_settings_for(tmp_path)), db_path=tmp_path / "d.db")
    c = db.connect(settings.db_path)
    telegram_reminders.init_db(c)
    tft_slot_history.init_db(c)
    telegram_digest.handle(c, PRINCIPAL, 4444, "/digest all", tft_guide.load_catalog(), SGT_NINE_THIRTY - timedelta(days=1))
    telegram_digest.handle(c, PRINCIPAL, 4444, "/digest yes", tft_guide.load_catalog(), SGT_NINE_THIRTY - timedelta(days=1))
    _span(c, "tft-colony", "2026-11-10", "12:45", "return", "2026-11-01T05:00:00Z")
    c.close()

    def blocked(*_args):
        raise telegram.TelegramDeliveryError("telegram_http_403", "dead")

    monkeypatch.setattr(telegram, "send_message", blocked)
    assert telegram_digest.run_dispatch(settings, SGT_NINE_THIRTY)["dead"] == 1
    c = db.connect(settings.db_path)
    assert c.execute("SELECT COUNT(*) FROM telegram_digests").fetchone()[0] == 0
    c.close()


def test_digest_command_through_the_webhook(guide_client, monkeypatch):
    client, settings = guide_client
    enabled = _enabled_reminder_settings(settings)
    app.dependency_overrides[get_settings] = lambda: enabled
    sends = []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: sends.append(args) or 9)
    _post(client, _update(update_id=7101, text="/digest Colony"))
    _post(client, _update(update_id=7102, text="/digest yes"))
    assert "Daily digest is on for Colony" in sends[-1][2]


def _settings_for(tmp_path):
    from tests.test_telegram_bot import _settings
    return _settings(tmp_path / "unused.db")
