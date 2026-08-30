from __future__ import annotations

import json
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import tft_slot_source


class Response:
    def __init__(
        self,
        payload: bytes,
        status: int = 200,
        content_type: str = "application/json",
        content_length: str | None = None,
    ):
        self.payload = payload
        self.status = status
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": content_length or str(len(payload)),
        }

    def getcode(self):
        return self.status

    def read(self, limit):
        return self.payload[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": "2026-08-30T03:00:00Z",
        "venues": [
            {
                "id": "tft-vue",
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": "2026-08-30T03:00:00Z",
                "meals": [
                    {
                        "meal": "Dinner",
                        "status": "available",
                        "slots": [
                            {
                                "date": "2026-10-29",
                                "time": "19:00",
                                "max_seats": 2,
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture(autouse=True)
def reset_cache():
    tft_slot_source.clear_cache()
    yield
    tft_slot_source.clear_cache()


def opener_for(payload: dict, *, status=200, content_type="application/json"):
    body = json.dumps(payload).encode()

    def opener(request, timeout):
        assert request.full_url == tft_slot_source.SOURCE_URL
        assert timeout == 4
        return Response(body, status=status, content_type=content_type)

    return opener


def test_exact_fixed_source_is_loaded_and_validated():
    assert tft_slot_source.load_snapshot(opener_for(snapshot()), lambda: 0) == snapshot()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(source_project="GenericDiningCity"),
        lambda payload: payload["venues"][0].update(project="GenericDiningCity"),
        lambda payload: payload["venues"][0].update(checked_at="naive"),
        lambda payload: payload["venues"][0]["meals"][0]["slots"][0].update(
            max_seats=99
        ),
    ],
)
def test_invalid_schema_or_provenance_fails_closed(mutator):
    payload = snapshot()
    mutator(payload)

    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(opener_for(payload), lambda: 0)


def test_redirect_and_non_json_are_rejected():
    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(
            opener_for(snapshot(), status=302), lambda: 0
        )
    tft_slot_source.clear_cache()
    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(
            opener_for(snapshot(), content_type="text/html"), lambda: 0
        )


def test_streamed_and_advertised_oversize_are_rejected():
    oversized = b"x" * (tft_slot_source.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(
            lambda *_args, **_kwargs: Response(oversized), lambda: 0
        )
    tft_slot_source.clear_cache()
    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(
            lambda *_args, **_kwargs: Response(
                b"{}", content_length=str(tft_slot_source.MAX_RESPONSE_BYTES + 1)
            ),
            lambda: 0,
        )


def test_positive_cache_and_single_flight_make_one_request():
    calls = 0
    calls_lock = threading.Lock()
    body = json.dumps(snapshot()).encode()

    def opener(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.02)
        return Response(body)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: tft_slot_source.load_snapshot(opener, lambda: 0),
                range(8),
            )
        )

    assert calls == 1
    assert all(result == snapshot() for result in results)


def test_expired_last_known_good_is_returned_as_original_stale_data():
    first = tft_slot_source.load_snapshot(opener_for(snapshot()), lambda: 0)

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    second = tft_slot_source.load_snapshot(fail, lambda: 61)

    assert second is first
    assert second["venues"][0]["checked_at"] == "2026-08-30T03:00:00Z"


def test_negative_cache_does_not_repeat_failed_fetch():
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError

    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(fail, lambda: 0)
    with pytest.raises(tft_slot_source.SlotSourceUnavailable):
        tft_slot_source.load_snapshot(fail, lambda: 1)

    assert calls == 1
