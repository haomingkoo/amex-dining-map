"""/release replies, the best-time line and the public patterns endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import main, tft_guide, tft_patterns


NOW = datetime(2026, 10, 26, 13, tzinfo=timezone.utc)


def _venue(**release) -> dict:
    return {
        "id": "tft-colony",
        "name": "Colony",
        "aliases": [],
        "release": {
            "lines": ["Until 30 Sep, new lunch dates opened one day at a time, 61 days ahead. None since."],
            "best_time": None,
            "meals": [{"meal": "Lunch", "rolling_lead_days": 61, "quiet_days": 26}],
            "furthest_open_dates": {"Lunch": "2026-11-30"},
        } | release,
    }


def _catalog(venue: dict) -> dict:
    return {"venues": [venue], "eligibility_source": {"new_dates_since": "2026-08-19"}}


def test_quiet_venue_points_at_cancellations():
    reply = tft_patterns.release_reply(_venue(), _catalog(_venue()), {"started_at": None, "venues": {}}, "link")
    assert reply.startswith("Colony: when tables appear")
    assert "New dates (tracked since 19 Aug 2026):" in reply
    assert "Open dates currently run to 30 Nov." in reply
    assert "cancellations are the main chance" in reply
    assert "How long tables last" not in reply


def test_live_history_lines_and_combined_best_time():
    venue = _venue(best_time="lunch between 11 am and 1 pm, 61 days ahead", meals=[])
    live = {
        "started_at": "2026-10-26T13:00:00Z",
        "venues": {"tft-colony": {"lines": ["New tables have usually gone within 10 minutes."],
                                  "best_return_bucket": "weekday morning", "returned_tables": 14}},
    }
    reply = tft_patterns.release_reply(venue, _catalog(venue), live, "link")
    assert "How long tables last (tracked since 26 Oct 2026):" in reply
    assert "• New tables have usually gone within 10 minutes." in reply
    assert (
        "Best time to look: lunch between 11 am and 1 pm, 61 days ahead for new dates; "
        "weekday mornings for cancellations." in reply
    )


def test_early_live_history_says_too_early():
    live = {"started_at": "2026-10-26T13:00:00Z", "venues": {"tft-colony": {"lines": [], "returned_tables": 1}}}
    reply = tft_patterns.release_reply(_venue(), _catalog(_venue()), live, "link")
    assert "• Too early to say. 1 table has come back so far." in reply


def test_unsafe_lines_and_buckets_are_dropped():
    venue = _venue(lines=["ok line", "bad\nline https://attacker.example", "x" * 500])
    live = {"started_at": None, "venues": {"tft-colony": {"best_return_bucket": "weekday\nmorning"}}}
    reply = tft_patterns.release_reply(venue, _catalog(venue), live, "link")
    assert "attacker.example" not in reply
    assert "x" * 300 not in reply
    assert "• ok line" in reply
    assert "weekday\nmorning" not in reply


def test_no_history_says_so():
    venue = {"id": "v", "name": "V", "release": {}}
    assert tft_patterns.best_time_line(venue, None) == "Best time to look: not enough history yet to say."


def test_release_command_and_venue_reply_use_live_loader():
    venue = _venue(best_time="dinner around midnight, 60 days ahead", meals=[])
    catalog = _catalog(venue) | {"official_url": "https://www.americanexpress.com/x", "roster_checked_at": NOW.isoformat()}
    live = {"started_at": "2026-10-26T13:00:00Z", "venues": {"tft-colony": {"best_return_bucket": "weekend evening", "lines": []}}}
    reply = tft_guide.handle_message("/release Colony", catalog, NOW, live_loader=lambda: live)
    assert "weekend evenings for cancellations" in reply


def test_patterns_endpoint_lists_every_catalog_venue():
    with TestClient(main.app) as client:
        response = client.get("/api/tft/patterns")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    ids = {venue["id"] for venue in tft_guide.load_catalog()["venues"]}
    assert set(body["venues"]) == ids
    assert all(entry["best_time"].startswith("Best time to look:") for entry in body["venues"].values())
    assert response.headers["cache-control"] == "no-store"


def test_website_best_time_omits_the_telegram_command():
    venue = _venue()
    assert "/remind" in tft_patterns.best_time_line(venue, None)
    web = tft_patterns.best_time_line(venue, None, remind_hint=False)
    assert web == "Best time to look: no new dates are opening right now, so cancellations are the main chance."
    with TestClient(main.app) as client:
        body = client.get("/api/tft/patterns").json()
    assert not any("/remind" in entry["best_time"] for entry in body["venues"].values())
