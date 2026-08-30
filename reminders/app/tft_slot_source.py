"""Hardened fixed-source loader for the compact public TFT slot projection."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, time as clock_time
from typing import Any, Callable


SOURCE_URL = "https://amex-explorer.kooexperience.com/data/table-for-two-slots.json"
PROJECT = "AMEXPlatSG"
MAX_RESPONSE_BYTES = 1_000_000
MAX_VENUES = 50
MAX_MEALS_PER_VENUE = 4
MAX_SLOTS = 20_000
POSITIVE_CACHE_SECONDS = 60
NEGATIVE_CACHE_SECONDS = 15


class SlotSourceUnavailable(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect()).open
_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at = 0.0
_negative_until = 0.0


def clear_cache() -> None:
    global _cached, _cached_at, _negative_until
    with _lock:
        _cached = None
        _cached_at = 0.0
        _negative_until = 0.0


def _aware_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def validate_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("slot snapshot schema is invalid")
    if payload.get("source_project") != PROJECT:
        raise ValueError("slot snapshot project is invalid")
    _aware_timestamp(payload.get("generated_at"))
    venues = payload.get("venues")
    if not isinstance(venues, list) or len(venues) > MAX_VENUES:
        raise ValueError("slot snapshot venue count is invalid")
    total_slots = 0
    seen_ids = set()
    for venue in venues:
        if not isinstance(venue, dict):
            raise ValueError("slot snapshot venue is invalid")
        venue_id = venue.get("id")
        if (
            not isinstance(venue_id, str)
            or re.fullmatch(r"[a-z0-9-]{1,80}", venue_id) is None
            or venue_id in seen_ids
        ):
            raise ValueError("slot snapshot venue id is invalid")
        seen_ids.add(venue_id)
        status = venue.get("status")
        if status not in {"live_available", "live_no_seats", "unknown"}:
            raise ValueError("slot snapshot venue status is invalid")
        if status in {"live_available", "live_no_seats"} and venue.get("project") != PROJECT:
            raise ValueError("live slot venue project is invalid")
        checked_at = venue.get("checked_at")
        if checked_at is not None:
            _aware_timestamp(checked_at)
        meals = venue.get("meals")
        if not isinstance(meals, list) or len(meals) > MAX_MEALS_PER_VENUE:
            raise ValueError("slot snapshot meal count is invalid")
        for meal in meals:
            if not isinstance(meal, dict) or meal.get("meal") not in {"Lunch", "Dinner"}:
                raise ValueError("slot snapshot meal is invalid")
            if meal.get("status") not in {"available", "no_seats", "unknown"}:
                raise ValueError("slot snapshot meal status is invalid")
            slots = meal.get("slots")
            if not isinstance(slots, list):
                raise ValueError("slot snapshot slots are invalid")
            total_slots += len(slots)
            if total_slots > MAX_SLOTS:
                raise ValueError("slot snapshot slot count is invalid")
            for slot in slots:
                if not isinstance(slot, dict):
                    raise ValueError("slot snapshot slot is invalid")
                slot_date = str(slot.get("date") or "")
                slot_time = str(slot.get("time") or "")
                if (
                    re.fullmatch(r"\d{4}-\d{2}-\d{2}", slot_date) is None
                    or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", slot_time)
                    is None
                ):
                    raise ValueError("slot snapshot date or time is invalid")
                date.fromisoformat(slot_date)
                clock_time.fromisoformat(slot_time)
                seats = slot.get("max_seats")
                if isinstance(seats, bool) or not isinstance(seats, int) or not 0 <= seats <= 10:
                    raise ValueError("slot snapshot seat count is invalid")
    return payload


def _fetch(opener: Callable = _opener) -> dict[str, Any]:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"Accept": "application/json", "User-Agent": "AmexExplorer/1.0"},
    )
    with opener(request, timeout=4) as response:
        if response.getcode() != 200:
            raise SlotSourceUnavailable("slot source returned a non-success status")
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0]
        if content_type.casefold() != "application/json":
            raise SlotSourceUnavailable("slot source did not return JSON")
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
            raise SlotSourceUnavailable("slot source exceeded the size limit")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SlotSourceUnavailable("slot source exceeded the size limit")
    return validate_snapshot(json.loads(body))


def load_snapshot(
    opener: Callable = _opener,
    monotonic: Callable[[], float] = time.monotonic,
    force_refresh: bool = False,
) -> dict[str, Any]:
    global _cached, _cached_at, _negative_until
    current = monotonic()
    with _lock:
        if (
            not force_refresh
            and _cached is not None
            and current - _cached_at < POSITIVE_CACHE_SECONDS
        ):
            return _cached
        if not force_refresh and current < _negative_until:
            if _cached is not None and not force_refresh:
                return _cached
            raise SlotSourceUnavailable("slot source is in negative cache")
        try:
            payload = _fetch(opener)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            json.JSONDecodeError,
            SlotSourceUnavailable,
        ) as exc:
            _negative_until = current + NEGATIVE_CACHE_SECONDS
            if _cached is not None:
                return _cached
            raise SlotSourceUnavailable("slot source could not be loaded") from exc
        _cached = payload
        _cached_at = current
        _negative_until = 0.0
        return payload
