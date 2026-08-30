"""Authenticated ingestion and immediate delivery of reviewed owner updates."""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException

from app import db, owner_alert_store, telegram
from app.config import Settings, load_settings
from app.owner_alerts import OwnerAlertRequest, format_owner_alert
from app.observability import log_event


router = APIRouter()
logger = logging.getLogger("amex_reminders.delivery")


def get_settings() -> Settings:
    return load_settings()


def _authenticate(authorization: str | None, settings: Settings) -> None:
    if not settings.owner_alerts_enabled:
        raise HTTPException(status_code=503, detail="Owner alerts are not enabled.")
    expected = f"Bearer {settings.owner_alert_ingest_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/api/owner-alerts/events")
def ingest_owner_events(
    payload: OwnerAlertRequest,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    _authenticate(authorization, settings)
    event = payload.event
    if event.status != "published":
        return {"ok": True, "id": event.id, "state": "withheld"}
    effective_at = event.reviewed_at or event.detected_at
    if settings.owner_alert_not_before and effective_at < settings.owner_alert_not_before:
        return {"ok": True, "id": event.id, "state": "before_activation"}

    conn = db.connect(settings.db_path)
    try:
        claimed = owner_alert_store.claim(
            conn,
            event.id,
            settings.telegram_owner_chat_id,
            event.digest(),
        )
    finally:
        conn.close()
    if claimed.state == "conflict":
        raise HTTPException(
            status_code=409,
            detail=f"Event {event.id} conflicts with its recorded digest.",
        )
    if not claimed.should_send:
        return {
            "ok": True,
            "id": event.id,
            "state": claimed.state,
            "attempt": claimed.attempt_count,
        }

    state = "sent"
    error_code = None
    message_id = None
    started = time.monotonic()
    try:
        message_id = telegram.send_message(
            settings.telegram_bot_token,
            settings.telegram_owner_chat_id,
            format_owner_alert(event, settings.explorer_base_url),
        )
    except telegram.TelegramDeliveryError as exc:
        state = exc.state
        error_code = exc.code

    conn = db.connect(settings.db_path)
    try:
        owner_alert_store.complete(
            conn,
            event.id,
            settings.telegram_owner_chat_id,
            state,
            message_id=message_id,
            error_code=error_code,
        )
    finally:
        conn.close()
    log_event(
        logger,
        "owner_alert_delivery",
        state=state,
        error_code=error_code or "sent",
        attempt=claimed.attempt_count,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    return {
        "ok": True,
        "id": event.id,
        "state": state,
        "attempt": claimed.attempt_count,
        "error_code": error_code,
    }
