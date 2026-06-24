from __future__ import annotations

import json

from app import availability


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
        ["15 Stamford Restaurant"], ["Dinner"], "http://x"
    )
    assert availability.open_tables_exist(["any"], ["Dinner"], "http://x")


def test_open_tables_exist_no_match(monkeypatch):
    _patch(monkeypatch, _DATA)

    # right venue, wrong session
    assert not availability.open_tables_exist(
        ["15 Stamford Restaurant"], ["Lunch"], "http://x"
    )
    # venue with no live availability
    assert not availability.open_tables_exist(["Cultivate"], ["Dinner"], "http://x")


def test_open_tables_exist_fails_closed_on_error(monkeypatch):
    def boom(url, timeout=4):
        raise OSError("network down")

    monkeypatch.setattr(availability.urllib.request, "urlopen", boom)

    assert not availability.open_tables_exist(["any"], ["Dinner"], "http://x")
