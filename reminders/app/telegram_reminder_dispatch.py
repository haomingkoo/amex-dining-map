"""Telegram reminder delivery run, shared by the internal route and the in-process loop."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import db, telegram, telegram_reminders, tft_slot_source
from app.config import Settings
from app.observability import log_event


# Live slots refresh every few minutes; the Pages-triggered route ran about once a day.
DISPATCH_INTERVAL_SECONDS = 300
logger = logging.getLogger("amex_reminders.delivery")

last_dispatch: dict[str, str | int | None] = {
    "at": None,
    "sent": None,
    "unknown": None,
    "dead": None,
    "error": None,
}


@dataclass
class DispatchResult:
    run_id: str
    claimed: int = 0
    sent: int = 0
    unknown: int = 0
    dead: int = 0
    skipped: int = 0
    more: bool = False
    error_code: str | None = None
    claim_failed: bool = False


def _record(result: DispatchResult) -> None:
    last_dispatch.update(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sent=result.sent,
        unknown=result.unknown,
        dead=result.dead,
        error=result.error_code,
    )


def log_dead_run(run_id: str, error_code: str, started: float) -> None:
    log_event(
        logger,
        "telegram_reminder_run",
        run_id=run_id,
        state="dead",
        error_code=error_code,
        active_scanned_count=0,
        matched_count=0,
        no_match_count=0,
        stale_venue_count=0,
        expired_count=0,
        reconciled_claimed_count=0,
        reconciled_unknown_count=0,
        batch_limited=False,
        claimed_count=0,
        sent_count=0,
        unknown_count=0,
        dead_count=0,
        skipped_count=0,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def run_dispatch(
    settings: Settings, snapshot: dict[str, Any], now: datetime | None = None
) -> DispatchResult:
    """Claim matching reminders and send each at most once; blocking."""
    started = time.monotonic()
    result = DispatchResult(run_id=secrets.token_hex(8))
    try:
        conn = db.connect(settings.db_path)
        try:
            claim_result = telegram_reminders.claim_notifications(
                conn, snapshot, now or datetime.now(timezone.utc)
            )
        finally:
            conn.close()
    except Exception:
        log_dead_run(result.run_id, "store_unavailable", started)
        result.error_code, result.claim_failed = "store_unavailable", True
        _record(result)
        return result
    store_failed = False
    receipt_conflicts = 0
    for notification in claim_result.notifications:
        delivery_started = time.monotonic()
        try:
            conn = db.connect(settings.db_path)
            try:
                should_send = telegram_reminders.begin_notification(
                    conn,
                    notification.reminder_id,
                    notification.chat_id,
                    datetime.now(timezone.utc),
                )
            finally:
                conn.close()
        except Exception:
            store_failed = True
            log_event(
                logger,
                "telegram_reminder_delivery",
                run_id=result.run_id,
                state="dead",
                error_code="store_unavailable",
                duration_ms=round((time.monotonic() - delivery_started) * 1000),
            )
            break
        if not should_send:
            result.skipped += 1
            continue
        try:
            message_id = telegram.send_message(
                settings.telegram_guide_bot_token,
                notification.chat_id,
                notification.text,
            )
            state, code = "done", "sent"
            result.sent += 1
        except telegram.TelegramDeliveryError as exc:
            state = "unknown" if exc.state in {"unknown", "retry"} else "dead"
            code = exc.code
            message_id = None
            if state == "unknown":
                result.unknown += 1
            else:
                result.dead += 1
        try:
            conn = db.connect(settings.db_path)
            try:
                telegram_reminders.complete_notification(
                    conn,
                    notification.reminder_id,
                    state,
                    code,
                    datetime.now(timezone.utc),
                    message_id,
                )
            finally:
                conn.close()
        except Exception:
            receipt_conflicts += 1
            log_event(
                logger,
                "telegram_reminder_delivery",
                run_id=result.run_id,
                state="unknown",
                error_code="receipt_conflict",
                duration_ms=round((time.monotonic() - delivery_started) * 1000),
            )
            continue
        log_event(
            logger,
            "telegram_reminder_delivery",
            run_id=result.run_id,
            state=state,
            error_code=code,
            duration_ms=round((time.monotonic() - delivery_started) * 1000),
        )
    result.claimed = len(claim_result.notifications)
    result.more = claim_result.more_matches
    if store_failed:
        result.error_code = "store_unavailable"
    elif receipt_conflicts:
        result.error_code = "receipt_conflict"
    log_event(
        logger,
        "telegram_reminder_run",
        run_id=result.run_id,
        state="dead" if result.error_code else "done",
        error_code=result.error_code or "completed",
        active_scanned_count=claim_result.active_scanned_count,
        matched_count=claim_result.matched_count,
        no_match_count=claim_result.no_match_count,
        stale_venue_count=claim_result.stale_venue_count,
        expired_count=claim_result.expired_count,
        reconciled_claimed_count=claim_result.reconciled_claimed_count,
        reconciled_unknown_count=claim_result.reconciled_unknown_count,
        batch_limited=claim_result.batch_limited,
        claimed_count=result.claimed,
        sent_count=result.sent,
        unknown_count=result.unknown,
        dead_count=result.dead,
        skipped_count=result.skipped,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    _record(result)
    return result


def dispatch_and_record(settings: Settings) -> None:
    """One in-process run for the periodic loop; logs and records, never raises."""
    started = time.monotonic()
    run_id = secrets.token_hex(8)
    try:
        snapshot = tft_slot_source.load_snapshot()
    except tft_slot_source.SlotSourceUnavailable:
        log_dead_run(run_id, "slot_source_unavailable", started)
        _record(DispatchResult(run_id=run_id, error_code="slot_source_unavailable"))
        return
    try:
        run_dispatch(settings, snapshot)
    except Exception:
        log_dead_run(run_id, "internal_error", started)
        _record(DispatchResult(run_id=run_id, error_code="internal_error"))
