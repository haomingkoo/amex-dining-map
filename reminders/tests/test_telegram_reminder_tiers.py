from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from app import db, telegram_reminder_dispatch, telegram_reminders, tft_guide
from tests.test_telegram_reminders import NOW, PRINCIPAL_A, connection, fresh_snapshot


def say(conn, *messages, principal=PRINCIPAL_A):
    catalog = tft_guide.load_catalog()
    return [
        telegram_reminders.handle_message(conn, principal, 111, message, catalog, NOW)
        for message in messages
    ]


def snapshot_for(project: str, venue_id: str = "tft-vue") -> dict:
    snapshot = fresh_snapshot()
    snapshot["source_project"] = project
    snapshot["venues"][0].update(id=venue_id, project=project)
    return snapshot


def test_remind_asks_for_the_card_then_lists_only_that_cards_venues(tmp_path: Path):
    conn = connection(tmp_path / "r.db")
    try:
        start, platinum = say(conn, "/remind", "platinum")
        assert "Platinum or Centurion" in start
        assert "VUE" in platinum and "JAAN" not in platinum
        say(conn, "/cancel")
        _, centurion = say(conn, "/remind", "centurion")
        assert "JAAN By Kirk Westaway" in centurion and "VUE" in centurion
    finally:
        conn.close()


def test_platinum_choice_does_not_accept_a_centurion_only_venue(tmp_path: Path):
    conn = connection(tmp_path / "r.db")
    try:
        reply = say(conn, "/remind", "platinum", "JAAN")[-1]
        assert reply == telegram_reminders.VENUE_REPROMPT
    finally:
        conn.close()


def test_centurion_reminder_is_stored_with_its_card(tmp_path: Path):
    conn = connection(tmp_path / "r.db")
    try:
        replies = say(conn, "/remind", "centurion", "JAAN", "lunch", "2026-10-29")
        assert "JAAN By Kirk Westaway · Centurion · lunch" in replies[-1]
        confirmation = say(conn, "YES")[0]
        assert "is on:" in confirmation
        row = conn.execute("SELECT venue_id, tier FROM telegram_reminders").fetchone()
        assert tuple(row) == ("tft-jaan-by-kirk-westaway", "centurion")
    finally:
        conn.close()


def test_existing_reminders_migrate_to_platinum(tmp_path: Path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE telegram_reminders (
          id TEXT PRIMARY KEY, principal_key TEXT NOT NULL, chat_id INTEGER NOT NULL,
          venue_id TEXT NOT NULL, venue_name TEXT NOT NULL, party_size INTEGER NOT NULL,
          meal TEXT NOT NULL, date_start TEXT NOT NULL, date_end TEXT NOT NULL,
          dates TEXT NOT NULL DEFAULT '[]', state TEXT NOT NULL,
          created_ts TEXT NOT NULL, updated_ts TEXT NOT NULL
        );
        CREATE TABLE telegram_reminder_conversations (
          principal_key TEXT PRIMARY KEY, state TEXT NOT NULL, venue_id TEXT, venue_name TEXT,
          party_size INTEGER, meal TEXT, date_start TEXT, date_end TEXT,
          dates TEXT NOT NULL DEFAULT '[]', created_ts TEXT NOT NULL,
          expires_ts TEXT NOT NULL, updated_ts TEXT NOT NULL
        );
        INSERT INTO telegram_reminders VALUES (
          'R000001', 'user:x', 111, 'tft-vue', 'VUE', 2, 'Dinner',
          '2026-10-29', '2026-10-29', '[]', 'active', '2026-08-30T00:00:00+00:00',
          '2026-08-30T00:00:00+00:00'
        );
        """
    )
    old.commit()
    old.close()
    conn = connection(path)
    try:
        assert conn.execute("SELECT tier FROM telegram_reminders").fetchone()[0] == "platinum"
        platinum = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(platinum.notifications) == 1
    finally:
        conn.close()


def test_each_card_only_matches_its_own_seats(tmp_path: Path):
    conn = connection(tmp_path / "r.db")
    try:
        say(conn, "/remind", "centurion", "VUE", "dinner", "2026-10-29", "YES")
        say(conn, "/remind", "platinum", "VUE", "dinner", "2026-10-29", "YES", principal="user:" + "b" * 64)
        centurion = telegram_reminders.claim_notifications(
            conn, snapshot_for("AMEXCentSG"), NOW, tft_guide.load_catalog()
        )
        assert len(centurion.notifications) == 1
        text = centurion.notifications[0].text
        assert "VUE (Centurion) has dinner open" in text
        assert "program=AMEXCentSG" in text and "restaurant_id=205194014" in text
        states = dict(conn.execute("SELECT tier, state FROM telegram_reminders").fetchall())
        assert states == {"centurion": "claimed", "platinum": "active"}
        platinum = telegram_reminders.claim_notifications(conn, fresh_snapshot(), NOW)
        assert len(platinum.notifications) == 1
        assert "(Centurion)" not in platinum.notifications[0].text
    finally:
        conn.close()


def test_centurion_start_link_preselects_the_card(tmp_path: Path):
    conn = connection(tmp_path / "r.db")
    try:
        reply = say(conn, "/start remind_centurion-tft-jaan-by-kirk-westaway")[0]
        assert "JAAN By Kirk Westaway" in reply and "Lunch or dinner?" in reply
        row = conn.execute("SELECT tier, venue_id FROM telegram_reminder_conversations").fetchone()
        assert tuple(row) == ("centurion", "tft-jaan-by-kirk-westaway")
    finally:
        conn.close()


def test_dispatch_runs_each_card_against_its_own_snapshot(monkeypatch, tmp_path: Path):
    seen = []
    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_snapshot", lambda: snapshot_for("AMEXPlatSG"))
    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_centurion_snapshot", lambda: snapshot_for("AMEXCentSG"))
    monkeypatch.setattr(
        telegram_reminder_dispatch,
        "run_dispatch",
        lambda settings, snapshot, now=None: seen.append(snapshot["source_project"])
        or telegram_reminder_dispatch.DispatchResult(run_id="x"),
    )
    telegram_reminder_dispatch.dispatch_and_record(object())
    assert seen == ["AMEXPlatSG", "AMEXCentSG"]


def test_centurion_outage_does_not_stop_platinum_dispatch(monkeypatch):
    seen = []

    def unavailable():
        raise telegram_reminder_dispatch.tft_slot_source.SlotSourceUnavailable("down")

    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_snapshot", lambda: snapshot_for("AMEXPlatSG"))
    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_centurion_snapshot", unavailable)
    monkeypatch.setattr(
        telegram_reminder_dispatch,
        "run_dispatch",
        lambda settings, snapshot, now=None: seen.append(snapshot["source_project"])
        or telegram_reminder_dispatch.DispatchResult(run_id="x"),
    )
    telegram_reminder_dispatch.dispatch_and_record(object())
    assert seen == ["AMEXPlatSG"]
    assert telegram_reminder_dispatch.last_dispatch_centurion["error"] == "slot_source_unavailable"


def test_platinum_outage_does_not_stop_centurion_dispatch(monkeypatch):
    seen = []

    def unavailable():
        raise telegram_reminder_dispatch.tft_slot_source.SlotSourceUnavailable("down")

    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_snapshot", unavailable)
    monkeypatch.setattr(telegram_reminder_dispatch.tft_slot_source, "load_centurion_snapshot", lambda: snapshot_for("AMEXCentSG"))
    monkeypatch.setattr(
        telegram_reminder_dispatch,
        "run_dispatch",
        lambda settings, snapshot, now=None: seen.append(snapshot["source_project"])
        or telegram_reminder_dispatch.DispatchResult(run_id="x"),
    )
    telegram_reminder_dispatch.dispatch_and_record(object())
    assert seen == ["AMEXCentSG"]
    assert telegram_reminder_dispatch.last_dispatch["error"] == "slot_source_unavailable"


def test_guide_draft_passes_the_card_through(tmp_path: Path):
    from types import SimpleNamespace

    from app import tft_agent

    captured = {}
    turn = SimpleNamespace(drafter=lambda fields: captured.update(fields) or "ok", user_text="", final=None, outcome=None)
    tft_agent._draft_reminder(tft_agent.DraftArgs(venue="VUE", card="centurion"), turn)
    assert captured["tier"] == "centurion"

    conn = connection(tmp_path / "r.db")
    try:
        reply = telegram_reminders.start_from_fields(
            conn, PRINCIPAL_A, tft_guide.load_catalog(), NOW, captured
        )
        assert "Lunch or dinner?" in reply
        assert conn.execute("SELECT tier FROM telegram_reminder_conversations").fetchone()[0] == "centurion"
    finally:
        conn.close()


def centurion_slot_snapshot(venue_id: str) -> dict:
    snapshot = snapshot_for("AMEXCentSG", venue_id)
    snapshot["venues"][0]["meals"][0]["slots"] = [
        {"date": "2026-09-05", "time": "19:00", "max_seats": 2}
    ]
    return snapshot


def test_slots_centurion_word_reads_centurion_seats(monkeypatch):
    monkeypatch.setattr(
        tft_guide.tft_slot_source, "load_centurion_snapshot", lambda: centurion_slot_snapshot("tft-vue")
    )
    reply = tft_guide.handle_message(
        "/slots VUE dinner centurion", tft_guide.load_catalog(), NOW, slot_loader=fresh_snapshot
    )
    assert "Centurion" in reply
    assert "Sat 5 Sep" in reply
    assert "program=AMEXCentSG" in reply


def test_slots_for_a_centurion_only_venue_needs_no_card_word(monkeypatch):
    monkeypatch.setattr(
        tft_guide.tft_slot_source,
        "load_centurion_snapshot",
        lambda: centurion_slot_snapshot("tft-jaan-by-kirk-westaway"),
    )
    reply = tft_guide.handle_message(
        "/slots JAAN dinner", tft_guide.load_catalog(), NOW, slot_loader=fresh_snapshot
    )
    assert "Centurion" in reply and "Sat 5 Sep" in reply


def test_plain_slots_stay_platinum(monkeypatch):
    monkeypatch.setattr(
        tft_guide.tft_slot_source, "load_centurion_snapshot", lambda: centurion_slot_snapshot("tft-vue")
    )
    reply = tft_guide.handle_message(
        "/slots VUE dinner", tft_guide.load_catalog(), NOW, slot_loader=fresh_snapshot
    )
    assert "Sat 5 Sep" not in reply
    assert "program=AMEXCentSG" not in reply


def test_guide_slot_tool_takes_the_card_and_finds_centurion_only_venues():
    from datetime import date

    from app import tft_agent

    request = tft_agent._slot_request(tft_agent.SlotArgs(card="centurion"), date(2026, 8, 30))
    assert request.tier == "centurion"
    assert tft_agent._venue("JAAN", tft_guide.load_catalog())["id"] == "tft-jaan-by-kirk-westaway"


def test_venue_link_answers_for_a_centurion_only_venue():
    reply = tft_guide.handle_message(
        "/start venue_tft-jaan-by-kirk-westaway", tft_guide.load_catalog(), NOW
    )
    assert "JAAN By Kirk Westaway" in reply
    assert "not in the reviewed TFT roster" not in reply
