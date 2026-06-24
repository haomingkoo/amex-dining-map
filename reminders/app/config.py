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


def load_settings() -> Settings:
    return Settings(
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
    )
