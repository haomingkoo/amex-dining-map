"""Email sending via the Resend HTTP API (no SDK), ported from trader-koo."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.utils import formataddr, parseaddr
from html import escape

RESEND_ENDPOINT = "https://api.resend.com/emails"
PRIVACY_URL = "https://amex-explorer.kooexperience.com/privacy.html"
PRIVACY_EMAIL = "privacy@kooexperience.com"
SENDER_NAME = "Table for Two alerts"


class EmailDeliveryError(RuntimeError):
    """A provider failure whose message is safe to expose to server logs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"email delivery failed ({code})")


def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    api_key: str,
    sender: str,
    list_unsubscribe_url: str | None = None,
    text: str | None = None,
    timeout: int = 30,
) -> None:
    """Send one HTML email through Resend. Provider responses are never retained."""
    payload: dict = {
        "from": formataddr((SENDER_NAME, parseaddr(sender)[1])),
        "to": [to],
        "subject": subject,
        "html": html,
        "reply_to": PRIVACY_EMAIL,
    }
    if text:
        payload["text"] = text
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
            resp.read()
        if status >= 300:
            raise EmailDeliveryError(f"provider_status_{status}")
    except urllib.error.HTTPError as exc:
        exc.read()
        raise EmailDeliveryError(f"provider_http_{exc.code}") from None
    except urllib.error.URLError:
        raise EmailDeliveryError("provider_unreachable") from None


def _shell(
    title: str, body_html: str, unsubscribe_url: str, manage_url: str | None = None
) -> str:
    safe_title = escape(title)
    safe_unsubscribe_url = escape(unsubscribe_url, quote=True)
    link = 'style="color:#8a7a5c"'
    manage_link = (
        f'<a href="{escape(manage_url, quote=True)}" {link}>Manage your reminders</a> &middot; '
        if manage_url
        else ""
    )
    return f"""\
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{safe_title}</title></head><body style="margin:0">
<div style="background:#f6f2ea;padding:24px 12px">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #eadfc8;border-radius:14px;
 padding:28px 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#26303d">
  <p style="margin:0 0 10px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#a8843f;font-weight:600">Table for Two reminders</p>
  <h1 style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:26px;line-height:1.15;font-weight:600;color:#0b1624">{safe_title}</h1>
  {body_html}
  <p style="margin:24px 0 0;padding-top:14px;border-top:1px solid #efe7d6;font-size:12px;line-height:1.5;color:#8a7a5c">
    An independent tool for Amex Platinum cardholders in Singapore. Not affiliated with American Express.<br>
    {manage_link}<a href="{safe_unsubscribe_url}" {link}>Unsubscribe</a> &middot; <a href="{PRIVACY_URL}" {link}>Privacy</a><br>
    Questions or data requests: <a href="mailto:{PRIVACY_EMAIL}" {link}>{PRIVACY_EMAIL}</a>
  </p>
</div></div>
</body></html>"""


def confirm_email_html(
    name: str | None,
    confirm_url: str,
    unsubscribe_url: str,
    manage_url: str | None = None,
    matches_exist: bool = False,
) -> str:
    greeting = f"Hi {escape(name)}," if name else "Hi,"
    safe_confirm_url = escape(confirm_url, quote=True)
    good_news = (
        '<p style="font-size:15px;line-height:1.5;margin:0 0 16px;padding:12px 14px;'
        'background:#f3ecdc;border-radius:10px;color:#5c4a22">Good news: tables are already '
        "open at venues you picked. Confirm and we'll send them over.</p>"
        if matches_exist
        else ""
    )
    body = f"""\
  {good_news}
  <p style="font-size:15px;line-height:1.5;margin:0 0 18px">{greeting} confirm your email and
     we'll let you know when a Table for Two slot matches your request.</p>
  <p style="margin:0 0 20px">
    <a href="{safe_confirm_url}"
       style="display:inline-block;background:#0b1624;color:#f2e6c9;text-decoration:none;
              padding:12px 20px;border-radius:10px;font-weight:600;font-size:15px">Confirm my email</a>
  </p>
  <p style="font-size:13px;line-height:1.5;color:#5b6575;margin:0 0 16px;word-break:break-all">Or open
     this link: <a href="{safe_confirm_url}" style="color:#5b6575">{safe_confirm_url}</a></p>
  <p style="font-size:13px;line-height:1.5;color:#5b6575;margin:0">Didn't sign up? Ignore this
     email and nothing more will be sent.</p>"""
    return _shell("One last step", body, unsubscribe_url, manage_url)


def confirm_email_text(
    name: str | None,
    confirm_url: str,
    unsubscribe_url: str,
    manage_url: str | None = None,
    matches_exist: bool = False,
) -> str:
    """Plain-text twin of confirm_email_html."""
    lines = [f"Hi {name}," if name else "Hi,", ""]
    if matches_exist:
        lines += [
            "Good news: tables are already open at venues you picked. "
            "Confirm and we'll send them over.",
            "",
        ]
    lines += [
        "Confirm your email and we'll let you know when a Table for Two slot "
        "matches your request:",
        "",
        confirm_url,
        "",
        "Didn't sign up? Ignore this email and nothing more will be sent.",
        "",
        "--",
        "An independent tool for Amex Platinum cardholders in Singapore. "
        "Not affiliated with American Express.",
    ]
    if manage_url:
        lines.append(f"Manage your reminders: {manage_url}")
    lines += [
        f"Unsubscribe: {unsubscribe_url}",
        f"Privacy: {PRIVACY_URL}",
        f"Questions or data requests: {PRIVACY_EMAIL}",
    ]
    return "\n".join(lines) + "\n"
