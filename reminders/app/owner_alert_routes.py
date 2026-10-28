"""Authenticated ingestion and immediate delivery of reviewed owner updates."""

from __future__ import annotations

import hmac
import logging
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from app import db, owner_alert_store, telegram
from app.config import Settings, load_settings
from app.owner_alerts import (
    OwnerAlertBatchRequest,
    OwnerAlertEvent,
    OwnerAlertRequest,
    format_owner_alert,
    format_owner_digest,
)
from app.observability import log_event


router = APIRouter()
logger = logging.getLogger("amex_reminders.delivery")
SAFE_EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
FAILURE_STATES = {"retry", "unknown", "dead", "conflict"}


def _level(state: str) -> int:
    return logging.WARNING if state in FAILURE_STATES else logging.INFO


def get_settings() -> Settings:
    return load_settings()


def _authenticate(authorization: str | None, settings: Settings) -> None:
    if not settings.owner_alerts_enabled:
        raise HTTPException(status_code=503, detail="Owner alerts are not enabled.")
    expected = f"Bearer {settings.owner_alert_ingest_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/api/owner-alerts/events")
async def ingest_owner_events(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    _authenticate(authorization, settings)
    try:
        payload = OwnerAlertRequest.model_validate(await request.json())
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(status_code=422, detail="Invalid owner alert payload.")
    event = payload.event
    event_ref = event.digest()[:12]
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
        log_event(
            logger,
            "owner_alert_delivery",
            level=logging.WARNING,
            event_ref=event_ref,
            state="conflict",
            error_code="digest_conflict",
            attempt=claimed.attempt_count,
            duration_ms=0,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Event {event.id} conflicts with its recorded digest.",
        )
    if not claimed.should_send:
        log_event(
            logger,
            "owner_alert_delivery",
            level=_level(claimed.state),
            event_ref=event_ref,
            state=claimed.state,
            error_code="stale_sending" if claimed.state == "unknown" else "deduplicated",
            attempt=claimed.attempt_count,
            duration_ms=0,
        )
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
        level=_level(state),
        event_ref=event_ref,
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


@router.post("/api/owner-alerts/batch")
async def ingest_owner_batch(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    _authenticate(authorization, settings)
    try:
        payload = OwnerAlertBatchRequest.model_validate(await request.json())
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(status_code=422, detail="Invalid owner alert batch payload.")
    chat_id = settings.telegram_owner_chat_id
    results: list[dict] = []
    counts = dict.fromkeys(
        (
            "withheld",
            "before_activation",
            "deduplicated",
            "conflict",
            "schema_rejected",
            "unidentified_rejected",
        ),
        0,
    )
    pending: list[tuple[OwnerAlertEvent, int]] = []
    seen: set[str] = set()
    conn = db.connect(settings.db_path)
    try:
        for raw in payload.events:
            try:
                event = OwnerAlertEvent.model_validate(raw)
            except ValidationError:
                raw_id = raw.get("id") if isinstance(raw, dict) else None
                if isinstance(raw_id, str) and SAFE_EVENT_ID.fullmatch(raw_id):
                    results.append({"id": raw_id, "state": "schema_rejected"})
                    counts["schema_rejected"] += 1
                else:
                    counts["unidentified_rejected"] += 1
                continue
            if event.id in seen:
                results.append(
                    {"id": event.id, "state": "conflict", "error_code": "duplicate_in_batch"}
                )
                counts["conflict"] += 1
                continue
            seen.add(event.id)
            if event.status != "published":
                results.append({"id": event.id, "state": "withheld"})
                counts["withheld"] += 1
                continue
            effective_at = event.reviewed_at or event.detected_at
            if settings.owner_alert_not_before and effective_at < settings.owner_alert_not_before:
                results.append({"id": event.id, "state": "before_activation"})
                counts["before_activation"] += 1
                continue
            claimed = owner_alert_store.claim(conn, event.id, chat_id, event.digest())
            if claimed.state == "conflict":
                results.append(
                    {"id": event.id, "state": "conflict", "error_code": "digest_conflict"}
                )
                counts["conflict"] += 1
            elif not claimed.should_send:
                results.append({"id": event.id, "state": claimed.state})
                counts["deduplicated"] += 1
            else:
                results.append({"id": event.id, "state": "sending"})
                pending.append((event, len(results) - 1))
    finally:
        conn.close()

    state = "sent" if pending else "nothing_to_send"
    error_code = None
    retry_after = None
    message_id = None
    started = time.monotonic()
    if pending:
        try:
            message_id = telegram.send_message(
                settings.telegram_bot_token,
                chat_id,
                format_owner_digest([event for event, _ in pending], settings.explorer_base_url),
            )
        except telegram.TelegramDeliveryError as exc:
            state = exc.state
            error_code = exc.code
            retry_after = exc.retry_after
        conn = db.connect(settings.db_path)
        try:
            for event, index in pending:
                owner_alert_store.complete(
                    conn,
                    event.id,
                    chat_id,
                    state,
                    message_id=message_id,
                    error_code=error_code,
                )
                results[index] = {"id": event.id, "state": state}
                if error_code:
                    results[index]["error_code"] = error_code
        finally:
            conn.close()
    message_count = 1 if state == "sent" else 0
    log_event(
        logger,
        "owner_alert_digest",
        level=(
            logging.WARNING
            if state in FAILURE_STATES or counts["conflict"] or counts["schema_rejected"]
            or counts["unidentified_rejected"]
            else logging.INFO
        ),
        state=state,
        error_code=error_code or state,
        retry_after=retry_after,
        received=len(payload.events),
        claimed=len(pending),
        message_count=message_count,
        duration_ms=round((time.monotonic() - started) * 1000),
        **counts,
    )
    return {"ok": True, "results": results, "message_count": message_count}
