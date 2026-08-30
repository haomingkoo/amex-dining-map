"""Authenticated, private-chat-only Telegram guide webhook."""

from __future__ import annotations

import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app import db, telegram, telegram_bot_store, tft_guide
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
        return {"ok": True}

    started = time.monotonic()
    first_word = message.text.strip().split(maxsplit=1)[0].lower()
    command_class = first_word if first_word in {"/start", "/help", "/venues", "/menu"} else "query"

    user_key = telegram_bot_store.identity_key(
        "user", message.sender.id, settings.telegram_identity_hash_salt
    )
    conn = db.connect(settings.db_path)
    try:
        allowed = telegram_bot_store.consume_limits(
            conn,
            [
                (user_key, settings.telegram_user_limit_per_minute, 1),
                (user_key, settings.telegram_user_limit_per_day, 1_440),
                ("global:tft-guide", settings.telegram_global_limit_per_minute, 1),
                ("global:tft-guide", settings.telegram_global_limit_per_day, 1_440),
            ],
        )
    finally:
        conn.close()
    if not allowed:
        _discard(settings, payload.update_id)
        return {"ok": True}

    try:
        answer = tft_guide.handle_message(message.text, tft_guide.load_catalog())
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
