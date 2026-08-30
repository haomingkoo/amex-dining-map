"""Table for Two reminders service — FastAPI app entrypoint."""

from __future__ import annotations

import os
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, owner_alert_store, telegram_bot_store, telegram_reminders, tft_guide
from app.config import load_settings
from app.owner_alert_routes import router as owner_alert_router
from app.observability import configure_logging
from app.telegram_bot_routes import router as telegram_bot_router
from app.routes import router
from app.security import (
    RequestBodyLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

settings = load_settings()
configure_logging()

app = FastAPI(
    title="Table for Two Reminders",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=16_384)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

db.init_db(settings.db_path)
owner_alert_store.init_db(settings.db_path)
telegram_bot_store.init_db(settings.db_path)
telegram_reminder_conn = db.connect(settings.db_path)
try:
    telegram_reminders.init_db(
        telegram_reminder_conn, settings.telegram_identity_hash_salt
    )
finally:
    telegram_reminder_conn.close()
app.include_router(router)
app.include_router(owner_alert_router)
app.include_router(telegram_bot_router)


APP_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def bundle_revision() -> str:
    digest = hashlib.sha256()
    paths = [*sorted(APP_DIR.glob("*.py")), tft_guide.CATALOG_PATH]
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"bundle:{digest.hexdigest()[:12]}"


@lru_cache(maxsize=1)
def catalog_health() -> dict[str, Any]:
    try:
        raw = tft_guide.CATALOG_PATH.read_bytes()
        catalog = tft_guide.load_catalog()
        return {
            "catalog_ok": True,
            "catalog_sha256": hashlib.sha256(raw).hexdigest(),
            "catalog_schema_version": catalog.get("schema_version"),
            "catalog_roster_checked_at": catalog.get("roster_checked_at"),
            "catalog_menu_checked_at": (catalog.get("menu_source") or {}).get(
                "checked_at"
            ),
            "catalog_release_updated_at": (catalog.get("release_source") or {}).get(
                "updated_at"
            ),
            "catalog_release_project": (catalog.get("release_source") or {}).get(
                "project"
            ),
            "catalog_slot_project": (catalog.get("slot_source") or {}).get(
                "project"
            ),
            "catalog_slot_stale_after_minutes": (
                catalog.get("slot_source") or {}
            ).get("stale_after_minutes"),
        }
    except (OSError, ValueError, TypeError):
        return {"catalog_ok": False}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    response = {
        "ok": True,
        "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID", "local"),
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or bundle_revision(),
    }
    response.update(catalog_health())
    return response
