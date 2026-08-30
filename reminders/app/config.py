"""Runtime settings for the reminders service, read from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
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
    return settings
