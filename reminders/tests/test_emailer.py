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
        text="hi",
    )

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"
    assert captured["data"]["from"] == "Table for Two alerts <dinnertime@kooexperience.com>"
    assert captured["data"]["reply_to"] == "privacy@kooexperience.com"
    assert captured["data"]["text"] == "hi"
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


def test_send_email_discards_provider_body_on_non_2xx(monkeypatch):
    def fake_urlopen(req, timeout=30):
        return _FakeResp(500, b'guest@example.com secret-manage-token')

    monkeypatch.setattr(emailer.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(emailer.EmailDeliveryError) as raised:
        emailer.send_email(
            "x@example.com", "s", "<p>h</p>", api_key="k", sender="f@example.com"
        )
    assert str(raised.value) == "email delivery failed (provider_status_500)"
    assert "guest@example.com" not in str(raised.value)
    assert "secret-manage-token" not in str(raised.value)


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


def test_confirmation_email_footer_has_privacy_link_and_contact():
    html = emailer.confirm_email_html(None, "https://svc/c", "https://svc/u")

    assert emailer.PRIVACY_URL in html
    assert "Questions or data requests: <a href=\"mailto:privacy@kooexperience.com\"" in html


def test_confirm_email_text_carries_the_same_links_as_html():
    args = ("Al", "https://svc/c?token=a", "https://svc/u", "https://svc/m", True)

    text = emailer.confirm_email_text(*args)
    html = emailer.confirm_email_html(*args)

    for url in ("https://svc/c?token=a", "https://svc/u", "https://svc/m", emailer.PRIVACY_URL):
        assert url in text
        assert url in html
    assert "Good news" in text
    assert "<" not in text


def test_confirm_email_html_has_no_external_assets():
    html = emailer.confirm_email_html("Al", "https://svc/c", "https://svc/u", "https://svc/m")

    assert "<img" not in html
    assert "<link" not in html
    assert "fonts.googleapis" not in html
    assert html.count(">https://svc/c</a>") == 1  # raw link text matches its href
