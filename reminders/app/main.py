"""Table for Two reminders service — FastAPI app entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings

settings = load_settings()

app = FastAPI(title="Table for Two Reminders", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}
