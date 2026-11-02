from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient

from app import main, tft_live_api, tft_live_refresh
from tests.test_tft_live_api import settings, snapshot, write_snapshot


NOW = datetime(2026, 9, 2, 4, 5, 6, tzinfo=timezone.utc)
CENT = tft_live_refresh.CENTURION_PROJECT


def centurion_catalog() -> dict:
    return {
        "venues": [{"id": "tft-vue", "dining_city_id": "100"}],
        "centurion_venues": [
            {"id": "tft-jaan", "dining_city_id": "200"},
            {"id": "tft-zui-yu-xuan", "dining_city_id": "300", "linked_only": True},
            {"id": "tft-gone", "dining_city_id": "400"},
        ],
    }


def day(date: str = "2026-09-20") -> dict:
    return {"data": [{"date": date, "times": [
        {"meal_type_text": "Lunch", "time": "11:45", "seats": {"available": [2, 4]}},
    ]}]}


def run_centurion(tmp_path, calls):
    def fetch(path, params, versioned):
        calls.append((path, dict(params or {})))
        if path.startswith("/projects/"):
            return [{"restaurant": {"id": "200"}}, {"restaurant": {"id": "100"}}]
        return day()

    return tft_live_refresh.TFTLiveRefresher(
        centurion_catalog,
        tmp_path / "slots-centurion.json",
        fetcher=fetch,
        clock=lambda: NOW,
        project=CENT,
        venues_key="centurion_venues",
    ).refresh()


def test_centurion_refresh_asks_the_centurion_project_for_centurion_venues(tmp_path):
    calls = []
    result = run_centurion(tmp_path, calls)

    assert result["source_project"] == CENT
    assert {row["project"] for row in result["venues"]} == {CENT}
    assert [row["id"] for row in result["venues"]] == ["tft-gone", "tft-jaan", "tft-zui-yu-xuan"]
    assert ("/projects/AMEXCentSG/restaurants", {"per_page": 100}) in calls
    assert all(params.get("project") == CENT for path, params in calls if "/restaurants/" in path and not path.startswith("/projects/"))
    assert not any("/restaurants/100/" in path for path, _ in calls)


def test_linked_only_venue_is_checked_though_missing_from_the_project_list(tmp_path):
    result = run_centurion(tmp_path, [])
    by_id = {row["id"]: row for row in result["venues"]}

    assert by_id["tft-zui-yu-xuan"]["status"] == "live_available"
    assert by_id["tft-jaan"]["meals"][0]["slots"] == [{"date": "2026-09-20", "time": "11:45", "max_seats": 4}]
    assert by_id["tft-gone"]["error_code"] == "not_in_project"


def test_snapshots_load_only_under_their_own_project(tmp_path):
    run_centurion(tmp_path, [])
    path = tmp_path / "slots-centurion.json"

    assert tft_live_refresh.load_snapshot(path, project=CENT)["source_project"] == CENT
    assert tft_live_refresh.load_snapshot(path) is None


def test_centurion_endpoint_serves_its_own_snapshot(tmp_path):
    platinum = tmp_path / "slots.json"
    write_snapshot(platinum)
    run_centurion(tmp_path, [])
    main.app.dependency_overrides[tft_live_api.get_settings] = lambda: settings(platinum)
    try:
        client = TestClient(main.app)
        centurion = client.get("/api/tft/slots/centurion")
        default = client.get("/api/tft/slots")
    finally:
        main.app.dependency_overrides.clear()

    assert centurion.status_code == 200
    assert centurion.json()["source_project"] == CENT
    assert centurion.headers["cache-control"] == "no-store"
    assert default.json() == snapshot()


def test_centurion_endpoint_returns_503_without_a_snapshot(tmp_path):
    platinum = tmp_path / "slots.json"
    write_snapshot(platinum)
    main.app.dependency_overrides[tft_live_api.get_settings] = lambda: settings(platinum)
    try:
        response = TestClient(main.app).get("/api/tft/slots/centurion")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Live slot snapshot unavailable"}


def test_centurion_snapshot_path_sits_beside_the_platinum_one(tmp_path):
    assert tft_live_api.centurion_snapshot_path(tmp_path / "tft-live-slots.json") == (
        tmp_path / "tft-live-slots-centurion.json"
    )
