"""Table for Two reminders service — FastAPI app entrypoint."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, owner_alert_store, telegram_bot_store
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
app.include_router(router)
app.include_router(owner_alert_router)
app.include_router(telegram_bot_router)


@app.get("/healthz")
def healthz() -> dict[str, bool | str]:
    return {
        "ok": True,
        "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID", "local"),
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA", "local"),
    }
