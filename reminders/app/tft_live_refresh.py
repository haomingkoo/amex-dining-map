"""Bounded, failure-tolerant AMEXPlatSG availability snapshot producer.

The public snapshot deliberately contains only the fields needed by the TFT
consumer.  Raw upstream responses and exception messages never cross this
boundary.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


PROJECT = "AMEXPlatSG"
API_BASE = "https://api.diningcity.asia/public"
DEFAULT_CATALOG_PATH = Path(__file__).with_name("tft_guide_catalog.json")
MAX_VENUES = 50
MAX_WORKERS = 6
MAX_DATES_PER_VENUE = 62
MAX_SLOTS_PER_MEAL = 512
MAX_SNAPSHOT_BYTES = 2_000_000
MAX_UPSTREAM_BYTES = 5_000_000
REQUEST_TIMEOUT_SECONDS = 12
REQUEST_RETRIES = 2
ERROR_CODES = frozenset(
    {
        "timeout",
        "rate_limited",
        "http_client",
        "http_server",
        "network",
        "invalid_response",
        "membership_error",
        "not_in_project",
        "internal_error",
    }
)
_ID_RE = re.compile(r"[a-z0-9-]{1,80}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")

Fetcher = Callable[[str, dict[str, object] | None, bool], object]
Clock = Callable[[], datetime]
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(clock: Clock) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _default_fetch(path: str, params: dict[str, object] | None, versioned: bool) -> object:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{API_BASE}{path}{query}",
        headers={
            "User-Agent": "Mozilla/5.0 amex-dining-map Railway TFT refresh",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "api-key": "cgecegcegcc",
            "lang": "en",
            **({"accept-version": "application/json; version=2"} if versioned else {}),
        },
    )
    retryable = {429, 500, 502, 503, 504}
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                content_type = response.headers.get_content_type()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    raise ValueError("upstream response is not JSON")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("upstream content length is invalid") from exc
                    if declared_length < 0 or declared_length > MAX_UPSTREAM_BYTES:
                        raise ValueError("upstream response is too large")
                body = response.read(MAX_UPSTREAM_BYTES + 1)
                if len(body) > MAX_UPSTREAM_BYTES:
                    raise ValueError("upstream response is too large")
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable or attempt == REQUEST_RETRIES:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == REQUEST_RETRIES:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("unreachable request retry state")


def _error_code(exc: BaseException, *, membership: bool = False) -> str:
    if membership:
        return "membership_error"
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return "rate_limited"
        return "http_server" if exc.code >= 500 else "http_client"
    if isinstance(exc, (TimeoutError, urllib.error.URLError)):
        return "timeout" if isinstance(exc, TimeoutError) else "network"
    if isinstance(exc, (TypeError, ValueError, KeyError, json.JSONDecodeError)):
        return "invalid_response"
    return "internal_error"


def _active_catalog_venues(catalog: object) -> list[dict[str, str]]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("venues"), list):
        raise ValueError("catalog venues are invalid")
    venues: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in catalog["venues"]:
        if not isinstance(raw, dict):
            continue
        if (
            raw.get("approved") is False
            or raw.get("active") is False
            or raw.get("review_required") is True
            or str(raw.get("operational_status") or raw.get("status") or "").lower()
            in {"closed", "inactive", "removed"}
        ):
            continue
        venue_id = str(raw.get("id") or "")
        dining_city_id = str(raw.get("dining_city_id") or "")
        if not _ID_RE.fullmatch(venue_id) or not dining_city_id.isdigit():
            continue
        if venue_id in seen:
            raise ValueError("catalog contains duplicate venue ids")
        seen.add(venue_id)
        venues.append({"id": venue_id, "dining_city_id": dining_city_id})
    if not venues or len(venues) > MAX_VENUES:
        raise ValueError("active catalog venue count is invalid")
    return sorted(venues, key=lambda item: item["id"])


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[dict[str, str]]:
    return _active_catalog_venues(json.loads(path.read_text(encoding="utf-8")))


def _membership_ids(payload: object) -> set[str]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("membership response is invalid")
    ids: list[str] = []
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("restaurant"), dict):
            continue
        restaurant_id = row["restaurant"].get("id") or row.get("restaurant_id")
        if restaurant_id is not None:
            ids.append(str(restaurant_id))
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("membership response is empty or duplicated")
    return set(ids)


def _max_seats(slot: dict) -> int:
    seats = slot.get("seats")
    if not isinstance(seats, dict):
        return 0
    values = seats.get("available")
    parsed: list[int] = []
    if isinstance(values, list):
        for value in values:
            try:
                parsed.append(int(value))
            except (TypeError, ValueError):
                pass
    try:
        fallback = int(seats.get("total_available_seats") or 0)
    except (TypeError, ValueError):
        fallback = 0
    return max([fallback, *parsed], default=0)


def _rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("availability response is invalid")
    return [row for row in payload["data"] if isinstance(row, dict)]


def _meals(rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict[tuple[str, str], int]] = {"Lunch": {}, "Dinner": {}}
    for row in rows:
        date = str(row.get("date") or "")
        if not _DATE_RE.fullmatch(date):
            continue
        times = row.get("times")
        if not isinstance(times, list):
            continue
        for slot in times:
            if not isinstance(slot, dict):
                continue
            raw_meal = str(slot.get("meal_type_text") or slot.get("meal_type") or "")
            meal = raw_meal.strip().title()
            slot_time = str(slot.get("time") or "")[:5]
            seats = min(max(_max_seats(slot), 0), 10)
            if meal not in buckets or not _TIME_RE.fullmatch(slot_time) or seats < 2:
                continue
            key = (date, slot_time)
            buckets[meal][key] = max(buckets[meal].get(key, 0), seats)
    result = []
    for meal in ("Lunch", "Dinner"):
        slots = [
            {"date": date, "time": slot_time, "max_seats": seats}
            for (date, slot_time), seats in sorted(buckets[meal].items())[
                :MAX_SLOTS_PER_MEAL
            ]
        ]
        if slots:
            result.append({"meal": meal, "status": "available", "slots": slots})
    return result


def _fetch_venue(
    venue: dict[str, str], fetcher: Fetcher, attempted_at: str
) -> dict:
    restaurant_id = venue["dining_city_id"]
    path = f"/restaurants/{restaurant_id}/available_2018"
    rows = _rows(fetcher(path, {"project": PROJECT}, True))
    if not rows:
        dates_payload = fetcher(
            f"/restaurants/{restaurant_id}/dining_dates", {"project": PROJECT}, False
        )
        if not isinstance(dates_payload, list):
            raise ValueError("dining dates response is invalid")
        dates = sorted(
            {
                str(row.get("date"))
                for row in dates_payload
                if isinstance(row, dict)
                and row.get("available") is True
                and _DATE_RE.fullmatch(str(row.get("date") or ""))
            }
        )[:MAX_DATES_PER_VENUE]
        for date in dates:
            rows.extend(
                _rows(
                    fetcher(
                        path,
                        {"project": PROJECT, "selected_date": date},
                        False,
                    )
                )
            )
    meals = _meals(rows)
    return {
        "id": venue["id"],
        "project": PROJECT,
        "status": "live_available" if meals else "live_no_seats",
        "checked_at": attempted_at,
        "attempted_at": attempted_at,
        "result": "fresh",
        "error_code": None,
        "meals": meals,
    }


def _bounded_prior_venue(raw: object) -> dict | None:
    if not isinstance(raw, dict) or raw.get("project") != PROJECT:
        return None
    venue_id = str(raw.get("id") or "")
    status = raw.get("status")
    checked_at = raw.get("checked_at")
    if (
        not _ID_RE.fullmatch(venue_id)
        or status not in {"live_available", "live_no_seats"}
        or not isinstance(checked_at, str)
        or not checked_at
    ):
        return None
    meals = raw.get("meals")
    if not isinstance(meals, list) or len(meals) > 2:
        return None
    bounded_meals = []
    for meal in meals:
        if (
            not isinstance(meal, dict)
            or meal.get("meal") not in {"Lunch", "Dinner"}
            or meal.get("status") != "available"
        ):
            return None
        slots = meal.get("slots")
        if not isinstance(slots, list) or len(slots) > MAX_SLOTS_PER_MEAL:
            return None
        bounded_slots = []
        for slot in slots:
            if not isinstance(slot, dict):
                return None
            date, slot_time = str(slot.get("date") or ""), str(slot.get("time") or "")
            try:
                seats = int(slot.get("max_seats") or 0)
            except (TypeError, ValueError):
                return None
            if not _DATE_RE.fullmatch(date) or not _TIME_RE.fullmatch(slot_time) or not 0 <= seats <= 10:
                return None
            bounded_slots.append({"date": date, "time": slot_time, "max_seats": seats})
        bounded_meals.append(
            {"meal": meal["meal"], "status": "available", "slots": bounded_slots}
        )
    return {
        "id": venue_id,
        "project": PROJECT,
        "status": status,
        "checked_at": checked_at,
        "meals": bounded_meals,
    }


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_snapshot(payload: object) -> dict:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("source_project") != PROJECT
        or payload.get("refresh_status") not in {"success", "partial", "error"}
        or not _valid_timestamp(payload.get("generated_at"))
        or not isinstance(payload.get("venues"), list)
        or len(payload["venues"]) > MAX_VENUES
    ):
        raise ValueError("snapshot envelope is invalid")
    counts = payload.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(key), int) or counts[key] < 0
        for key in ("eligible", "succeeded", "failed", "retained")
    ):
        raise ValueError("snapshot counts are invalid")
    seen: set[str] = set()
    for raw in payload["venues"]:
        venue = _bounded_prior_venue(raw)
        observation_is_valid = venue is not None and (
            _valid_timestamp(raw.get("checked_at"))
            and _valid_timestamp(raw.get("attempted_at"))
            and (
                (raw.get("result") == "fresh" and raw.get("error_code") is None)
                or (
                    raw.get("result") == "retained"
                    and raw.get("error_code") in ERROR_CODES
                )
            )
        )
        error_is_valid = (
            isinstance(raw, dict)
            and _ID_RE.fullmatch(str(raw.get("id") or ""))
            and raw.get("project") == PROJECT
            and raw.get("status") == "unknown"
            and raw.get("result") == "error"
            and raw.get("error_code") in ERROR_CODES
            and raw.get("checked_at") is None
            and _valid_timestamp(raw.get("attempted_at"))
            and raw.get("meals") == []
        )
        if not observation_is_valid and not error_is_valid:
            raise ValueError("snapshot venue is invalid")
        venue_id = str(raw["id"])
        if venue_id in seen:
            raise ValueError("snapshot venue ids are duplicated")
        seen.add(venue_id)
    if (
        counts["eligible"] != len(payload["venues"])
        or counts["succeeded"] + counts["failed"] != counts["eligible"]
        or counts["retained"]
        != sum(row.get("result") == "retained" for row in payload["venues"])
        or counts["succeeded"]
        != sum(row.get("result") == "fresh" for row in payload["venues"])
    ):
        raise ValueError("snapshot counts do not match venues")
    expected_status = (
        "success"
        if counts["failed"] == 0
        else "partial"
        if counts["succeeded"]
        else "error"
    )
    if payload["refresh_status"] != expected_status:
        raise ValueError("snapshot refresh status does not match counts")
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(rendered) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds size bound")
    return payload


def load_snapshot(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        with path.open("rb") as handle:
            body = handle.read(MAX_SNAPSHOT_BYTES + 1)
        if len(body) > MAX_SNAPSHOT_BYTES:
            return None
        return validate_snapshot(json.loads(body.decode("utf-8")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _atomic_write(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds size bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


class TFTLiveRefresher:
    """Produce one atomic snapshot at a time; concurrent triggers are skipped."""

    def __init__(
        self,
        catalog_path: Path,
        snapshot_path: Path,
        *,
        fetcher: Fetcher = _default_fetch,
        clock: Clock = _now,
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.snapshot_path = Path(snapshot_path)
        self.fetcher = fetcher
        self.clock = clock
        self.max_workers = min(max(1, int(max_workers)), MAX_WORKERS)
        self._lock = threading.Lock()

    def refresh(self) -> dict | None:
        if not self._lock.acquire(blocking=False):
            logger.info("tft_live_refresh skipped reason=already_running")
            return None
        try:
            try:
                return self._refresh_locked()
            except Exception as exc:
                logger.error("tft_live_refresh failed error_code=%s", _error_code(exc))
                raise
        finally:
            self._lock.release()

    def _refresh_locked(self) -> dict:
        attempted_at = _timestamp(self.clock)
        catalog = load_catalog(self.catalog_path)
        prior = load_snapshot(self.snapshot_path) or {}
        prior_by_id = {
            str(row.get("id")): row
            for row in prior.get("venues", [])
            if _bounded_prior_venue(row) is not None
        }
        try:
            membership = self.fetcher(
                f"/projects/{PROJECT}/restaurants", {"per_page": 100}, True
            )
            member_ids = _membership_ids(membership)
            listed = [row for row in catalog if row["dining_city_id"] in member_ids]
            not_listed = {
                row["id"] for row in catalog if row["dining_city_id"] not in member_ids
            }
            membership_error = None
        except Exception as exc:  # retain prior observations on total membership failure
            listed = []
            not_listed = set()
            membership_error = _error_code(exc, membership=True)

        fresh: dict[str, dict] = {}
        failures: dict[str, str] = {}
        if membership_error is None:
            failures.update({venue_id: "not_in_project" for venue_id in not_listed})
            workers = min(self.max_workers, len(listed)) or 1
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_fetch_venue, venue, self.fetcher, attempted_at): venue
                    for venue in listed
                }
                for future in as_completed(futures):
                    venue = futures[future]
                    try:
                        fresh[venue["id"]] = future.result()
                    except Exception as exc:
                        failures[venue["id"]] = _error_code(exc)
        else:
            failures = {venue["id"]: membership_error for venue in catalog}

        rows = []
        retained = 0
        for venue in catalog:
            venue_id = venue["id"]
            if venue_id in fresh:
                rows.append(fresh[venue_id])
                continue
            prior_venue = (
                None
                if venue_id in not_listed
                else _bounded_prior_venue(prior_by_id.get(venue_id))
            )
            if prior_venue is not None:
                rows.append(
                    {
                        **prior_venue,
                        "attempted_at": attempted_at,
                        "result": "retained",
                        "error_code": failures.get(venue_id, "internal_error"),
                    }
                )
                retained += 1
            else:
                rows.append(
                    {
                        "id": venue_id,
                        "project": PROJECT,
                        "status": "unknown",
                        "checked_at": None,
                        "attempted_at": attempted_at,
                        "result": "error",
                        "error_code": failures.get(venue_id, "internal_error"),
                        "meals": [],
                    }
                )

        succeeded = len(fresh)
        failed = len(catalog) - succeeded
        refresh_status = "success" if failed == 0 else "partial" if succeeded else "error"
        snapshot = {
            "schema_version": 1,
            "source_project": PROJECT,
            "generated_at": attempted_at,
            "refresh_status": refresh_status,
            "counts": {
                "eligible": len(catalog),
                "succeeded": succeeded,
                "failed": failed,
                "retained": retained,
            },
            "venues": sorted(rows, key=lambda row: row["id"]),
        }
        validate_snapshot(snapshot)
        _atomic_write(self.snapshot_path, snapshot)
        logger.info(
            "tft_live_refresh completed status=%s eligible=%d succeeded=%d failed=%d retained=%d",
            refresh_status,
            len(catalog),
            succeeded,
            failed,
            retained,
        )
        return snapshot
