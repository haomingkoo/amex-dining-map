from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient
import pytest

from app import main, tft_live_api
from app.config import Settings, load_settings


GENERATED_AT = "2026-09-02T00:00:00Z"


def settings(snapshot_path: Path, **overrides) -> Settings:
    base = Settings(
        db_path=snapshot_path.with_name("test.db"),
        resend_api_key="",
        resend_from="test@example.com",
        alert_export_token="test-token",
        allowed_origin="https://amex-explorer.kooexperience.com",
        public_base_url="http://testserver",
        confirm_token_expiry_hours=168,
        table_data_url="https://example.test/table-for-two.json",
        tft_live_snapshot_path=snapshot_path,
    )
    return replace(base, **overrides)


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": GENERATED_AT,
        "refresh_status": "success",
        "counts": {"eligible": 1, "succeeded": 1, "failed": 0, "retained": 0},
        "venues": [
            {
                "id": "vue",
                "project": "AMEXPlatSG",
                "status": "live_no_seats",
                "checked_at": GENERATED_AT,
                "attempted_at": GENERATED_AT,
                "result": "fresh",
                "error_code": None,
                "meals": [],
            }
        ],
    }


def write_snapshot(path: Path, payload: dict | None = None) -> None:
    path.write_text(json.dumps(payload or snapshot()), encoding="utf-8")


def test_live_settings_defaults_and_snapshot_path_follow_db(monkeypatch, tmp_path):
    db_path = tmp_path / "state" / "reminders.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("TFT_LIVE_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("TFT_LIVE_REFRESH_ENABLED", raising=False)
    monkeypatch.delenv("TFT_LIVE_REFRESH_INTERVAL_SECONDS", raising=False)

    configured = load_settings()

    assert configured.tft_live_refresh_enabled is False
    assert configured.tft_live_refresh_interval_seconds == 600
    assert configured.tft_live_snapshot_path == db_path.parent / "tft-live-slots.json"


@pytest.mark.parametrize("interval", [59, 1801])
def test_live_refresh_interval_rejects_out_of_bounds(monkeypatch, interval):
    monkeypatch.setenv("TFT_LIVE_REFRESH_INTERVAL_SECONDS", str(interval))

    with pytest.raises(RuntimeError, match="between 60 and 1800"):
        load_settings()


@pytest.mark.parametrize("interval", [60, 1800])
def test_live_refresh_interval_accepts_bounds(monkeypatch, interval):
    monkeypatch.setenv("TFT_LIVE_REFRESH_INTERVAL_SECONDS", str(interval))

    assert load_settings().tft_live_refresh_interval_seconds == interval


def test_live_refresh_requires_single_replica_confirmation(monkeypatch):
    monkeypatch.setenv("TFT_LIVE_REFRESH_ENABLED", "true")
    monkeypatch.setenv("TFT_LIVE_SINGLE_REPLICA_CONFIRMED", "false")

    with pytest.raises(RuntimeError, match="SINGLE_REPLICA_CONFIRMED"):
        load_settings()


def test_slots_endpoint_returns_validated_no_store_snapshot(tmp_path):
    path = tmp_path / "slots.json"
    write_snapshot(path)
    main.app.dependency_overrides[tft_live_api.get_settings] = lambda: settings(path)
    try:
        response = TestClient(main.app).get("/api/tft/slots")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-encoding"] == "gzip"


@pytest.mark.parametrize("contents", [None, "not json"])
def test_slots_endpoint_returns_safe_503_when_snapshot_unavailable(
    tmp_path, contents
):
    path = tmp_path / "slots.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    main.app.dependency_overrides[tft_live_api.get_settings] = lambda: settings(path)
    try:
        response = TestClient(main.app).get("/api/tft/slots")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Live slot snapshot unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert str(path) not in response.text


def test_snapshot_health_is_bounded_and_omits_venue_errors(tmp_path):
    path = tmp_path / "slots.json"
    payload = snapshot()
    payload["refresh_status"] = "error"
    payload["counts"] = {"eligible": 1, "succeeded": 0, "failed": 1, "retained": 0}
    payload["venues"][0].update(
        {
            "status": "unknown",
            "checked_at": None,
            "result": "error",
            "error_code": "timeout",
        }
    )
    write_snapshot(path, payload)

    health = tft_live_api.snapshot_health(
        path, now=datetime(2026, 9, 2, 0, 1, tzinfo=timezone.utc)
    )

    assert health == {
        "status": "error",
        "generated_at": GENERATED_AT,
        "age_seconds": 60,
        "counts": {"eligible": 1, "succeeded": 0, "failed": 1, "retained": 0},
    }
    assert "error_code" not in json.dumps(health)


def test_snapshot_health_marks_an_old_success_stale(tmp_path):
    path = tmp_path / "slots.json"
    write_snapshot(path)

    health = tft_live_api.snapshot_health(
        path, now=datetime(2026, 9, 2, 0, 30, 1, tzinfo=timezone.utc)
    )

    assert health["status"] == "stale"
    assert health["age_seconds"] == 1_801
    assert health["counts"] == {
        "eligible": 1,
        "succeeded": 1,
        "failed": 0,
        "retained": 0,
    }


def test_refresh_loop_runs_immediately_then_uses_fixed_delay():
    events: list[object] = []

    class Refresher:
        def refresh(self):
            events.append("refresh")

    async def fake_to_thread(call):
        call()

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))
        if events.count("refresh") == 2:
            raise asyncio.CancelledError

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await main.run_live_refresh_loop(
                Refresher(), 123, to_thread=fake_to_thread, sleep=fake_sleep
            )

    asyncio.run(scenario())
    assert events == ["refresh", ("sleep", 123), "refresh", ("sleep", 123)]


def test_refresh_loop_cancels_cleanly_after_immediate_attempt():
    refreshed = asyncio.Event()

    class Refresher:
        def refresh(self):
            pass

    async def fake_to_thread(call):
        call()
        refreshed.set()

    async def scenario():
        task = asyncio.create_task(
            main.run_live_refresh_loop(Refresher(), 600, to_thread=fake_to_thread)
        )
        await asyncio.wait_for(refreshed.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_app_lifespan_starts_one_immediate_refresh_without_network(monkeypatch):
    refreshed = threading.Event()

    class Refresher:
        def refresh(self):
            refreshed.set()

    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            tft_live_refresh_enabled=True,
            tft_live_refresh_interval_seconds=600,
            tft_live_single_replica_confirmed=True,
        ),
    )
    monkeypatch.setattr(main, "live_refresher", Refresher())

    with TestClient(main.app):
        assert refreshed.wait(timeout=1)
