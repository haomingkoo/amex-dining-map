from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, telegram_bot_routes, telegram_bot_store, telegram_reminders, tft_agent
from app.config import load_settings
from app.main import app
from app.telegram_bot_routes import get_settings
from tests.agent_helpers import ScriptedChat, call, text
from tests.test_telegram_bot import WEBHOOK_SECRET, _settings, _update

FREE_TEXT = "colony this weekend?"
PRINCIPAL = "user:" + "d" * 64


@pytest.fixture()
def llm_settings(tmp_path: Path):
    settings = replace(
        _settings(tmp_path / "agent.db"),
        telegram_guide_llm_enabled=True,
        gemini_api_key="g" * 40,
        telegram_user_limit_per_minute=1_000,
        telegram_user_limit_per_day=1_000,
    )
    db.init_db(settings.db_path)
    telegram_bot_store.init_db(settings.db_path)
    conn = db.connect(settings.db_path)
    telegram_reminders.init_db(conn)
    conn.close()
    return settings


@pytest.fixture()
def scripted(monkeypatch):
    chats: list[ScriptedChat] = []

    def factory(_key: str) -> ScriptedChat:
        chat = ScriptedChat(call("list_venues"), text("Here are the venues."))
        chats.append(chat)
        return chat

    monkeypatch.setattr(tft_agent, "gemini_chat", factory)
    return chats


def test_llm_disabled_never_builds_a_client(llm_settings, monkeypatch):
    monkeypatch.setattr(tft_agent, "gemini_chat", lambda _key: pytest.fail("LLM must stay off"))

    reply = telegram_bot_routes._guide_answer(
        replace(llm_settings, telegram_guide_llm_enabled=False), PRINCIPAL, FREE_TEXT
    )

    assert reply.startswith("I could not match that")


def test_agent_answers_free_text_and_saves_short_context(llm_settings, scripted):
    reply = telegram_bot_routes._guide_answer(llm_settings, PRINCIPAL, FREE_TEXT)

    assert reply.startswith("Here are the venues.")
    conn = db.connect(llm_settings.db_path)
    assert telegram_bot_store.load_context(conn, PRINCIPAL) == [(FREE_TEXT, reply[:800])]
    conn.close()


def test_slash_command_never_reaches_the_llm(llm_settings, scripted):
    telegram_bot_routes._guide_answer(llm_settings, PRINCIPAL, "/menu noma")

    assert scripted == []


def test_twenty_first_llm_message_of_the_day_is_basic_mode(llm_settings, scripted):
    settings = replace(llm_settings, telegram_llm_user_limit_per_minute=1_000)
    replies = [telegram_bot_routes._guide_answer(settings, PRINCIPAL, FREE_TEXT) for _ in range(21)]

    assert len(scripted) == 20
    assert all(not reply.startswith(telegram_bot_routes.BASIC_MODE) for reply in replies[:20])
    assert replies[20].startswith(telegram_bot_routes.BASIC_MODE)
    assert "I could not match that" in replies[20]


def test_global_llm_cap_applies_across_users(llm_settings, scripted):
    settings = replace(llm_settings, telegram_llm_global_limit_per_day=3)
    replies = [
        telegram_bot_routes._guide_answer(settings, f"user:{index:064d}", FREE_TEXT) for index in range(4)
    ]

    assert len(scripted) == 3
    assert replies[3].startswith(telegram_bot_routes.BASIC_MODE)


def test_drafting_counts_toward_the_llm_budget(llm_settings, monkeypatch):
    settings = replace(
        llm_settings,
        telegram_reminders_enabled=True,
        telegram_reminder_dispatch_token="r" * 43,
        telegram_llm_user_limit_per_day=1,
    )
    monkeypatch.setattr(tft_agent, "gemini_chat", lambda _key: ScriptedChat(call("draft_reminder", venue="VUE")))

    first = telegram_bot_routes._guide_answer(settings, PRINCIPAL, "remind me about VUE")
    conn = db.connect(settings.db_path)
    conn.execute("DELETE FROM telegram_reminder_conversations")
    conn.commit()
    conn.close()
    second = telegram_bot_routes._guide_answer(settings, PRINCIPAL, "remind me about VUE")

    assert first.startswith("Reminder for VUE. Lunch or dinner?")
    assert second.startswith(telegram_bot_routes.BASIC_MODE)


def test_webhook_sends_no_telegram_identity_to_the_llm(llm_settings, scripted, monkeypatch):
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda *args: 1)
    app.dependency_overrides[get_settings] = lambda: llm_settings
    try:
        with TestClient(app) as client:
            client.post(
                "/api/telegram/guide/webhook",
                json=_update(text=FREE_TEXT, user_id=987654321),
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
    finally:
        app.dependency_overrides.clear()

    sent = repr(scripted[0].requests)
    assert "987654321" not in sent and "spoofed" not in sent


def test_delete_me_forgets_context_when_reminders_are_off(llm_settings, scripted, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.telegram_bot_routes.telegram.send_message", lambda _t, _c, body: sent.append(body) or 1)
    telegram_bot_routes._guide_answer(llm_settings, telegram_bot_store.identity_key("user", 4444, "s" * 43), FREE_TEXT)
    app.dependency_overrides[get_settings] = lambda: llm_settings
    try:
        with TestClient(app) as client:
            client.post(
                "/api/telegram/guide/webhook",
                json=_update(text="/delete_me"),
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
    finally:
        app.dependency_overrides.clear()

    conn = db.connect(llm_settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM telegram_guide_context").fetchone()[0] == 0
    conn.close()
    assert sent[-1].startswith("Deleted your recent conversation with the guide.")


def test_context_expires_after_thirty_minutes(llm_settings):
    conn = db.connect(llm_settings.db_path)
    telegram_bot_store.save_exchange(conn, PRINCIPAL, "hi", "hello")
    conn.execute("UPDATE telegram_guide_context SET updated_ts = '2000-01-01T00:00:00+00:00'")
    conn.commit()

    assert telegram_bot_store.load_context(conn, PRINCIPAL) == []
    conn.close()


def test_context_keeps_the_last_three_exchanges(llm_settings):
    conn = db.connect(llm_settings.db_path)
    for index in range(5):
        telegram_bot_store.save_exchange(conn, PRINCIPAL, f"q{index}", f"a{index}")

    assert [user for user, _ in telegram_bot_store.load_context(conn, PRINCIPAL)] == ["q2", "q3", "q4"]
    conn.close()


def _guide_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_GUIDE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_GUIDE_BOT_TOKEN", "987654321:separatepublicbotabcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_GUIDE_WEBHOOK_SECRET", "w" * 43)
    monkeypatch.setenv("TELEGRAM_IDENTITY_HASH_SALT", "s" * 43)
    monkeypatch.setenv("TELEGRAM_GUIDE_LLM_ENABLED", "true")


def test_llm_enabled_without_key_fails_at_startup(monkeypatch):
    _guide_env(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        load_settings()


def test_llm_settings_load_with_key_and_default_limits(monkeypatch):
    _guide_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.Ab8" + "a" * 40)

    settings = load_settings()

    assert settings.telegram_guide_llm_enabled
    assert (
        settings.telegram_llm_user_limit_per_minute,
        settings.telegram_llm_user_limit_per_day,
        settings.telegram_llm_global_limit_per_day,
    ) == (4, 20, 250)


def test_healthz_reports_llm_fallback_counters(llm_settings, monkeypatch):
    tft_agent.reset_stats()
    monkeypatch.setattr(tft_agent, "gemini_chat", lambda _key: ScriptedChat(tft_agent.AgentError("http_503")))
    monkeypatch.setattr("app.main.settings", llm_settings)

    telegram_bot_routes._guide_answer(llm_settings, PRINCIPAL, FREE_TEXT)
    with TestClient(app) as client:
        health = client.get("/healthz").json()

    assert health["feature_state"]["telegram_guide_llm_enabled"] is True
    assert health["telegram_guide_llm"]["fallbacks"] == 1
    assert health["telegram_guide_llm"]["outcomes"] == {"fallback:http_503": 1}
    tft_agent.reset_stats()


def test_over_budget_is_counted_as_a_fallback(llm_settings, scripted):
    tft_agent.reset_stats()
    settings = replace(llm_settings, telegram_llm_global_limit_per_day=1)

    telegram_bot_routes._guide_answer(settings, "user:" + "1" * 64, FREE_TEXT)
    telegram_bot_routes._guide_answer(settings, "user:" + "2" * 64, FREE_TEXT)

    assert tft_agent.stats()["outcomes"] == {"agent": 1, "budget": 1}
    tft_agent.reset_stats()


def test_provider_quota_error_gets_the_same_plain_reply(llm_settings, monkeypatch):
    def quota(_key):
        def chat(*_args):
            raise tft_agent.AgentError("http_429")
        return chat

    monkeypatch.setattr(tft_agent, "gemini_chat", quota)
    reply = telegram_bot_routes._guide_answer(llm_settings, PRINCIPAL, FREE_TEXT)

    assert reply.startswith(telegram_bot_routes.BASIC_MODE)
    assert "/slots, /venue and /remind work as usual." in reply
    assert "I could not match that" in reply


def test_other_agent_failures_keep_the_deterministic_reply(llm_settings, monkeypatch):
    def slow(_key):
        def chat(*_args):
            raise tft_agent.AgentError("timeout")
        return chat

    monkeypatch.setattr(tft_agent, "gemini_chat", slow)
    reply = telegram_bot_routes._guide_answer(llm_settings, PRINCIPAL, FREE_TEXT)

    assert reply.startswith("I could not match that")
