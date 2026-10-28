"""Table for Two reminders service — FastAPI app entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
import os
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app import (
    db,
    owner_alert_store,
    telegram_bot_store,
    telegram_digest,
    telegram_reminder_dispatch,
    telegram_reminders,
    tft_agent,
    tft_guide,
    tft_live_api,
    tft_patterns,
)
from app import alert_dispatch
from app.config import load_settings
from app.owner_alert_routes import router as owner_alert_router
from app.owner_alerts import OWNER_ALERT_BATCH_MAX_BYTES
from app.observability import configure_logging
from app.telegram_bot_routes import router as telegram_bot_router
from app.tft_live_refresh import TFTLiveRefresher
from app.routes import router
from app.security import (
    RequestBodyLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

settings = load_settings()
configure_logging()


# Same adopted catalogue as the guide, so a venue added after a deploy is refreshed.
live_refresher = TFTLiveRefresher(
    tft_guide.load_catalog,
    settings.tft_live_snapshot_path,
)

class RecordingRefresher:
    """Refresh, then record how long each slot stayed open."""

    def __init__(self, refresher: TFTLiveRefresher, db_path: Path) -> None:
        self.refresher = refresher
        self.db_path = db_path

    def refresh(self) -> dict | None:
        snapshot = self.refresher.refresh()
        if snapshot is not None:
            tft_patterns.record_snapshot(self.db_path, snapshot)
        return snapshot


# The site publishes the same catalogue the image bakes in; following it stops the
# deployed copy drifting between redeploys. Half the 30-minute Monitor Source Health
# cadence, so a published change is adopted before the next check reads /healthz.
PUBLISHED_CATALOG_URL = f"{settings.explorer_base_url}/data/tft_guide_catalog.json"
CATALOG_REFRESH_INTERVAL_SECONDS = 900
# Retention limits in db.purge_expired_records apply daily, not only on restart.
PURGE_INTERVAL_SECONDS = 86_400


async def run_live_refresh_loop(
    refresher: TFTLiveRefresher,
    interval_seconds: int,
    *,
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Refresh immediately, then wait one fixed delay after each completion."""

    while True:
        try:
            await to_thread(refresher.refresh)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Upstream details stay inside the bounded producer snapshot/log boundary.
            pass
        await sleep(interval_seconds)


async def run_periodically(
    interval_seconds: int,
    call: Callable[..., Any],
    *args: Any,
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run a blocking call on a fixed cadence, off the event loop."""

    while True:
        await to_thread(call, *args)
        await sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks: list[asyncio.Task[None]] = []
    if settings.tft_live_refresh_enabled:
        tasks.append(
            asyncio.create_task(
                run_live_refresh_loop(
                    RecordingRefresher(live_refresher, settings.db_path),
                    settings.tft_live_refresh_interval_seconds,
                )
            )
        )
        # Start the immediate refresh before application startup completes.
        await asyncio.sleep(0)
    # An HTTPS public base URL is what config.py already treats as "deployed"; local
    # runs and the test suite keep the baked copy and stay off the network.
    if settings.public_base_url.startswith("https://"):
        tasks.append(
            asyncio.create_task(
                run_periodically(
                    CATALOG_REFRESH_INTERVAL_SECONDS,
                    tft_guide.adopt_published_catalog,
                    PUBLISHED_CATALOG_URL,
                )
            )
        )
    if settings.github_dispatch_token:
        tasks.append(
            asyncio.create_task(
                run_periodically(
                    alert_dispatch.DISPATCH_INTERVAL_SECONDS,
                    alert_dispatch.dispatch_and_record,
                    settings.github_dispatch_token,
                    alert_dispatch.GITHUB_REPO,
                )
            )
        )
    tasks.append(
        asyncio.create_task(
            run_periodically(PURGE_INTERVAL_SECONDS, db.purge, settings.db_path)
        )
    )
    if settings.telegram_reminders_enabled:
        tasks.append(
            asyncio.create_task(
                run_periodically(
                    telegram_reminder_dispatch.DISPATCH_INTERVAL_SECONDS,
                    telegram_reminder_dispatch.dispatch_and_record,
                    settings,
                )
            )
        )
    if settings.telegram_reminders_enabled:
        tasks.append(
            asyncio.create_task(
                run_periodically(
                    telegram_digest.DISPATCH_INTERVAL_SECONDS,
                    telegram_digest.dispatch_and_record,
                    settings,
                )
            )
        )
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Table for Two Reminders",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(GZipMiddleware, minimum_size=100)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=16_384,
    bearer_limits={"/api/owner-alerts/batch": OWNER_ALERT_BATCH_MAX_BYTES},
)
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
app.include_router(tft_live_api.router)
app.mount("/fonts", StaticFiles(directory=Path(__file__).parent / "fonts"), name="fonts")


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


def catalog_health() -> dict[str, Any]:
    try:
        in_use = tft_guide.catalog_in_use()
        catalog = in_use.payload
        return {
            "catalog_ok": True,
            "catalog_source": in_use.source,
            "catalog_sha256": hashlib.sha256(in_use.raw).hexdigest(),
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
            "catalog_terms_current": (catalog.get("eligibility_source") or {}).get(
                "terms_current"
            ),
            "catalog_menu_prices_need_review": (catalog.get("verdict_source") or {}).get(
                "needs_review"
            ),
        }
    except (OSError, ValueError, TypeError):
        return {"catalog_ok": False}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    response = {
        "ok": True,
        "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID", "local"),
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or bundle_revision(),
        "feature_state": {
            "email_delivery_configured": bool(
                settings.resend_api_key and settings.resend_from
            ),
            "owner_alerts_enabled": settings.owner_alerts_enabled,
            "telegram_guide_enabled": settings.telegram_guide_enabled,
            "telegram_reminders_enabled": settings.telegram_reminders_enabled,
            "telegram_guide_llm_enabled": settings.telegram_guide_llm_enabled,
            "telegram_guide_web_search_enabled": bool(
                settings.telegram_guide_llm_enabled and settings.brave_api_key
            ),
            "tft_live_refresh_enabled": settings.tft_live_refresh_enabled,
            "alert_dispatch_enabled": bool(settings.github_dispatch_token),
        },
        "alert_dispatch": dict(alert_dispatch.last_dispatch),
        "telegram_reminder_dispatch": dict(telegram_reminder_dispatch.last_dispatch),
        "telegram_digest_dispatch": dict(telegram_digest.last_dispatch),
    }
    if settings.telegram_guide_llm_enabled:
        response["telegram_guide_llm"] = tft_agent.stats()
    response.update(catalog_health())
    response["tft_live"] = tft_live_api.snapshot_health(
        settings.tft_live_snapshot_path
    )
    response["tft_slot_history"] = dict(tft_patterns.last_record)
    if settings.tft_live_refresh_enabled:
        response["ok"] = response["tft_live"]["status"] == "success"
    return response
