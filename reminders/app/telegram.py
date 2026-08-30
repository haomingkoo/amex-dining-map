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


def send_message(bot_token: str, chat_id: int, text: str) -> int:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
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
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise TelegramDeliveryError(f"telegram_http_{exc.code}", "retry") from exc
        raise TelegramDeliveryError(f"telegram_http_{exc.code}", "dead") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise TelegramDeliveryError("telegram_transport_unknown", "unknown") from exc

    try:
        payload = json.loads(raw)
        if payload.get("ok") is not True:
            raise ValueError("Telegram response was not successful")
        message_id = int(payload["result"]["message_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramDeliveryError("telegram_response_unknown", "unknown") from exc
    return message_id
