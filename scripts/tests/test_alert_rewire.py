from __future__ import annotations

import importlib.util
import json
import sys
from email.message import EmailMessage
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "send_table_for_two_alerts.py"
_spec = importlib.util.spec_from_file_location("alerts_mod", MODULE_PATH)
alerts = importlib.util.module_from_spec(_spec)
sys.modules["alerts_mod"] = alerts
_spec.loader.exec_module(alerts)


class _Resp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_api_subscriptions_parses_export(monkeypatch):
    payload = {
        "subscriptions": [
            {
                "email": "a@example.com",
                "name": "Al",
                "party_size": 2,
                "sessions": ["Dinner"],
                "venues": ["any"],
                "date_start": "2026-07-01",
                "date_end": "2026-07-10",
                "unsubscribe_url": "https://svc/api/unsubscribe?token=z",
            }
        ]
    }
    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _Resp(payload)

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    subs = alerts.fetch_api_subscriptions("https://svc", "tok", {})

    assert captured["url"] == "https://svc/api/subscribers"
    assert captured["auth"] == "Bearer tok"
    assert len(subs) == 1
    assert subs[0].email == "a@example.com"
    assert subs[0].unsubscribe_url == "https://svc/api/unsubscribe?token=z"


def test_send_resend_message_builds_payload(monkeypatch):
    message = EmailMessage()
    message["Subject"] = "Table for Two alert"
    message["From"] = "dinnertime@kooexperience.com"
    message["To"] = "a@example.com"
    message["List-Unsubscribe"] = "<https://svc/api/unsubscribe?token=z>"
    message.set_content("text body")
    message.add_alternative("<p>html body</p>", subtype="html")
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["idempotency"] = req.get_header("Idempotency-key")
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _Resp({"id": "abc"})

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    alerts._send_resend_message(
        message,
        {"api_key": "re_key", "sender": "dinnertime@kooexperience.com", "timeout": 30},
        "abc123",
    )

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_key"
    assert captured["idempotency"] == "tft-alert-abc123"
    assert captured["data"]["subject"] == "Table for Two alert"
    assert captured["data"]["to"] == ["a@example.com"]
    assert "html body" in captured["data"]["html"]
    assert captured["data"]["headers"]["List-Unsubscribe"] == (
        "<https://svc/api/unsubscribe?token=z>"
    )


def test_send_messages_persists_each_confirmed_receipt_before_next_send(tmp_path, monkeypatch):
    messages = []
    for recipient in ("first@example.com", "second@example.com"):
        message = EmailMessage()
        message["Subject"] = "Table for Two alert"
        message["From"] = "dinnertime@kooexperience.com"
        message["To"] = recipient
        message.set_content("body")
        messages.append(message)
    calls = []

    def send(message, config, key):
        calls.append((message["To"], key))
        if len(calls) == 2:
            raise RuntimeError("second failed")

    monkeypatch.setattr(alerts, "_send_resend_message", send)
    sent_log = tmp_path / "sent.json"

    try:
        alerts.send_messages(
            messages,
            ["first-key", "second-key"],
            {"api_key": "re_key", "sender": "sender@example.com"},
            sent_log,
            {},
        )
    except RuntimeError:
        pass

    persisted = json.loads(sent_log.read_text())
    assert "first-key" in persisted["sent_keys"]
    assert "second-key" not in persisted["sent_keys"]
