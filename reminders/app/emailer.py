"""Email sending via the Resend HTTP API (no SDK), ported from trader-koo."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    api_key: str,
    sender: str,
    list_unsubscribe_url: str | None = None,
    timeout: int = 30,
) -> None:
    """Send one HTML email through Resend. Raises RuntimeError on failure."""
    payload: dict = {"from": sender, "to": [to], "subject": subject, "html": html}
    if list_unsubscribe_url:
        payload["headers"] = {
            "List-Unsubscribe": f"<{list_unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    req = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "amex-reminders/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
        if status >= 300:
            raise RuntimeError(f"Resend API failed status={status} body={body[:500]}")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API HTTP {exc.code}: {err_body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Resend connect failed: {exc.reason}") from exc


def _shell(
    title: str, body_html: str, unsubscribe_url: str, manage_url: str | None = None
) -> str:
    manage_link = (
        f'<a href="{manage_url}" style="color:#8a94a6">Manage your reminders</a> · '
        if manage_url
        else ""
    )
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:480px;margin:0 auto;padding:24px;color:#1a2332">
  <h1 style="font-size:20px;margin:0 0 16px">{title}</h1>
  {body_html}
  <hr style="border:none;border-top:1px solid #e5e9f0;margin:24px 0 12px">
  <p style="font-size:12px;color:#8a94a6;margin:0">
    Table for Two reminders · Unofficial Platinum Experience.<br>
    {manage_link}<a href="{unsubscribe_url}" style="color:#8a94a6">Unsubscribe</a>.
  </p>
</div>"""


def confirm_email_html(
    name: str | None,
    confirm_url: str,
    unsubscribe_url: str,
    manage_url: str | None = None,
) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    body = f"""\
  <p style="font-size:15px;line-height:1.5;margin:0 0 16px">{greeting} please confirm
     your email to start receiving Table for Two availability reminders.</p>
  <p style="margin:0 0 20px">
    <a href="{confirm_url}"
       style="display:inline-block;background:#1a2332;color:#fff;text-decoration:none;
              padding:12px 22px;border-radius:8px;font-size:15px">Confirm my email</a>
  </p>
  <p style="font-size:13px;color:#8a94a6;margin:0">If you didn't request this, ignore
     this email — nothing will be sent.</p>"""
    return _shell("Confirm your Table for Two reminders", body, unsubscribe_url, manage_url)
