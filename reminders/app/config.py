"""Runtime settings for the reminders service, read from environment."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    resend_api_key: str
    resend_from: str
    alert_export_token: str
    allowed_origin: str
    public_base_url: str
    confirm_token_expiry_hours: int
    table_data_url: str
    trusted_proxy_hops: int = 1
    abuse_hash_salt: str = ""
    subscribe_ip_limit: int = 5
    subscribe_email_limit: int = 5
    subscribe_global_limit: int = 200
    owner_alerts_enabled: bool = False
    owner_alert_ingest_token: str = ""
    telegram_bot_token: str = ""
    telegram_owner_chat_id: int = 0
    explorer_base_url: str = "https://amex-explorer.kooexperience.com"
    owner_alert_not_before: datetime | None = None
    telegram_guide_enabled: bool = False
    telegram_guide_bot_token: str = ""
    telegram_guide_webhook_secret: str = ""
    telegram_identity_hash_salt: str = ""
    telegram_user_limit_per_minute: int = 8
    telegram_global_limit_per_minute: int = 120
    telegram_user_limit_per_day: int = 200
    telegram_global_limit_per_day: int = 5_000


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _env_datetime(name: str) -> datetime | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{name} must include a timezone")
    return parsed


def load_settings() -> Settings:
    settings = Settings(
        db_path=Path(os.getenv("DB_PATH", "reminders.db")),
        resend_api_key=os.getenv("RESEND_API_KEY", "").strip(),
        resend_from=os.getenv("RESEND_FROM", "dinnertime@kooexperience.com").strip(),
        alert_export_token=os.getenv("ALERT_EXPORT_TOKEN", "").strip(),
        allowed_origin=os.getenv(
            "ALLOWED_ORIGIN", "https://amex-explorer.kooexperience.com"
        ).strip(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        confirm_token_expiry_hours=int(os.getenv("CONFIRM_TOKEN_EXPIRY_HOURS", "168")),
        table_data_url=os.getenv(
            "TABLE_DATA_URL",
            "https://amex-explorer.kooexperience.com/data/table-for-two.json",
        ).strip(),
        trusted_proxy_hops=int(os.getenv("TRUSTED_PROXY_HOPS", "1")),
        abuse_hash_salt=os.getenv("ABUSE_HASH_SALT", "").strip(),
        subscribe_ip_limit=int(os.getenv("SUBSCRIBE_IP_LIMIT", "5")),
        subscribe_email_limit=int(os.getenv("SUBSCRIBE_EMAIL_LIMIT", "5")),
        subscribe_global_limit=int(os.getenv("SUBSCRIBE_GLOBAL_LIMIT", "200")),
        owner_alerts_enabled=_env_bool("OWNER_ALERTS_ENABLED"),
        owner_alert_ingest_token=os.getenv("OWNER_ALERT_INGEST_TOKEN", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_owner_chat_id=_env_int("TELEGRAM_OWNER_CHAT_ID"),
        explorer_base_url=os.getenv(
            "EXPLORER_BASE_URL", "https://amex-explorer.kooexperience.com"
        ).rstrip("/"),
        owner_alert_not_before=_env_datetime("OWNER_ALERT_NOT_BEFORE"),
        telegram_guide_enabled=_env_bool("TELEGRAM_GUIDE_ENABLED"),
        telegram_guide_bot_token=os.getenv("TELEGRAM_GUIDE_BOT_TOKEN", "").strip(),
        telegram_guide_webhook_secret=os.getenv(
            "TELEGRAM_GUIDE_WEBHOOK_SECRET", ""
        ).strip(),
        telegram_identity_hash_salt=os.getenv(
            "TELEGRAM_IDENTITY_HASH_SALT", ""
        ).strip(),
        telegram_user_limit_per_minute=_env_int(
            "TELEGRAM_USER_LIMIT_PER_MINUTE", 8
        ),
        telegram_global_limit_per_minute=_env_int(
            "TELEGRAM_GLOBAL_LIMIT_PER_MINUTE", 120
        ),
        telegram_user_limit_per_day=_env_int("TELEGRAM_USER_LIMIT_PER_DAY", 200),
        telegram_global_limit_per_day=_env_int(
            "TELEGRAM_GLOBAL_LIMIT_PER_DAY", 5_000
        ),
    )
    if settings.public_base_url.startswith("https://"):
        missing = []
        if not settings.resend_api_key:
            missing.append("RESEND_API_KEY")
        if len(settings.alert_export_token) < 32:
            missing.append("ALERT_EXPORT_TOKEN (at least 32 characters)")
        if len(settings.abuse_hash_salt) < 32:
            missing.append("ABUSE_HASH_SALT (at least 32 characters)")
        if not settings.allowed_origin.startswith("https://"):
            missing.append("ALLOWED_ORIGIN (HTTPS)")
        if missing:
            raise RuntimeError(
                "Production reminder configuration is incomplete: " + ", ".join(missing)
            )
    if not 0 <= settings.trusted_proxy_hops <= 5:
        raise RuntimeError("TRUSTED_PROXY_HOPS must be between 0 and 5")
    if min(
        settings.subscribe_ip_limit,
        settings.subscribe_email_limit,
        settings.subscribe_global_limit,
    ) < 1:
        raise RuntimeError("Subscribe rate limits must be positive")
    if settings.owner_alerts_enabled:
        missing = []
        if (
            re.fullmatch(r"[A-Za-z0-9_-]{43,}", settings.owner_alert_ingest_token)
            is None
            or settings.owner_alert_ingest_token.startswith(
                ("YOUR_", "REPLACE_", "CHANGE_ME")
            )
        ):
            missing.append("OWNER_ALERT_INGEST_TOKEN (43+ random URL-safe characters)")
        token_parts = settings.telegram_bot_token.split(":", 1)
        if (
            len(token_parts) != 2
            or not token_parts[0].isdigit()
            or len(token_parts[1]) < 20
        ):
            missing.append("TELEGRAM_BOT_TOKEN")
        if not str(settings.telegram_owner_chat_id).startswith("-100"):
            missing.append("TELEGRAM_OWNER_CHAT_ID (private channel ID)")
        if not settings.explorer_base_url.startswith("https://"):
            missing.append("EXPLORER_BASE_URL (HTTPS)")
        if settings.owner_alert_not_before is None:
            missing.append("OWNER_ALERT_NOT_BEFORE (timezone-aware ISO-8601)")
        if missing:
            raise RuntimeError(
                "Owner alert configuration is incomplete: " + ", ".join(missing)
            )
    if settings.telegram_guide_enabled:
        missing = []
        guide_token = settings.telegram_guide_bot_token.split(":", 1)
        if (
            len(guide_token) != 2
            or not guide_token[0].isdigit()
            or len(guide_token[1]) < 20
            or settings.telegram_guide_bot_token == settings.telegram_bot_token
        ):
            missing.append("TELEGRAM_GUIDE_BOT_TOKEN (separate public bot)")
        for name, value in (
            ("TELEGRAM_GUIDE_WEBHOOK_SECRET", settings.telegram_guide_webhook_secret),
            ("TELEGRAM_IDENTITY_HASH_SALT", settings.telegram_identity_hash_salt),
        ):
            if (
                re.fullmatch(r"[A-Za-z0-9_-]{43,256}", value) is None
                or value.startswith(("YOUR_", "REPLACE_", "CHANGE_ME"))
            ):
                missing.append(f"{name} (43+ random URL-safe characters)")
        if (
            settings.telegram_guide_webhook_secret
            == settings.telegram_identity_hash_salt
        ):
            missing.append("independent Telegram webhook and identity secrets")
        if min(
            settings.telegram_user_limit_per_minute,
            settings.telegram_global_limit_per_minute,
            settings.telegram_user_limit_per_day,
            settings.telegram_global_limit_per_day,
        ) < 1:
            missing.append("positive Telegram guide rate limits")
        if missing:
            raise RuntimeError(
                "Telegram guide configuration is incomplete: " + ", ".join(missing)
            )
    return settings
