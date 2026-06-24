"""HTTP endpoints: subscribe, confirm, unsubscribe, and subscriber export."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import db
from app.config import Settings, load_settings
from app.emailer import confirm_email_html, send_email
from app.schemas import SubscribeRequest

router = APIRouter()

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_MIN = 60


def get_settings() -> Settings:
    return load_settings()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _page(title: str, message: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
             background:#070d16;color:#e8edf5;display:flex;min-height:100vh;
             align-items:center;justify-content:center;margin:0">
  <div style="max-width:420px;padding:32px;text-align:center">
    <h1 style="font-size:22px;margin:0 0 12px">{title}</h1>
    <p style="font-size:15px;line-height:1.5;color:#aab4c4;margin:0 0 20px">{message}</p>
    <a href="https://amex-explorer.kooexperience.com/#/table-for-two"
       style="color:#7aa2ff">Back to Table for Two</a>
  </div></body></html>"""


@router.post("/api/subscribe")
def subscribe(
    payload: SubscribeRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    success = {"ok": True, "message": "Check your email to confirm your reminder."}
    if payload.website.strip():  # honeypot — pretend success, do nothing
        return success

    ip = client_ip(request)
    sub_input = payload.to_input()
    conn = db.connect(settings.db_path)
    try:
        recent = db.count_recent_events(
            conn, ip, "subscribe_attempt", RATE_LIMIT_WINDOW_MIN
        )
        if recent >= RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429, detail="Too many attempts; please try again later."
            )
        db.log_event(conn, ip, "subscribe_attempt")
        confirm_token = db.upsert_pending(
            conn, sub_input, ip, settings.confirm_token_expiry_hours
        )
        unsub_token = conn.execute(
            "SELECT unsubscribe_token FROM subscribers WHERE email = ?",
            (sub_input.email,),
        ).fetchone()["unsubscribe_token"]
    finally:
        conn.close()

    confirm_url = f"{settings.public_base_url}/api/confirm?token={confirm_token}"
    unsub_url = f"{settings.public_base_url}/api/unsubscribe?token={unsub_token}"
    send_email(
        sub_input.email,
        "Confirm your Table for Two reminders",
        confirm_email_html(sub_input.name, confirm_url, unsub_url),
        api_key=settings.resend_api_key,
        sender=settings.resend_from,
        list_unsubscribe_url=unsub_url,
    )
    return success


@router.get("/api/confirm", response_class=HTMLResponse)
def confirm(token: str = "", settings: Settings = Depends(get_settings)) -> HTMLResponse:
    conn = db.connect(settings.db_path)
    try:
        ok = db.confirm(conn, token)
    finally:
        conn.close()
    if ok:
        return HTMLResponse(
            _page(
                "You're subscribed",
                "We'll email you when a Table for Two slot matches your request.",
            )
        )
    return HTMLResponse(
        _page(
            "Link expired or invalid",
            "Please sign up again from the Table for Two page.",
        ),
        status_code=400,
    )


@router.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    token: str = "", settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    conn = db.connect(settings.db_path)
    try:
        ok = db.unsubscribe(conn, token)
    finally:
        conn.close()
    if ok:
        return HTMLResponse(
            _page("Unsubscribed", "You won't receive any more Table for Two reminders.")
        )
    return HTMLResponse(
        _page("Invalid link", "This unsubscribe link is not valid."), status_code=400
    )


@router.get("/api/subscribers")
def subscribers(
    authorization: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> dict:
    provided = authorization.removeprefix("Bearer ").strip()
    if not settings.alert_export_token or not hmac.compare_digest(
        provided, settings.alert_export_token
    ):
        raise HTTPException(status_code=401, detail="unauthorized")
    conn = db.connect(settings.db_path)
    try:
        rows = db.active_subscribers(conn)
    finally:
        conn.close()
    subscriptions = []
    for row in rows:
        token = row.pop("unsubscribe_token")
        row["unsubscribe_url"] = (
            f"{settings.public_base_url}/api/unsubscribe?token={token}"
        )
        subscriptions.append(row)
    return {"subscriptions": subscriptions}
