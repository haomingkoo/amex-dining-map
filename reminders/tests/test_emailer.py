from __future__ import annotations

import json

import pytest

from app import emailer


class _FakeResp:
    def __init__(self, status: int = 200, body: bytes = b"{}"):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_send_email_posts_to_resend(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(200)

    monkeypatch.setattr(emailer.urllib.request, "urlopen", fake_urlopen)

    emailer.send_email(
        "guest@example.com",
        "Confirm",
        "<p>hi</p>",
        api_key="re_test_key",
        sender="dinnertime@kooexperience.com",
        list_unsubscribe_url="https://svc/api/unsubscribe?token=z",
    )

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"
    assert captured["data"]["from"] == "dinnertime@kooexperience.com"
    assert captured["data"]["to"] == ["guest@example.com"]
    assert captured["data"]["subject"] == "Confirm"
    assert "List-Unsubscribe" in captured["data"]["headers"]


def test_confirmation_email_escapes_name_and_links():
    html = emailer.confirm_email_html(
        '<img src=x onerror="alert(1)">',
        'https://svc/confirm?token=a&next="bad"',
        "https://svc/unsubscribe?token=a&b=1",
    )

    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert 'token=a&amp;next=&quot;bad&quot;' in html


def test_send_email_raises_on_non_2xx(monkeypatch):
    def fake_urlopen(req, timeout=30):
        return _FakeResp(500, b'{"error":"boom"}')

    monkeypatch.setattr(emailer.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError):
        emailer.send_email(
            "x@example.com", "s", "<p>h</p>", api_key="k", sender="f@example.com"
        )


def test_confirm_email_html_contains_links():
    html = emailer.confirm_email_html(
        "Alice",
        "https://svc/api/confirm?token=abc",
        "https://svc/api/unsubscribe?token=xyz",
    )

    assert "https://svc/api/confirm?token=abc" in html
    assert "https://svc/api/unsubscribe?token=xyz" in html
    assert "Alice" in html
    assert "Confirm my email" in html  # full body survived the good-news prepend


def test_confirm_email_html_shows_matches_only_when_present():
    without = emailer.confirm_email_html("Al", "c", "u", "m", matches_exist=False)
    with_matches = emailer.confirm_email_html("Al", "c", "u", "m", matches_exist=True)

    assert "Good news" not in without
    assert "Good news" in with_matches
