#!/usr/bin/env python3
"""Secret-safe Telegram provisioning and production-readiness checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime


TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{20,}")
SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43,256}")
USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,28}[Bb][Oo][Tt]")
DEFAULT_API_BASE = "https://amex-reminders-production.up.railway.app"
PUBLIC_CONFIG_URL = "https://amex-explorer.kooexperience.com/data/telegram-guide.json"


class ReadinessError(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ReadinessError(f"missing {name}")
    return value


def _secret(name: str) -> str:
    value = required(name)
    if SECRET_RE.fullmatch(value) is None or value.startswith(("YOUR_", "REPLACE_", "CHANGE_ME")):
        raise ReadinessError(f"invalid {name}")
    return value


def config_values() -> dict[str, object]:
    owner_token = required("TELEGRAM_BOT_TOKEN")
    guide_token = required("TELEGRAM_GUIDE_BOT_TOKEN")
    if TOKEN_RE.fullmatch(owner_token) is None:
        raise ReadinessError("invalid TELEGRAM_BOT_TOKEN")
    if TOKEN_RE.fullmatch(guide_token) is None or guide_token == owner_token:
        raise ReadinessError("invalid or non-distinct TELEGRAM_GUIDE_BOT_TOKEN")
    chat_text = required("TELEGRAM_OWNER_CHAT_ID")
    if re.fullmatch(r"-100\d{6,}", chat_text) is None:
        raise ReadinessError("invalid TELEGRAM_OWNER_CHAT_ID")
    cutoff = required("OWNER_ALERT_NOT_BEFORE")
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError("invalid OWNER_ALERT_NOT_BEFORE") from exc
    if parsed_cutoff.tzinfo is None:
        raise ReadinessError("invalid OWNER_ALERT_NOT_BEFORE")
    secrets = {
        "OWNER_ALERT_INGEST_TOKEN": _secret("OWNER_ALERT_INGEST_TOKEN"),
        "TELEGRAM_GUIDE_WEBHOOK_SECRET": _secret("TELEGRAM_GUIDE_WEBHOOK_SECRET"),
        "TELEGRAM_IDENTITY_HASH_SALT": _secret("TELEGRAM_IDENTITY_HASH_SALT"),
        "TELEGRAM_REMINDER_DISPATCH_TOKEN": _secret("TELEGRAM_REMINDER_DISPATCH_TOKEN"),
    }
    if len(set(secrets.values())) != len(secrets):
        raise ReadinessError("Telegram and owner secrets must be independent")
    return {
        "owner_token": owner_token,
        "guide_token": guide_token,
        "owner_chat_id": int(chat_text),
        **secrets,
    }


def request_json(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(65_537))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ReadinessError("remote readiness probe failed") from exc
    if not isinstance(payload, dict):
        raise ReadinessError("remote readiness probe returned an invalid shape")
    return payload


def telegram_call(token: str, method: str, data: dict | None = None, allow_absent=False):
    url = f"https://api.telegram.org/bot{token}/{method}"
    encoded = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    request = urllib.request.Request(url, data=encoded, method="POST" if encoded is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(65_537))
    except urllib.error.HTTPError as exc:
        if allow_absent and exc.code == 400:
            return None
        raise ReadinessError(f"Telegram {method} probe failed") from None
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"Telegram {method} probe failed") from exc
    if payload.get("ok") is not True:
        raise ReadinessError(f"Telegram {method} probe failed")
    return payload.get("result")


def check_identities(values: dict[str, object]) -> None:
    owner = telegram_call(str(values["owner_token"]), "getMe")
    guide = telegram_call(str(values["guide_token"]), "getMe")
    if owner.get("is_bot") is not True or guide.get("is_bot") is not True or owner.get("id") == guide.get("id"):
        raise ReadinessError("owner and guide identities are not distinct bots")
    chat_id = int(values["owner_chat_id"])
    channel = telegram_call(str(values["owner_token"]), "getChat", {"chat_id": chat_id})
    if int(channel.get("id", 0)) != chat_id or channel.get("type") != "channel":
        raise ReadinessError("owner destination is not the configured private channel")
    membership = telegram_call(
        str(values["owner_token"]),
        "getChatMember",
        {"chat_id": chat_id, "user_id": int(owner["id"])},
    )
    if membership.get("status") != "administrator" or membership.get("can_post_messages") is not True:
        raise ReadinessError("owner bot lacks post-only channel administration")
    for permission in ("can_edit_messages", "can_delete_messages", "can_invite_users", "can_promote_members"):
        if membership.get(permission) is True:
            raise ReadinessError(f"owner bot has unnecessary {permission}")
    guide_membership = telegram_call(
        str(values["owner_token"]),
        "getChatMember",
        {"chat_id": chat_id, "user_id": int(guide["id"])},
        allow_absent=True,
    )
    if guide_membership is not None and guide_membership.get("status") not in {"left", "kicked"}:
        raise ReadinessError("guide bot must not belong to the owner channel")
    for token in (str(values["owner_token"]), str(values["guide_token"])):
        webhook = telegram_call(token, "getWebhookInfo")
        if webhook.get("url"):
            raise ReadinessError("bot webhook must be empty before activation")


def expect_status(url: str, headers: dict, expected: int) -> None:
    request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ReadinessError("production authentication probe failed") from exc
    if status != expected:
        raise ReadinessError(f"production authentication probe returned {status}, expected {expected}")


def health(api_base: str) -> dict:
    payload = request_json(f"{api_base}/healthz")
    if payload.get("ok") is not True or payload.get("catalog_ok") is not True:
        raise ReadinessError("production health or catalogue is not ready")
    return payload


def check_owner(api_base: str) -> None:
    features = health(api_base).get("feature_state") or {}
    if features.get("owner_alerts_enabled") is not True:
        raise ReadinessError("owner alerts are not enabled in deployed health")
    expect_status(f"{api_base}/api/owner-alerts/events", {"Authorization": "Bearer deliberately-wrong"}, 401)


def check_guide(api_base: str, values: dict[str, object]) -> None:
    features = health(api_base).get("feature_state") or {}
    if features.get("telegram_guide_enabled") is not True:
        raise ReadinessError("Telegram guide is not enabled in deployed health")
    guide = telegram_call(str(values["guide_token"]), "getMe")
    username = str(guide.get("username") or "")
    if USERNAME_RE.fullmatch(username) is None:
        raise ReadinessError("guide bot has no valid public username")
    webhook = telegram_call(str(values["guide_token"]), "getWebhookInfo")
    expected_url = f"{api_base}/api/telegram/guide/webhook"
    if webhook.get("url") != expected_url or webhook.get("allowed_updates") != ["message"] or webhook.get("last_error_message"):
        raise ReadinessError("guide webhook does not match the deployed endpoint")
    config = request_json(PUBLIC_CONFIG_URL)
    if config != {"schema_version": 1, "enabled": True, "bot_username": username}:
        raise ReadinessError("public Telegram guide config does not match BotFather")
    expect_status(
        expected_url,
        {"X-Telegram-Bot-Api-Secret-Token": "deliberately-wrong"},
        401,
    )


def check_reminders(api_base: str) -> None:
    features = health(api_base).get("feature_state") or {}
    if features.get("telegram_guide_enabled") is not True or features.get("telegram_reminders_enabled") is not True:
        raise ReadinessError("Telegram reminders are not enabled in deployed health")
    expect_status(
        f"{api_base}/api/internal/telegram/reminders/dispatch",
        {"X-Telegram-Reminder-Dispatch-Token": "deliberately-wrong"},
        401,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("config", "identities", "owner", "guide", "reminders"))
    args = parser.parse_args()
    values = config_values()
    api_base = os.getenv("REMINDERS_API_BASE", DEFAULT_API_BASE).rstrip("/")
    if not api_base.startswith("https://"):
        raise ReadinessError("REMINDERS_API_BASE must use HTTPS")
    if args.phase == "identities":
        check_identities(values)
    elif args.phase == "owner":
        check_owner(api_base)
    elif args.phase == "guide":
        check_guide(api_base, values)
    elif args.phase == "reminders":
        check_reminders(api_base)
    print(f"TELEGRAM READINESS OK phase={args.phase}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReadinessError as exc:
        raise SystemExit(f"TELEGRAM READINESS FAILED: {exc}") from None
