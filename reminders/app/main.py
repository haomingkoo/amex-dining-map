"""Table for Two reminders service — FastAPI app entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import load_settings
from app.routes import router
from app.security import RequestBodyLimitMiddleware, SecurityHeadersMiddleware

settings = load_settings()

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

db.init_db(settings.db_path)
app.include_router(router)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}
