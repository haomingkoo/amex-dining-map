"""Authenticated, private-chat-only Telegram guide webhook."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app import (
    db,
    telegram,
    telegram_bot_store,
    telegram_reminders,
    tft_guide,
    tft_slot_source,
)
from app.config import Settings, load_settings
from app.observability import log_event


BOT_SCOPE = "tft-guide-v1"
router = APIRouter()
logger = logging.getLogger("amex_reminders.delivery")


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    is_bot: bool = False


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    type: Literal["private", "group", "supergroup", "channel"]


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    message_id: Annotated[int, Field(gt=0)]
    date: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    chat: TelegramChat
    sender: TelegramUser | None = Field(default=None, alias="from")
    text: Annotated[str | None, Field(max_length=512)] = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    update_id: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    message: TelegramMessage | None = None


class ReminderDispatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generated_at: Annotated[str, Field(min_length=20, max_length=40)]


def get_settings() -> Settings:
    return load_settings()


def _finish(settings: Settings, update_id: int, state: str, code: str, message_id=None):
    conn = db.connect(settings.db_path)
    try:
        telegram_bot_store.complete_update(
            conn, BOT_SCOPE, update_id, state, code, message_id
        )
    finally:
        conn.close()


def _discard(settings: Settings, update_id: int) -> None:
    conn = db.connect(settings.db_path)
    try:
        telegram_bot_store.discard_update(conn, BOT_SCOPE, update_id)
    finally:
        conn.close()


def _reminder_answer(
    settings: Settings,
    principal_key: str,
    chat_id: int,
    text: str,
    now: datetime,
) -> str | None:
    conn = db.connect(settings.db_path)
    try:
        return telegram_reminders.handle_message(
            conn,
            principal_key,
            chat_id,
            text,
            tft_guide.load_catalog(),
            now,
        )
    finally:
        conn.close()


@router.post("/api/telegram/guide/webhook")
async def telegram_guide_webhook(
    request: Request,
    webhook_secret: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    if not settings.telegram_guide_enabled:
        raise HTTPException(status_code=503, detail="Telegram guide is not enabled.")
    if not webhook_secret or not hmac.compare_digest(
        webhook_secret, settings.telegram_guide_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw = await request.body()
        payload = TelegramUpdate.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, UnicodeDecodeError):
        return {"ok": True}

    message = payload.message
    if (
        message is None
        or message.chat.type != "private"
        or message.sender is None
        or message.sender.is_bot
        or message.chat.id != message.sender.id
        or not message.text
        or len(message.text.encode("utf-8")) > 2_048
        or message.date < datetime.now(timezone.utc).timestamp() - 600
        or message.date > datetime.now(timezone.utc).timestamp() + 300
    ):
        return {"ok": True}

    conn = db.connect(settings.db_path)
    try:
        claimed = telegram_bot_store.claim_update(conn, BOT_SCOPE, payload.update_id)
    finally:
        conn.close()
    if not claimed.should_process:
        if claimed.state == "unknown":
            log_event(
                logger,
                "telegram_guide_delivery",
                command_class="replay",
                state="unknown",
                error_code="stale_processing",
                duration_ms=0,
            )
        return {"ok": True}

    started = time.monotonic()
    first_word = message.text.strip().split(maxsplit=1)[0].lower()
    command_class = (
        first_word
        if first_word in {
            "/start", "/help", "/venues", "/menu", "/release", "/slots",
            "/remind", "/reminders", "/cancel", "/delete_me",
        }
        else "query"
    )

    user_key = telegram_bot_store.identity_key(
        "user", message.sender.id, settings.telegram_identity_hash_salt
    )
    current = datetime.now(timezone.utc)
    conn = db.connect(settings.db_path)
    try:
        management = (
            settings.telegram_reminders_enabled
            and telegram_reminders.is_management_message(
                conn, user_key, message.text, current
            )
        )
        if management:
            policies = [
                (user_key, 20, 1),
                (user_key, 100, 1_440),
                ("global:tft-management", 120, 1),
                ("global:tft-management", 2_000, 1_440),
            ]
            event_type = "management"
        else:
            policies = [
                (user_key, settings.telegram_user_limit_per_minute, 1),
                (user_key, settings.telegram_user_limit_per_day, 1_440),
                ("global:tft-guide", settings.telegram_global_limit_per_minute, 1),
                ("global:tft-guide", settings.telegram_global_limit_per_day, 1_440),
            ]
            event_type = "guide"
        allowed = telegram_bot_store.consume_limits(
            conn,
            policies,
            event_type,
        )
    finally:
        conn.close()
    if not allowed:
        _discard(settings, payload.update_id)
        return {"ok": True}

    try:
        reminder_command = first_word in {
            "/remind", "/reminders", "/cancel", "/delete_me"
        }
        if settings.telegram_reminders_enabled:
            answer = await run_in_threadpool(
                _reminder_answer,
                settings,
                user_key,
                message.chat.id,
                message.text,
                datetime.now(timezone.utc),
            )
        elif reminder_command:
            answer = "Telegram reminders are not enabled yet. You can still use /slots for a current observed lookup."
        else:
            answer = None
        if answer is None:
            answer = await run_in_threadpool(
                tft_guide.handle_message,
                message.text,
                tft_guide.load_catalog(),
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        json.JSONDecodeError,
    ):
        _finish(settings, payload.update_id, "dead", "catalog_invalid")
        log_event(
            logger,
            "telegram_guide_delivery",
            command_class=command_class,
            state="dead",
            error_code="catalog_invalid",
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return {"ok": True}
    try:
        message_id = await run_in_threadpool(
            telegram.send_message,
            settings.telegram_guide_bot_token,
            message.chat.id,
            answer,
        )
    except telegram.TelegramDeliveryError as exc:
        terminal = "unknown" if exc.state in {"unknown", "retry"} else "dead"
        _finish(settings, payload.update_id, terminal, exc.code)
        log_event(
            logger,
            "telegram_guide_delivery",
            command_class=command_class,
            state=terminal,
            error_code=exc.code,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return {"ok": True}
    _finish(settings, payload.update_id, "done", "sent", message_id)
    log_event(
        logger,
        "telegram_guide_delivery",
        command_class=command_class,
        state="done",
        error_code="sent",
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    return {"ok": True}


@router.post("/api/internal/telegram/reminders/dispatch")
async def dispatch_telegram_reminders(
    request: Request,
    dispatch_token: str | None = Header(
        default=None, alias="X-Telegram-Reminder-Dispatch-Token"
    ),
    settings: Settings = Depends(get_settings),
) -> dict[str, int | bool | str]:
    if not settings.telegram_reminders_enabled:
        raise HTTPException(
            status_code=503, detail="Telegram reminders are not enabled."
        )
    if not dispatch_token or not hmac.compare_digest(
        dispatch_token, settings.telegram_reminder_dispatch_token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = ReminderDispatch.model_validate(await request.json())
        expected = datetime.fromisoformat(
            payload.expected_generated_at.replace("Z", "+00:00")
        )
        if expected.tzinfo is None:
            raise ValueError
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid dispatch request.")

    started = time.monotonic()
    run_id = secrets.token_hex(8)
    try:
        snapshot = await run_in_threadpool(tft_slot_source.load_snapshot)
    except tft_slot_source.SlotSourceUnavailable:
        log_event(
            logger,
            "telegram_reminder_run",
            run_id=run_id,
            state="dead",
            error_code="slot_source_unavailable",
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
        raise HTTPException(
            status_code=503, detail=f"Slot source unavailable. Run {run_id}."
        )
    if snapshot.get("generated_at") != payload.expected_generated_at:
        try:
            snapshot = await run_in_threadpool(
                lambda: tft_slot_source.load_snapshot(force_refresh=True)
            )
        except tft_slot_source.SlotSourceUnavailable:
            log_event(
                logger,
                "telegram_reminder_run",
                run_id=run_id,
                state="dead",
                error_code="slot_source_refresh_failed",
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
            raise HTTPException(
                status_code=503, detail=f"Slot source unavailable. Run {run_id}."
            )
    if snapshot.get("generated_at") != payload.expected_generated_at:
        log_event(
            logger,
            "telegram_reminder_run",
            run_id=run_id,
            state="dead",
            error_code="snapshot_generation_mismatch",
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
        raise HTTPException(
            status_code=409, detail=f"Snapshot generation mismatch. Run {run_id}."
        )

    try:
        conn = db.connect(settings.db_path)
        try:
            claim_result = telegram_reminders.claim_notifications(
                conn, snapshot, datetime.now(timezone.utc)
            )
        finally:
            conn.close()
    except Exception:
        log_event(
            logger,
            "telegram_reminder_run",
            run_id=run_id,
            state="dead",
            error_code="store_unavailable",
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
        raise HTTPException(
            status_code=503, detail=f"Reminder store unavailable. Run {run_id}."
        )
    sent = unknown = dead = skipped = receipt_conflicts = 0
    store_failed = False
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
                run_id=run_id,
                state="dead",
                error_code="store_unavailable",
                duration_ms=round((time.monotonic() - delivery_started) * 1000),
            )
            break
        if not should_send:
            skipped += 1
            continue
        try:
            message_id = await run_in_threadpool(
                telegram.send_message,
                settings.telegram_guide_bot_token,
                notification.chat_id,
                notification.text,
            )
            state, code = "done", "sent"
            sent += 1
        except telegram.TelegramDeliveryError as exc:
            state = "unknown" if exc.state in {"unknown", "retry"} else "dead"
            code = exc.code
            message_id = None
            if state == "unknown":
                unknown += 1
            else:
                dead += 1
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
                run_id=run_id,
                state="unknown",
                error_code="receipt_conflict",
                duration_ms=round((time.monotonic() - delivery_started) * 1000),
            )
            continue
        log_event(
            logger,
            "telegram_reminder_delivery",
            run_id=run_id,
            state=state,
            error_code=code,
            duration_ms=round((time.monotonic() - delivery_started) * 1000),
        )
    failed = store_failed or receipt_conflicts > 0
    log_event(
        logger,
        "telegram_reminder_run",
        run_id=run_id,
        state="dead" if failed else "done",
        error_code=(
            "store_unavailable"
            if store_failed
            else "receipt_conflict"
            if receipt_conflicts
            else "completed"
        ),
        active_scanned_count=claim_result.active_scanned_count,
        matched_count=claim_result.matched_count,
        no_match_count=claim_result.no_match_count,
        stale_venue_count=claim_result.stale_venue_count,
        expired_count=claim_result.expired_count,
        reconciled_claimed_count=claim_result.reconciled_claimed_count,
        reconciled_unknown_count=claim_result.reconciled_unknown_count,
        batch_limited=claim_result.batch_limited,
        claimed_count=len(claim_result.notifications),
        sent_count=sent,
        unknown_count=unknown,
        dead_count=dead,
        skipped_count=skipped,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    if failed:
        raise HTTPException(
            status_code=503 if store_failed else 500,
            detail=f"Reminder dispatch incomplete. Run {run_id}.",
        )
    return {
        "ok": True,
        "run_id": run_id,
        "claimed": len(claim_result.notifications),
        "sent": sent,
        "unknown": unknown,
        "dead": dead,
        "skipped": skipped,
        "more": claim_result.more_matches,
    }
