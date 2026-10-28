"""Minimal Telegram Bot API delivery adapter using the standard library."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass


TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramDeliveryError(Exception):
    code: str
    state: str
    retry_after: int | None = None


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    try:
        value = json.loads(exc.read(4_096))["parameters"]["retry_after"]
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return value if isinstance(value, int) and value >= 0 else None


def send_message(
    bot_token: str, chat_id: int, text: str, reply_markup: dict | None = None
) -> int:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(65_537)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise TelegramDeliveryError(
                "telegram_http_429", "retry", _retry_after(exc)
            ) from exc
        if 500 <= exc.code <= 599:
            raise TelegramDeliveryError(f"telegram_http_{exc.code}", "retry") from exc
        raise TelegramDeliveryError(f"telegram_http_{exc.code}", "dead") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise TelegramDeliveryError("telegram_transport_unknown", "unknown") from exc

    try:
        payload = json.loads(raw)
        if payload.get("ok") is not True:
            raise ValueError("Telegram response was not successful")
        message_id = int(payload["result"]["message_id"])
        response_chat_id = int(payload["result"]["chat"]["id"])
        if response_chat_id != int(chat_id):
            raise ValueError("Telegram response destination did not match")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramDeliveryError("telegram_response_unknown", "unknown") from exc
    return message_id


def answer_callback_query(bot_token: str, callback_query_id: str) -> None:
    """Stop the button's loading spinner. Best effort: the reply message is what matters."""
    request = urllib.request.Request(
        f"{TELEGRAM_API_BASE}/bot{bot_token}/answerCallbackQuery",
        data=json.dumps({"callback_query_id": callback_query_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read(4_096)
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise TelegramDeliveryError("telegram_callback_unknown", "unknown") from exc
