from __future__ import annotations

import json

import pytest

from app import telegram


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode()


def test_send_message_requires_telegram_to_confirm_exact_destination(monkeypatch):
    monkeypatch.setattr(
        telegram.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {"ok": True, "result": {"message_id": 91, "chat": {"id": -1001234567890}}}
        ),
    )

    assert telegram.send_message("123:abcdefghijklmnopqrstuvwxyz", -1001234567890, "test") == 91


def test_destination_mismatch_is_ambiguous_and_never_reported_sent(monkeypatch):
    monkeypatch.setattr(
        telegram.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {"ok": True, "result": {"message_id": 91, "chat": {"id": -1009999999999}}}
        ),
    )

    with pytest.raises(telegram.TelegramDeliveryError) as exc_info:
        telegram.send_message("123:abcdefghijklmnopqrstuvwxyz", -1001234567890, "test")
    assert exc_info.value.code == "telegram_response_unknown"
    assert exc_info.value.state == "unknown"


def test_missing_response_chat_is_ambiguous(monkeypatch):
    monkeypatch.setattr(
        telegram.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {"ok": True, "result": {"message_id": 91}}
        ),
    )

    with pytest.raises(telegram.TelegramDeliveryError, match="telegram_response_unknown"):
        telegram.send_message("123:abcdefghijklmnopqrstuvwxyz", -1001234567890, "test")
