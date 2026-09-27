from __future__ import annotations

from scripts import sync_japan_mvp

FETCHED_AT = "2026-09-27T00:00:00+00:00"


def venue(venue_id: str, verified_at: str, dinner_max: int = 16000) -> dict:
    return {
        "id": venue_id,
        "name": venue_id,
        "city": "Tokyo",
        "price_dinner_max_jpy": dinner_max,
        "last_verified_at": verified_at,
        "lat": 35.0,
        "lng": 139.0,
    }


def records_sha(records: list[dict]) -> str:
    return sync_japan_mvp.build_source_meta(records, FETCHED_AT)["records_sha256"]


def test_records_hash_ignores_verification_time_and_order():
    first = [venue("pocket-1", "2026-09-25T00:00:00+00:00"), venue("pocket-2", "2026-09-25T00:00:00+00:00")]

    second = [venue("pocket-2", "2026-09-26T00:00:00+00:00"), venue("pocket-1", "2026-09-26T00:00:00+00:00")]

    assert records_sha(first) == records_sha(second)


def test_records_hash_changes_when_displayed_price_changes():
    before = [venue("pocket-1", "2026-09-25T00:00:00+00:00")]

    after = [venue("pocket-1", "2026-09-25T00:00:00+00:00", dinner_max=17600)]

    assert records_sha(before) != records_sha(after)
