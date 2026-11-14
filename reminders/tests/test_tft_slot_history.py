"""Slot spans recorded from live snapshots, and the verdicts drawn from them."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app import tft_patterns, tft_slot_history


START = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)  # Mon 9 am SGT


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    tft_slot_history.init_db(conn)
    return conn


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _snap(moment: datetime, slots: dict[str, list[tuple[str, str]]], result: str = "fresh") -> dict:
    venues = []
    for venue_id, pairs in slots.items():
        venues.append({
            "id": venue_id,
            "status": "live_available" if pairs else "live_no_seats",
            "result": result,
            "checked_at": _iso(moment),
            "meals": [{"meal": "Lunch", "slots": [{"date": d, "time": t, "max_seats": 2} for d, t in pairs]}],
        })
    return {"generated_at": _iso(moment), "venues": venues}


def _spans(conn):
    return conn.execute(
        "SELECT slot_date, slot_time, kind, close_reason FROM tft_slot_spans ORDER BY id"
    ).fetchall()


def test_first_snapshot_is_baseline_then_new_return_and_expiry():
    conn = _conn()
    base = [("2026-12-01", "12:00"), ("2026-12-02", "12:00")]
    assert tft_slot_history.record(conn, _snap(START, {"v": base})) == {"baseline": 2}
    # A date past the furthest one open is new; a slot booked out then back is a return.
    t1 = START + timedelta(minutes=5)
    tft_slot_history.record(conn, _snap(t1, {"v": [("2026-12-02", "12:00"), ("2026-12-03", "12:00")]}))
    t2 = START + timedelta(minutes=10)
    tft_slot_history.record(conn, _snap(t2, {"v": base + [("2026-12-03", "12:00")]}))
    rows = _spans(conn)
    assert ("2026-12-01", "12:00", "baseline", "gone") in rows
    assert ("2026-12-03", "12:00", "new", None) in rows
    assert ("2026-12-01", "12:00", "return", None) in rows


def test_slot_whose_time_passed_closes_as_expired():
    conn = _conn()
    soon = (START + timedelta(hours=1)).astimezone(tft_slot_history.SGT)
    key = (soon.date().isoformat(), soon.strftime("%H:%M"))
    tft_slot_history.record(conn, _snap(START, {"v": [key]}))
    tft_slot_history.record(conn, _snap(START + timedelta(hours=2), {"v": []}))
    assert _spans(conn)[0][3] == "expired"


def test_retained_and_stale_venues_are_ignored():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": [("2026-12-01", "12:00")]}, result="retained"))
    assert _spans(conn) == []
    snapshot = _snap(START, {"v": [("2026-12-01", "12:00")]})
    snapshot["venues"][0]["checked_at"] = _iso(START - timedelta(minutes=5))
    tft_slot_history.record(conn, snapshot)
    assert _spans(conn) == []


def test_mass_disappearance_is_treated_as_a_bad_read():
    conn = _conn()
    many = [("2026-12-01", f"{h:02d}:{m:02d}") for h in range(10, 22) for m in (0, 15, 30, 45)]
    tft_slot_history.record(conn, _snap(START, {"v": many}))
    counts = tft_slot_history.record(conn, _snap(START + timedelta(minutes=5), {"v": many[:2]}))
    assert counts == {"skipped": 1}
    assert all(row[3] is None for row in _spans(conn))


def test_summary_states_durations_and_return_times_only_with_enough_data():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": [("2026-12-01", "12:00")]}))
    moment = START
    for n in range(12):
        # Each cycle: a new date appears, then a cancellation returns, then both go.
        new_day = f"2026-12-{n + 2:02d}"
        moment += timedelta(minutes=5)
        tft_slot_history.record(conn, _snap(moment, {"v": [("2026-12-01", "12:00"), (new_day, "12:00")]}))
        moment += timedelta(minutes=5)
        tft_slot_history.record(conn, _snap(moment, {"v": []}))
        moment += timedelta(minutes=5)
        tft_slot_history.record(conn, _snap(moment, {"v": [("2026-12-01", "12:00")]}))
    summary = tft_slot_history.summary(conn, moment)
    venue = summary["venues"]["v"]
    assert venue["new_tables"] == 12
    assert venue["returned_tables"] == 12
    assert "New tables have usually gone within 10 minutes." in venue["lines"]
    assert venue["best_return_bucket"] == "weekday morning"
    assert "Cancellations have come back most often on weekday mornings." in venue["lines"]
    assert summary["started_at"] == _iso(START)


def test_thin_data_gives_no_verdict():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": []}))
    tft_slot_history.record(conn, _snap(START + timedelta(minutes=5), {"v": [("2026-12-05", "12:00")]}))
    tft_slot_history.record(conn, _snap(START + timedelta(minutes=10), {"v": []}))
    venue = tft_slot_history.summary(conn, START + timedelta(minutes=10))["venues"]["v"]
    assert venue["lines"] == []
    assert venue["best_return_bucket"] is None


def test_record_snapshot_reports_storage_errors_in_health(tmp_path):
    bad = tmp_path / "missing" / "dir"
    bad.mkdir(parents=True)
    tft_patterns.record_snapshot(bad, _snap(START, {"v": []}))  # a directory is not a database
    assert tft_patterns.last_record["error"]


def _many(day: str) -> list[tuple[str, str]]:
    return [(day, f"{h:02d}:{m:02d}") for h in range(10, 22) for m in (0, 15, 30, 45)]


def test_suspect_drop_is_reported_with_venue_and_since():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": _many("2026-12-01")}))
    t1 = START + timedelta(minutes=10)
    tft_slot_history.record(conn, _snap(t1, {"v": _many("2026-12-20")}))
    [suspect] = tft_slot_history.suspect_venues(conn)
    assert suspect["venue_id"] == "v"
    assert suspect["since"] == _iso(t1)
    assert suspect["checks"] == 1
    assert suspect["vanished"] == 48 and suspect["open"] == 48


def test_drop_that_persists_is_accepted_as_a_sellout():
    # Madame Fan, Nov 2026: every baseline date booked out while new dates opened
    # further out. The guard skipped it on every check for 12 days.
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": _many("2026-12-01")}))
    first = START + timedelta(minutes=10)
    moment = first
    while moment - first < tft_slot_history.SUSPECT_CONFIRM_AFTER:
        assert tft_slot_history.record(conn, _snap(moment, {"v": _many("2026-12-20")})) == {"skipped": 1}
        moment += timedelta(minutes=10)
    counts = tft_slot_history.record(conn, _snap(moment, {"v": _many("2026-12-20")}))
    assert counts == {"confirmed_drop": 1, "gone": 48, "baseline": 48}
    rows = _spans(conn)
    assert sum(1 for r in rows if r[0] == "2026-12-01" and r[3] == "gone") == 48
    assert sum(1 for r in rows if r[0] == "2026-12-20" and r[2] == "baseline" and r[3] is None) == 48
    assert tft_slot_history.suspect_venues(conn) == []


def test_one_bad_read_clears_the_suspect_without_closing_spans():
    conn = _conn()
    many = _many("2026-12-01")
    tft_slot_history.record(conn, _snap(START, {"v": many}))
    tft_slot_history.record(conn, _snap(START + timedelta(minutes=10), {"v": many[:2]}))
    counts = tft_slot_history.record(conn, _snap(START + timedelta(minutes=20), {"v": many}))
    assert counts == {}
    assert all(row[3] is None for row in _spans(conn))
    assert tft_slot_history.suspect_venues(conn) == []


def test_expired_slots_do_not_count_towards_a_suspect_drop():
    # Spans whose time has passed vanish because time moved on, not because of a bad read.
    conn = _conn()
    soon = (START + timedelta(hours=1)).astimezone(tft_slot_history.SGT).date().isoformat()
    past = [(soon, f"{h:02d}:{m:02d}") for h in range(0, 12) for m in (0, 15, 30, 45)]
    future = [("2026-12-05", "12:00")]
    tft_slot_history.record(conn, _snap(START, {"v": past + future}))
    counts = tft_slot_history.record(conn, _snap(START + timedelta(days=1), {"v": future}))
    assert counts == {"expired": 48}


def test_health_reports_skipped_venues(tmp_path):
    path = tmp_path / "r.db"
    tft_patterns.record_snapshot(path, _snap(START, {"v": _many("2026-12-01")}))
    tft_patterns.record_snapshot(path, _snap(START + timedelta(minutes=10), {"v": _many("2026-12-20")}))
    health = tft_patterns.last_record
    assert health["status"] == "degraded"
    assert [s["venue_id"] for s in health["suspect_venues"]] == ["v"]
    assert health["suspect_venues"][0]["since"] == _iso(START + timedelta(minutes=10))
