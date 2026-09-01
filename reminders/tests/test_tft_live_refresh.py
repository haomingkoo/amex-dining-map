from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

import pytest

from app import tft_live_refresh


NOW = datetime(2026, 9, 2, 4, 5, 6, tzinfo=timezone.utc)


def catalog(path: Path, *, count: int = 2) -> Path:
    venues = [
        {
            "id": f"venue-{index}",
            "dining_city_id": str(2000 + index),
            "name": f"Venue {index}",
        }
        for index in range(count)
    ]
    # These records must never become producer targets.
    venues.extend(
        [
            {"id": "closed", "dining_city_id": "9991", "operational_status": "closed"},
            {"id": "review", "dining_city_id": "9992", "review_required": True},
            {"id": "unapproved", "dining_city_id": "9993", "approved": False},
        ]
    )
    path.write_text(json.dumps({"venues": venues}), encoding="utf-8")
    return path


def membership(*ids: str) -> list[dict]:
    return [{"restaurant": {"id": value, "name": value}} for value in ids]


def slots(date: str = "2026-09-20", *, extra: int = 0) -> dict:
    times = [
        {
            "meal_type_text": "Lunch",
            "time": f"{12 + (index // 60):02d}:{index % 60:02d}",
            "seats": {"available": [2, 3]},
        }
        for index in range(min(extra, 120))
    ]
    times.extend(
        [
            {
                "meal_type_text": "Lunch",
                "time": "12:00",
                "seats": {"available": [2, 4]},
            },
            {
                "meal_type_text": "Dinner",
                "time": "19:30:00",
                "seats": {"total_available_seats": 2},
            },
            {
                "meal_type_text": "Brunch",
                "time": "10:00",
                "seats": {"available": [2]},
            },
        ]
    )
    return {"data": [{"date": date, "times": times}]}


def prior_snapshot(*venue_ids: str) -> dict:
    rows = [
        {
            "id": venue_id,
            "project": tft_live_refresh.PROJECT,
            "status": "live_available",
            "checked_at": "2026-09-01T00:00:00Z",
            "attempted_at": "2026-09-01T00:00:00Z",
            "result": "fresh",
            "error_code": None,
            "meals": [
                {
                    "meal": "Dinner",
                    "status": "available",
                    "slots": [
                        {"date": "2026-09-10", "time": "19:00", "max_seats": 2}
                    ],
                }
            ],
        }
        for venue_id in venue_ids
    ]
    return {
        "schema_version": 1,
        "source_project": tft_live_refresh.PROJECT,
        "generated_at": "2026-09-01T00:00:00Z",
        "refresh_status": "success",
        "counts": {
            "eligible": len(rows),
            "succeeded": len(rows),
            "failed": 0,
            "retained": 0,
        },
        "venues": rows,
    }


def write_prior(path: Path, *venue_ids: str) -> None:
    path.write_text(json.dumps(prior_snapshot(*venue_ids)), encoding="utf-8")


def test_membership_is_fetched_once_and_filters_to_approved_active_catalog(tmp_path):
    calls = []

    def fetch(path, params, versioned):
        calls.append((path, params, versioned))
        if path.startswith("/projects/"):
            return membership("2000", "9991", "7777")
        return slots()

    output = tmp_path / "snapshot.json"
    write_prior(output, "venue-1")
    result = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json"), output, fetcher=fetch, clock=lambda: NOW
    ).refresh()

    assert result is not None
    assert result["refresh_status"] == "partial"
    assert result["counts"] == {"eligible": 2, "succeeded": 1, "failed": 1, "retained": 0}
    assert [row["id"] for row in result["venues"]] == ["venue-0", "venue-1"]
    missing = result["venues"][1]
    assert (missing["status"], missing["result"], missing["error_code"]) == (
        "unknown", "error", "not_in_project"
    )
    assert missing["checked_at"] is None
    assert sum(path.startswith("/projects/") for path, _, _ in calls) == 1
    assert all("9991" not in path for path, _, _ in calls)


def test_partial_failure_retains_last_good_and_bounds_public_fields(tmp_path):
    output = tmp_path / "snapshot.json"
    write_prior(output, "venue-1")

    def fetch(path, _params, _versioned):
        if path.startswith("/projects/"):
            return membership("2000", "2001")
        if "/2001/" in path:
            raise RuntimeError("SECRET upstream stack and credential")
        return slots()

    result = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json"), output, fetcher=fetch, clock=lambda: NOW
    ).refresh()

    assert result is not None
    assert result["refresh_status"] == "partial"
    assert result["counts"] == {"eligible": 2, "succeeded": 1, "failed": 1, "retained": 1}
    retained = next(row for row in result["venues"] if row["id"] == "venue-1")
    assert retained["checked_at"] == "2026-09-01T00:00:00Z"
    assert retained["attempted_at"] == "2026-09-02T04:05:06Z"
    assert retained["result"] == "retained"
    assert retained["error_code"] == "internal_error"
    assert "SECRET" not in json.dumps(result)
    fresh = next(row for row in result["venues"] if row["id"] == "venue-0")
    assert [meal["meal"] for meal in fresh["meals"]] == ["Lunch", "Dinner"]
    assert set(fresh) == {
        "id", "project", "status", "checked_at", "attempted_at", "result", "error_code", "meals"
    }


def test_total_membership_error_records_attempt_and_preserves_prior_observation(tmp_path):
    output = tmp_path / "snapshot.json"
    write_prior(output, "venue-0")
    calls = []

    def fetch(path, _params, _versioned):
        calls.append(path)
        raise TimeoutError("upstream timeout details")

    result = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json"), output, fetcher=fetch, clock=lambda: NOW
    ).refresh()

    assert result is not None
    assert calls == [f"/projects/{tft_live_refresh.PROJECT}/restaurants"]
    assert result["generated_at"] == "2026-09-02T04:05:06Z"
    assert result["refresh_status"] == "error"
    assert result["counts"] == {"eligible": 2, "succeeded": 0, "failed": 2, "retained": 1}
    retained, unknown = result["venues"]
    assert retained["result"] == "retained"
    assert retained["checked_at"] == "2026-09-01T00:00:00Z"
    assert unknown["result"] == "error"
    assert unknown["checked_at"] is None
    assert {row["error_code"] for row in result["venues"]} == {"membership_error"}
    assert "upstream timeout details" not in output.read_text(encoding="utf-8")


def test_atomic_persistence_replaces_complete_file(tmp_path, monkeypatch):
    output = tmp_path / "snapshot.json"
    old = "old-complete-file"
    output.write_text(old, encoding="utf-8")
    real_replace = tft_live_refresh.os.replace
    observed = []

    def replace(source, destination):
        observed.append((Path(source).read_text(encoding="utf-8"), output.read_text(encoding="utf-8")))
        real_replace(source, destination)

    monkeypatch.setattr(tft_live_refresh.os, "replace", replace)

    def fetch(path, _params, _versioned):
        return membership("2000") if path.startswith("/projects/") else slots()

    tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json", count=1),
        output,
        fetcher=fetch,
        clock=lambda: NOW,
    ).refresh()

    assert len(observed) == 1
    assert observed[0][1] == old
    assert json.loads(observed[0][0]) == json.loads(output.read_text(encoding="utf-8"))
    assert not list(tmp_path.glob(".snapshot.json.*"))


def test_concurrent_refresh_is_skipped_without_second_upstream_call(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fetch(path, _params, _versioned):
        calls.append(path)
        if path.startswith("/projects/"):
            entered.set()
            assert release.wait(2)
            return membership("2000")
        return slots()

    refresher = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json", count=1),
        tmp_path / "snapshot.json",
        fetcher=fetch,
        clock=lambda: NOW,
    )
    thread = threading.Thread(target=refresher.refresh)
    thread.start()
    assert entered.wait(1)
    assert refresher.refresh() is None
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert sum(path.startswith("/projects/") for path in calls) == 1


def test_output_and_fallback_request_counts_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(tft_live_refresh, "MAX_DATES_PER_VENUE", 3)
    monkeypatch.setattr(tft_live_refresh, "MAX_SLOTS_PER_MEAL", 20)
    calls = []

    def fetch(path, params, _versioned):
        calls.append((path, params))
        if path.startswith("/projects/"):
            return membership("2000")
        if path.endswith("/available_2018") and "selected_date" not in params:
            return {"data": []}
        if path.endswith("/dining_dates"):
            return [
                {"date": f"2026-10-{day:02d}", "available": True}
                for day in range(1, 10)
            ]
        return slots(params["selected_date"], extra=120)

    result = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json", count=1),
        tmp_path / "snapshot.json",
        fetcher=fetch,
        clock=lambda: NOW,
        max_workers=999,
    ).refresh()

    assert result is not None
    selected = [params["selected_date"] for _, params in calls if "selected_date" in params]
    assert selected == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert len(result["venues"]) <= tft_live_refresh.MAX_VENUES
    assert all(meal["meal"] in {"Lunch", "Dinner"} for meal in result["venues"][0]["meals"])
    assert all(
        len(meal["slots"]) <= tft_live_refresh.MAX_SLOTS_PER_MEAL
        for meal in result["venues"][0]["meals"]
    )
    assert len(json.dumps(result).encode()) <= tft_live_refresh.MAX_SNAPSHOT_BYTES


def test_worker_concurrency_is_bounded(tmp_path):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fetch(path, _params, _versioned):
        nonlocal active, peak
        if path.startswith("/projects/"):
            return membership(*(str(2000 + index) for index in range(8)))
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return slots()

    result = tft_live_refresh.TFTLiveRefresher(
        catalog(tmp_path / "catalog.json", count=8),
        tmp_path / "snapshot.json",
        fetcher=fetch,
        clock=lambda: NOW,
        max_workers=2,
    ).refresh()

    assert result is not None
    assert result["counts"]["succeeded"] == 8
    assert 1 < peak <= 2


def test_failed_atomic_replace_preserves_old_file_and_cleans_temp(tmp_path, monkeypatch):
    output = tmp_path / "snapshot.json"
    output.write_text("old-complete-file", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(tft_live_refresh.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        tft_live_refresh._atomic_write(output, prior_snapshot("venue-0"))
    assert output.read_text(encoding="utf-8") == "old-complete-file"
    assert not list(tmp_path.glob(".snapshot.json.*"))


def test_invalid_or_oversized_prior_snapshot_is_not_loaded(tmp_path, monkeypatch):
    output = tmp_path / "snapshot.json"
    output.write_text('{"schema_version":1}', encoding="utf-8")
    assert tft_live_refresh.load_snapshot(output) is None

    valid = prior_snapshot("venue-0")
    monkeypatch.setattr(tft_live_refresh, "MAX_SNAPSHOT_BYTES", 10)
    output.write_text(json.dumps(valid), encoding="utf-8")
    assert tft_live_refresh.load_snapshot(output) is None


def test_validate_snapshot_rejects_count_mismatch():
    invalid = prior_snapshot("venue-0")
    invalid["counts"]["succeeded"] = 0
    with pytest.raises(ValueError, match="counts"):
        tft_live_refresh.validate_snapshot(invalid)


def test_validate_snapshot_rejects_refresh_status_mismatch():
    invalid = prior_snapshot("venue-0")
    invalid["refresh_status"] = "partial"
    with pytest.raises(ValueError, match="refresh status"):
        tft_live_refresh.validate_snapshot(invalid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("generated_at", "not-a-date"),
        ("generated_at", "2026-09-02T04:05:06"),
    ],
)
def test_validate_snapshot_rejects_invalid_or_naive_timestamps(field, value):
    invalid = prior_snapshot("venue-0")
    invalid[field] = value
    with pytest.raises(ValueError, match="envelope"):
        tft_live_refresh.validate_snapshot(invalid)


def test_validate_snapshot_rejects_invalid_meal_status_and_result_pair():
    invalid = prior_snapshot("venue-0")
    invalid["venues"][0]["meals"][0]["status"] = "unknown"
    with pytest.raises(ValueError, match="venue"):
        tft_live_refresh.validate_snapshot(invalid)

    invalid = prior_snapshot("venue-0")
    invalid["venues"][0]["result"] = "fresh"
    invalid["venues"][0]["error_code"] = "network"
    with pytest.raises(ValueError, match="venue"):
        tft_live_refresh.validate_snapshot(invalid)


def test_default_fetch_rejects_wrong_content_type_and_oversized_body(monkeypatch):
    class Headers:
        def __init__(self, content_type, length=None):
            self.content_type = content_type
            self.length = length

        def get_content_type(self):
            return self.content_type

        def get(self, key):
            return self.length if key == "Content-Length" else None

    class Response:
        def __init__(self, body, content_type="application/json", length=None):
            self.body = body
            self.headers = Headers(content_type, length)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, amount):
            return self.body[:amount]

    monkeypatch.setattr(
        tft_live_refresh.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(b"{}", "text/html"),
    )
    with pytest.raises(ValueError, match="not JSON"):
        tft_live_refresh._default_fetch("/test", None, True)

    monkeypatch.setattr(tft_live_refresh, "MAX_UPSTREAM_BYTES", 8)
    monkeypatch.setattr(
        tft_live_refresh.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(b'{"payload":"too large"}'),
    )
    with pytest.raises(ValueError, match="too large"):
        tft_live_refresh._default_fetch("/test", None, True)
