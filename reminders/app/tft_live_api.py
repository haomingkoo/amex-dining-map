"""Public, bounded interface for the Railway TFT live-slot snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import tft_guide, tft_patterns
from app.config import Settings, load_settings
from app.tft_live_refresh import load_snapshot


router = APIRouter()
TFT_LIVE_STALE_AFTER_SECONDS = 30 * 60


def get_settings() -> Settings:
    return load_settings()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validated_snapshot(path: Path) -> dict[str, Any] | None:
    """Load a producer-validated snapshot and enforce envelope consistency."""

    snapshot = load_snapshot(path)
    if snapshot is None or _timestamp(snapshot.get("generated_at")) is None:
        return None
    counts = snapshot["counts"]
    eligible = counts["eligible"]
    succeeded = counts["succeeded"]
    failed = counts["failed"]
    retained = counts["retained"]
    if (
        eligible != len(snapshot["venues"])
        or succeeded + failed != eligible
        or retained > failed
    ):
        return None
    expected_status = "success" if failed == 0 else "partial" if succeeded else "error"
    if snapshot["refresh_status"] != expected_status:
        return None
    return snapshot


def snapshot_health(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    snapshot = validated_snapshot(path)
    if snapshot is None:
        return {
            "status": "unavailable",
            "generated_at": None,
            "age_seconds": None,
            "counts": None,
        }
    generated = _timestamp(snapshot["generated_at"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = max(
        0,
        int((current.astimezone(timezone.utc) - generated).total_seconds()),
    )
    status = (
        "stale"
        if age_seconds > TFT_LIVE_STALE_AFTER_SECONDS
        else snapshot["refresh_status"]
    )
    return {
        "status": status,
        "generated_at": snapshot["generated_at"],
        "age_seconds": age_seconds,
        "counts": snapshot["counts"],
    }


@router.get("/api/tft/slots")
def tft_live_slots(settings: Settings = Depends(get_settings)) -> JSONResponse:
    snapshot = validated_snapshot(settings.tft_live_snapshot_path)
    if snapshot is None:
        return JSONResponse(
            {"detail": "Live slot snapshot unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})


@router.get("/api/tft/patterns")
def tft_patterns_summary(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Per-venue slot timing for the Explorer: durations, returns and the best time to look."""
    live = tft_patterns.live_summary(settings.db_path)
    venues = {}
    for venue in tft_guide.load_catalog().get("venues") or []:
        venue_id = str(venue.get("id"))
        entry = (live.get("venues") or {}).get(venue_id) or {}
        venues[venue_id] = {
            "best_time": tft_patterns.best_time_line(venue, entry),
            "lines": entry.get("lines") or [],
            "new_tables": entry.get("new_tables", 0),
            "returned_tables": entry.get("returned_tables", 0),
            "returns_per_day": entry.get("returns_per_day", 0),
            "return_buckets": entry.get("return_buckets") or {},
            "new_lasted_minutes": entry.get("new_lasted_minutes") or [],
        }
    return JSONResponse(
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "started_at": live.get("started_at"),
            "venues": venues,
        },
    )
