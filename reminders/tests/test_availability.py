from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app import availability


NOW = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


_DATA = {
    "venues": [
        {
            "name": "15 Stamford Restaurant",
            "availability": {
                "status": "live_available",
                "checked_at": "2026-08-30T00:50:00Z",
                "meals": [{"meal": "Dinner", "status": "available"}],
            },
        },
        {
            "name": "Cultivate",
            "availability": {"status": "no_availability", "meals": []},
        },
    ]
}


def _patch(monkeypatch, payload):
    monkeypatch.setattr(
        availability.urllib.request, "urlopen", lambda url, timeout=4: _Resp(payload)
    )


def test_open_tables_exist_matches_venue_and_session(monkeypatch):
    _patch(monkeypatch, _DATA)

    assert availability.open_tables_exist(
        ["15 Stamford Restaurant"], ["Dinner"], "http://x", now=NOW
    )
    assert availability.open_tables_exist(["any"], ["Dinner"], "http://x", now=NOW)


def test_open_tables_exist_no_match(monkeypatch):
    _patch(monkeypatch, _DATA)

    # right venue, wrong session
    assert not availability.open_tables_exist(
        ["15 Stamford Restaurant"], ["Lunch"], "http://x", now=NOW
    )
    # venue with no live availability
    assert not availability.open_tables_exist(
        ["Cultivate"], ["Dinner"], "http://x", now=NOW
    )


def test_open_tables_exist_rejects_stale_or_unverifiable_availability(monkeypatch):
    for checked_at in (
        (NOW - timedelta(minutes=31)).isoformat(),
        (NOW + timedelta(minutes=6)).isoformat(),
        None,
        "not-a-date",
    ):
        payload = json.loads(json.dumps(_DATA))
        if checked_at is None:
            payload["venues"][0]["availability"].pop("checked_at")
        else:
            payload["venues"][0]["availability"]["checked_at"] = checked_at
        _patch(monkeypatch, payload)
        assert not availability.open_tables_exist(
            ["any"], ["Dinner"], "http://x", now=NOW
        )


def test_open_tables_exist_fails_closed_on_error(monkeypatch):
    def boom(url, timeout=4):
        raise OSError("network down")

    monkeypatch.setattr(availability.urllib.request, "urlopen", boom)

    assert not availability.open_tables_exist(
        ["any"], ["Dinner"], "http://x", now=NOW
    )
