from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main, telegram_reminder_dispatch, tft_guide, tft_live_api, tft_slot_source
from app.main import app
from app.telegram_bot_routes import get_settings
from tests.test_telegram_bot import (  # noqa: F401
    _enabled_reminder_settings,
    _seed_active_reminder,
    guide_client,
)


def live_payload(checked: datetime, requested_date: str) -> dict:
    stamp = checked.isoformat()
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": stamp,
        "refresh_status": "success",
        "counts": {"eligible": 1, "succeeded": 1, "failed": 0, "retained": 0},
        "venues": [
            {
                "id": "tft-vue",
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": stamp,
                "attempted_at": stamp,
                "result": "fresh",
                "error_code": None,
                "meals": [
                    {
                        "meal": "Dinner",
                        "status": "available",
                        "slots": [
                            {"date": requested_date, "time": "19:00", "max_seats": 4}
                        ],
                    }
                ],
            }
        ],
    }


def pages_payload(checked: datetime, requested_date: str) -> dict:
    payload = live_payload(checked, requested_date)
    for key in ("refresh_status", "counts"):
        payload.pop(key)
    return payload


@pytest.fixture()
def sources(tmp_path: Path, monkeypatch):
    """Point the live path at tmp and serve a Pages copy without network."""
    tft_slot_source.clear_cache()
    live_path = tmp_path / "tft-live-slots.json"
    pages: dict = {}
    fetches: list[int] = []
    monkeypatch.setattr(
        tft_slot_source,
        "load_settings",
        lambda: SimpleNamespace(tft_live_snapshot_path=live_path),
    )

    def fetch(_opener):
        fetches.append(1)
        if not pages:
            raise tft_slot_source.SlotSourceUnavailable("no pages copy")
        return tft_slot_source.validate_snapshot(pages["payload"])

    monkeypatch.setattr(tft_slot_source, "_fetch", fetch)
    yield SimpleNamespace(live_path=live_path, pages=pages, fetches=fetches)
    tft_slot_source.clear_cache()


def _future_date(now: datetime) -> str:
    return (now + timedelta(days=10)).date().isoformat()


def test_load_snapshot_prefers_fresh_live_file_without_fetching_pages(sources):
    now = datetime.now(timezone.utc)
    live = live_payload(now - timedelta(minutes=2), _future_date(now))
    sources.live_path.write_text(json.dumps(live))
    sources.pages["payload"] = pages_payload(now - timedelta(hours=10), _future_date(now))

    loaded = tft_slot_source.load_snapshot()

    assert tft_live_api.validated_snapshot(sources.live_path) is not None
    assert loaded["generated_at"] == live["generated_at"]
    assert sources.fetches == []


def test_load_snapshot_falls_back_to_pages_when_live_is_stale(sources):
    now = datetime.now(timezone.utc)
    sources.live_path.write_text(
        json.dumps(live_payload(now - timedelta(minutes=45), _future_date(now)))
    )
    pages = pages_payload(now - timedelta(hours=10), _future_date(now))
    sources.pages["payload"] = pages

    loaded = tft_slot_source.load_snapshot()

    assert loaded["generated_at"] == pages["generated_at"]
    assert sources.fetches == [1]


@pytest.mark.parametrize("body", ["{not json", json.dumps({"schema_version": 2})])
def test_load_snapshot_falls_back_to_pages_when_live_is_invalid(sources, body):
    now = datetime.now(timezone.utc)
    sources.live_path.write_text(body)
    pages = pages_payload(now - timedelta(hours=10), _future_date(now))
    sources.pages["payload"] = pages

    assert tft_slot_source.load_snapshot()["generated_at"] == pages["generated_at"]


def test_live_file_must_pass_slot_source_caps(sources):
    now = datetime.now(timezone.utc)
    live = live_payload(now - timedelta(minutes=2), _future_date(now))
    live["venues"][0]["meals"] *= 5
    sources.live_path.write_text(json.dumps(live))

    assert tft_slot_source.live_snapshot() is None


def test_guide_answer_uses_live_when_pages_copy_is_ten_hours_old(sources):
    now = datetime.now(timezone.utc)
    requested = _future_date(now)
    sources.live_path.write_text(
        json.dumps(live_payload(now - timedelta(minutes=2), requested))
    )
    sources.pages["payload"] = pages_payload(now - timedelta(hours=10), requested)

    result = tft_guide.handle_message(
        f"/slots VUE | 2 | dinner | {requested}", tft_guide.load_catalog(), now
    )

    assert result.startswith("Open tables, dinner for 2 at VUE on ")
    assert "too old to rely on" not in result
    assert sources.fetches == []


def test_guide_answer_reports_stale_when_only_old_pages_copy_exists(sources):
    now = datetime.now(timezone.utc)
    requested = _future_date(now)
    sources.pages["payload"] = pages_payload(now - timedelta(hours=10), requested)

    result = tft_guide.handle_message(
        f"/slots VUE | 2 | dinner | {requested}", tft_guide.load_catalog(), now
    )

    assert "too old to rely on" in result


def _reset_last_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_reminder_dispatch,
        "last_dispatch",
        dict.fromkeys(("at", "sent", "unknown", "dead", "error")),
    )


def test_in_process_dispatch_sends_from_live_snapshot_and_records_health(
    guide_client, sources, monkeypatch
):
    client, settings = guide_client
    settings = _enabled_reminder_settings(settings)
    now = datetime.now(timezone.utc)
    requested = _future_date(now)
    _seed_active_reminder(settings, now, requested)
    sources.live_path.write_text(
        json.dumps(live_payload(now - timedelta(minutes=2), requested))
    )
    sends = []
    monkeypatch.setattr(
        "app.telegram_reminder_dispatch.telegram.send_message",
        lambda *args: sends.append(args) or 77,
    )
    _reset_last_dispatch(monkeypatch)

    telegram_reminder_dispatch.dispatch_and_record(settings)
    health = client.get("/healthz").json()["telegram_reminder_dispatch"]
    telegram_reminder_dispatch.dispatch_and_record(settings)

    assert len(sends) == 1
    assert sends[0][1] == 4444
    assert sources.fetches == []
    assert set(health) == {"at", "sent", "unknown", "dead", "error"}
    assert (health["sent"], health["unknown"], health["dead"], health["error"]) == (
        1,
        0,
        0,
        None,
    )
    assert health["at"]


def test_in_process_dispatch_records_source_failure_without_raising(
    sources, monkeypatch, tmp_path
):
    _reset_last_dispatch(monkeypatch)

    telegram_reminder_dispatch.dispatch_and_record(SimpleNamespace(db_path=tmp_path))

    assert telegram_reminder_dispatch.last_dispatch["error"] == "slot_source_unavailable"


def test_concurrent_route_and_loop_send_each_notification_once(
    guide_client, sources, monkeypatch
):
    client, settings = guide_client
    settings = _enabled_reminder_settings(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    now = datetime.now(timezone.utc)
    requested = _future_date(now)
    _seed_active_reminder(settings, now, requested)
    live = live_payload(now - timedelta(minutes=2), requested)
    sources.live_path.write_text(json.dumps(live))
    sends = []

    def slow_send(*args):
        sends.append(args)
        time.sleep(0.2)
        return 88

    monkeypatch.setattr("app.telegram_reminder_dispatch.telegram.send_message", slow_send)
    start = threading.Barrier(2)
    responses = []

    def route() -> None:
        start.wait()
        responses.append(
            client.post(
                "/api/internal/telegram/reminders/dispatch",
                json={"expected_generated_at": "2026-08-30T04:00:00+00:00"},
                headers={"X-Telegram-Reminder-Dispatch-Token": "d" * 43},
            )
        )

    def loop() -> None:
        start.wait()
        telegram_reminder_dispatch.dispatch_and_record(settings)

    threads = [threading.Thread(target=route), threading.Thread(target=loop)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(sends) == 1
    assert responses[0].status_code == 200


def test_lifespan_starts_reminder_loop_only_when_enabled(monkeypatch):
    ran = threading.Event()
    monkeypatch.setattr(
        telegram_reminder_dispatch, "dispatch_and_record", lambda _settings: ran.set()
    )

    with TestClient(app):
        assert not ran.wait(timeout=0.25)
    monkeypatch.setattr(
        main, "settings", replace(main.settings, telegram_reminders_enabled=True)
    )
    with TestClient(app):
        assert ran.wait(timeout=1)


def test_snapshot_with_extra_diningcity_meal_types_is_still_valid() -> None:
    import json
    from pathlib import Path

    from app import tft_slot_source

    payload = json.loads((Path(__file__).resolve().parents[2] / "data" / "table-for-two-slots.json").read_text())
    venue = payload["venues"][0]
    venue["meals"] = list(venue.get("meals") or [])[:2] + [
        {"meal": "Afternoon Tea", "status": "available", "slots": []},
    ]

    tft_slot_source.validate_snapshot(payload)


def test_snapshot_with_a_malicious_meal_name_is_rejected() -> None:
    import json
    from pathlib import Path

    import pytest

    from app import tft_slot_source

    payload = json.loads((Path(__file__).resolve().parents[2] / "data" / "table-for-two-slots.json").read_text())
    payload["venues"][0]["meals"] = [{"meal": "<script>", "status": "available", "slots": []}]

    with pytest.raises(ValueError):
        tft_slot_source.validate_snapshot(payload)
