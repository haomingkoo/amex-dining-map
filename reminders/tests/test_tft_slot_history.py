"""Slot spans recorded from live snapshots, and the verdicts drawn from them."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main, tft_patterns, tft_slot_history


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


def test_hold_that_cannot_confirm_turns_health_failing(tmp_path, monkeypatch):
    # The held venue stops coming back fresh, so the hold never confirms and must not sit quietly.
    monkeypatch.setattr(tft_patterns, "last_record", dict(tft_patterns.last_record))
    path = tmp_path / "r.db"
    tft_patterns.record_snapshot(path, _snap(START, {"v": _many("2026-12-01")}))
    held = START + timedelta(minutes=10)
    tft_patterns.record_snapshot(path, _snap(held, {"v": _many("2026-12-20")}))
    assert tft_patterns.last_record["status"] == "degraded"
    later = held + tft_slot_history.SUSPECT_ESCALATE_AFTER + timedelta(minutes=10)
    tft_patterns.record_snapshot(path, _snap(later, {"v": _many("2026-12-20")}, result="retained"))
    assert tft_patterns.last_record["status"] == "failing"
    assert tft_patterns.last_record["suspect_venues"][0]["since"] == _iso(held)

    payload = TestClient(main.app).get("/healthz").json()
    assert payload["ok"] is False
    assert payload["tft_slot_history"]["status"] == "failing"


def test_venue_removed_from_the_roster_closes_its_spans_as_removed():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"gone": _many("2026-12-01"), "kept": [("2026-12-01", "12:00")]}))
    t1 = START + timedelta(minutes=10)
    tft_slot_history.record(conn, _snap(t1, {"gone": [], "kept": [("2026-12-01", "12:00")]}))
    assert tft_slot_history.suspect_venues(conn)[0]["venue_id"] == "gone"

    counts = tft_slot_history.record(conn, _snap(t1 + timedelta(minutes=10), {"kept": [("2026-12-01", "12:00")]}))
    assert counts == {"removed": 48}
    reasons = conn.execute(
        "SELECT venue_id, close_reason, COUNT(*) FROM tft_slot_spans GROUP BY 1, 2 ORDER BY 1"
    ).fetchall()
    assert reasons == [("gone", "removed", 48), ("kept", None, 1)]
    assert tft_slot_history.suspect_venues(conn) == []
    # Back on the roster later, it starts a fresh baseline instead of reading as releases.
    back = tft_slot_history.record(conn, _snap(t1 + timedelta(minutes=20), {"gone": [("2026-12-02", "12:00")], "kept": [("2026-12-01", "12:00")]}))
    assert back == {"baseline": 1}


def test_existing_span_table_is_migrated_to_accept_removed():
    conn = sqlite3.connect(":memory:")
    conn.executescript(tft_slot_history.SCHEMA.replace("'gone', 'expired', 'removed'", "'gone', 'expired'"))
    conn.execute(
        "INSERT INTO tft_slot_spans(venue_id, meal, slot_date, slot_time, kind, opened_at) "
        "VALUES ('v', 'Lunch', '2026-12-01', '12:00', 'baseline', ?)", (_iso(START),),
    )
    tft_slot_history.init_db(conn)
    tft_slot_history.init_db(conn)  # idempotent
    assert _spans(conn) == [("2026-12-01", "12:00", "baseline", None)]
    conn.execute("UPDATE tft_slot_spans SET closed_at = 'x', close_reason = 'removed'")
    indexes = {row[1] for row in conn.execute("PRAGMA index_list('tft_slot_spans')")}
    assert {"idx_tft_spans_open", "idx_tft_spans_closed"} <= indexes


def _span_rows(conn):
    return conn.execute(
        "SELECT venue_id, meal, slot_date, slot_time, kind, close_reason FROM tft_slot_spans ORDER BY id"
    ).fetchall()


def test_snapshot_without_a_timezone_aware_time_is_ignored():
    conn = _conn()
    for generated_at in ("2026-11-02T01:00:00", "not a time", None):
        snapshot = _snap(START, {"v": [("2026-12-01", "12:00")]})
        snapshot["generated_at"] = generated_at
        assert tft_slot_history.record(conn, snapshot) == {}
    assert _span_rows(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM tft_slot_history_meta").fetchone()[0] == 0


def test_unusable_venues_do_not_stop_later_venues_in_the_snapshot():
    conn = _conn()
    slot = [("2026-12-01", "12:00")]
    snapshot = _snap(START, {"retained": slot, "stale": slot, "no-id": slot, "ok": slot})
    snapshot["venues"][0]["result"] = "retained"
    snapshot["venues"][1]["checked_at"] = _iso(START - timedelta(minutes=5))
    snapshot["venues"][2]["id"] = None
    assert tft_slot_history.record(conn, snapshot) == {"baseline": 1}
    assert [row[0] for row in _span_rows(conn)] == ["ok"]


def test_spans_keep_the_meal_and_ignore_slots_missing_a_date_or_time():
    conn = _conn()
    snapshot = _snap(START, {"v": [("2026-12-01", "12:00")]})
    snapshot["venues"][0]["meals"][0]["slots"] += [{"date": "2026-12-02", "time": ""}, {"date": "", "time": "13:00"}]
    snapshot["venues"][0]["meals"].append({"meal": "Dinner", "slots": [{"date": "2026-12-01", "time": "19:00"}]})
    tft_slot_history.record(conn, snapshot)
    assert _span_rows(conn) == [
        ("v", "Dinner", "2026-12-01", "19:00", "baseline", None),
        ("v", "Lunch", "2026-12-01", "12:00", "baseline", None),
    ]


def test_a_second_snapshot_at_the_same_time_is_not_applied():
    conn = _conn()
    tft_slot_history.record(conn, _snap(START, {"v": [("2026-12-01", "12:00")]}))
    assert tft_slot_history.record(conn, _snap(START, {"v": [("2026-12-02", "12:00")]})) == {}
    assert _span_rows(conn) == [("v", "Lunch", "2026-12-01", "12:00", "baseline", None)]


def test_closings_are_counted_and_a_slot_at_check_time_has_expired():
    conn = _conn()
    now = START.astimezone(tft_slot_history.SGT)
    at_check = (now.date().isoformat(), now.strftime("%H:%M"))
    earlier_today = (now.date().isoformat(), (now - timedelta(hours=2)).strftime("%H:%M"))
    later = [("2026-12-01", "12:00"), ("2026-12-02", "12:00")]
    tft_slot_history.record(conn, _snap(START - timedelta(minutes=5), {"v": [at_check, earlier_today, *later]}))
    assert tft_slot_history.record(conn, _snap(START, {"v": []})) == {"expired": 2, "gone": 2}


def test_a_slot_back_on_the_furthest_open_date_is_a_return():
    conn = _conn()
    days = [f"2026-12-{day:02d}" for day in range(1, 31)]
    tft_slot_history.record(conn, _snap(START, {"v": [(day, "12:00") for day in days]}))
    late = START + timedelta(minutes=5)
    counts = tft_slot_history.record(
        conn, _snap(late, {"v": [(day, "12:00") for day in days] + [(days[-1], "13:00"), (days[-2], "13:00")]})
    )
    assert counts == {"return": 2}


def test_the_bad_read_guard_needs_forty_slots_and_half_the_venue(caplog):
    conn = _conn()
    many = [("2026-12-01", f"{h:02d}:{m:02d}") for h in range(0, 24) for m in (0, 10, 20, 30, 40, 50)][:100]
    venues = {"half": many[:80], "share": many}
    tft_slot_history.record(conn, _snap(START, venues))
    later = START + timedelta(minutes=5)
    with caplog.at_level("WARNING", logger="app.tft_slot_history"):
        counts = tft_slot_history.record(conn, _snap(later, {"half": many[40:80], "share": many[40:]}))
    assert counts == {"skipped": 1, "gone": 40}
    assert caplog.messages[0] == (
        f"tft_slot_history skipped venue=half reason=suspect_drop since={_iso(later)} checks=1 vanished=40 open=80"
    )


def test_every_suspect_venue_is_counted_as_skipped():
    conn = _conn()
    many = [("2026-12-01", f"{h:02d}:{m:02d}") for h in range(10, 22) for m in (0, 15, 30, 45)]
    tft_slot_history.record(conn, _snap(START, {"a": many, "b": many}))
    assert tft_slot_history.record(conn, _snap(START + timedelta(minutes=5), {"a": [], "b": []})) == {"skipped": 2}


def _span(conn, kind, opened_after, closed_after_minutes=None, reason="gone", venue="v", opened_at=None):
    opened_at = opened_at or _iso(opened_after)
    closed_at = _iso(opened_after + timedelta(minutes=closed_after_minutes)) if closed_after_minutes is not None else None
    conn.execute(
        "INSERT INTO tft_slot_spans(venue_id, meal, slot_date, slot_time, kind, opened_at, opened_after, closed_at, close_reason) "
        "VALUES (?, 'Lunch', '2026-12-01', '12:00', ?, ?, ?, ?, ?)",
        (venue, kind, opened_at, _iso(opened_after), closed_at, reason if closed_at else None),
    )


def _start(conn, moment=START):
    conn.execute("INSERT INTO tft_slot_history_meta(key, value) VALUES ('started_at', ?)", (_iso(moment),))


def _lines_for(minutes: list[float], kind: str = "new") -> list[str]:
    conn = _conn()
    for value in minutes:
        _span(conn, kind, START, value)
    return tft_slot_history.summary(conn, START)["venues"]["v"]["lines"]


def test_duration_verdict_needs_five_closed_tables():
    assert _lines_for([7] * 4) == []
    assert _lines_for([7] * 5) == ["New tables have usually gone within 10 minutes."]


def test_duration_verdict_wording_at_each_boundary():
    assert _lines_for([60] * 5) == ["New tables have usually gone within 60 minutes."]
    assert _lines_for([61] * 5) == ["New tables have usually lasted under 2 hours."]
    assert _lines_for([121] * 5) == ["New tables have usually lasted under 3 hours."]
    assert _lines_for([24 * 60] * 5) == ["New tables have usually lasted under 24 hours."]
    assert _lines_for([1450] * 5) == ["New tables have usually stayed open for more than a day."]
    assert _lines_for([30] * 5, kind="return") == ["Tables that came back have usually gone within 30 minutes."]


def test_summary_counts_and_durations_only_from_tables_that_were_taken():
    conn = _conn()
    _start(conn, START - timedelta(days=4))
    _span(conn, "new", START, opened_at="not a time")
    _span(conn, "new", START, 12.4)
    _span(conn, "new", START, 3)
    _span(conn, "new", START, 90, reason="expired")
    _span(conn, "new", START)
    for _ in range(9):
        _span(conn, "return", START, 600)
    _span(conn, "return", START + timedelta(days=5))
    venue = tft_slot_history.summary(conn, START)["venues"]["v"]
    assert venue["new_tables"] == 4
    assert venue["returned_tables"] == 10
    assert venue["returns_per_day"] == 2.5
    assert venue["new_lasted_minutes"] == [3, 12]
    assert venue["return_buckets"] == {
        "weekday night": 0, "weekday morning": 9, "weekday afternoon": 0, "weekday evening": 0,
        "weekend night": 0, "weekend morning": 1, "weekend afternoon": 0, "weekend evening": 0,
    }
    assert venue["best_return_bucket"] == "weekday morning"
    assert venue["lines"] == [
        "Tables that came back have usually lasted under 10 hours.",
        "Cancellations have come back most often on weekday mornings.",
    ]


def test_returns_per_day_counts_at_least_one_day():
    conn = _conn()
    _start(conn, START - timedelta(hours=12))
    for _ in range(3):
        _span(conn, "return", START)
    assert tft_slot_history.summary(conn, START)["venues"]["v"]["returns_per_day"] == 3.0
    conn = _conn()
    _start(conn, START - timedelta(days=3))
    for _ in range(10):
        _span(conn, "return", START)
    assert tft_slot_history.summary(conn, START)["venues"]["v"]["returns_per_day"] == 3.3
    conn = _conn()
    _start(conn, START - timedelta(days=4))
    _span(conn, "return", START)
    assert tft_slot_history.summary(conn, START)["venues"]["v"]["returns_per_day"] == 0.2


def test_without_a_start_time_returns_are_per_single_day():
    conn = _conn()
    for _ in range(3):
        _span(conn, "return", START)
    summary = tft_slot_history.summary(conn, START + timedelta(days=10))
    assert summary["started_at"] is None
    assert summary["venues"]["v"]["returns_per_day"] == 3.0


def test_new_table_durations_are_capped_at_two_hundred():
    conn = _conn()
    for minute in range(201):
        _span(conn, "new", START, minute)
    assert len(tft_slot_history.summary(conn, START)["venues"]["v"]["new_lasted_minutes"]) == 200


def test_return_time_verdict_needs_ten_returns_and_a_clear_favourite():
    def best(hours_sgt: list[int]) -> str | None:
        conn = _conn()
        for hour in hours_sgt:
            _span(conn, "return", START + timedelta(hours=hour - 9))
        return tft_slot_history.summary(conn, START)["venues"]["v"]["best_return_bucket"]

    assert best([9] * 9) is None
    assert best([9] * 10) == "weekday morning"
    assert best([9] * 3 + [13] * 3 + [19] * 2 + [2] * 2) is None
    assert best([9] * 7 + [13] * 6 + [19] * 6 + [2]) == "weekday morning"
    assert best([6] * 10) == "weekday morning"


def test_saturday_returns_fall_in_weekend_buckets():
    conn = _conn()
    saturday_evening = START + timedelta(days=5, hours=10)  # Sat 7 pm SGT
    for _ in range(10):
        _span(conn, "return", saturday_evening)
    venue = tft_slot_history.summary(conn, START)["venues"]["v"]
    assert venue["best_return_bucket"] == "weekend evening"
    assert venue["return_buckets"]["weekend evening"] == 10


@pytest.fixture
def utc_host(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_slot_times_are_singapore_time_on_a_utc_host(utc_host):
    conn = _conn()
    # 08:30 SGT is 00:30 UTC, before this 01:00 UTC check, so the slot expired.
    tft_slot_history.record(conn, _snap(START - timedelta(minutes=45), {"v": [("2026-11-02", "08:30")]}))
    assert tft_slot_history.record(conn, _snap(START, {"v": []})) == {"expired": 1}


def test_return_dayparts_are_singapore_time_on_a_utc_host(utc_host):
    conn = _conn()
    for _ in range(10):
        _span(conn, "return", START)
    assert tft_slot_history.summary(conn, START)["venues"]["v"]["best_return_bucket"] == "weekday morning"


def _hold(conn, venues, moment):
    return tft_slot_history.record(conn, _snap(moment, venues))


def test_two_venues_confirming_together_are_both_counted_and_a_third_still_sees_new_tables(caplog):
    conn = _conn()
    kept = [("2026-12-01", "12:00")]
    _hold(conn, {"a": _many("2026-12-01"), "c": _many("2026-12-02"), "b": kept}, START)
    first = START + timedelta(minutes=10)
    moment = first
    while moment - first < tft_slot_history.SUSPECT_CONFIRM_AFTER:
        _hold(conn, {"a": _many("2026-12-20"), "c": _many("2026-12-21"), "b": kept}, moment)
        moment += timedelta(minutes=10)
    with caplog.at_level("WARNING", logger="app.tft_slot_history"):
        counts = _hold(conn, {"a": _many("2026-12-20"), "c": _many("2026-12-21"), "b": kept + [("2026-12-30", "12:00")]}, moment)
    assert counts == {"confirmed_drop": 2, "gone": 96, "baseline": 96, "new": 1}
    assert (
        f"tft_slot_history accepted venue=a reason=suspect_drop_confirmed since={_iso(first)} vanished=48"
        in caplog.messages
    )


def test_a_drop_confirms_only_after_more_than_three_checks():
    conn = _conn()
    _hold(conn, {"v": _many("2026-12-01")}, START)
    first = START + timedelta(minutes=10)
    for hours in (0, 3, 6):
        assert _hold(conn, {"v": _many("2026-12-20")}, first + timedelta(hours=hours)) == {"skipped": 1}
    assert _hold(conn, {"v": _many("2026-12-20")}, first + timedelta(hours=7))["confirmed_drop"] == 1


def test_a_slot_at_the_check_time_counts_as_expired_not_towards_a_bad_read():
    conn = _conn()
    at_check = START + timedelta(hours=1)  # 10:00 SGT
    future = [(f"2026-12-{day:02d}", "12:00") for day in range(1, 31)] + [("2026-12-31", f"{h}:00") for h in range(12, 21)]
    _hold(conn, {"v": [("2026-11-02", "10:00")] + future}, START)
    assert _hold(conn, {"v": []}, at_check) == {"expired": 1, "gone": 39}


def test_venues_removed_together_add_up_and_are_logged(caplog):
    conn = _conn()
    kept = [("2026-12-01", "12:00")]
    _hold(conn, {"g1": kept, "g2": kept + [("2026-12-02", "12:00")], "kept": kept}, START)
    with caplog.at_level("WARNING", logger="app.tft_slot_history"):
        assert _hold(conn, {"kept": kept}, START + timedelta(minutes=10)) == {"removed": 3}
    assert "tft_slot_history removed venue=g1 closed=1" in caplog.messages


def test_hold_status_is_ok_without_holds_and_fails_once_a_hold_reaches_the_escalation_age():
    since = [{"since": _iso(START)}]
    limit = START + tft_slot_history.SUSPECT_ESCALATE_AFTER
    assert tft_slot_history.hold_status([], _iso(START)) == "ok"
    assert tft_slot_history.hold_status(since, _iso(limit - timedelta(seconds=1))) == "degraded"
    assert tft_slot_history.hold_status(since, _iso(limit)) == "failing"


def test_hold_status_without_a_snapshot_time_uses_the_clock():
    now = datetime.now(timezone.utc)
    assert tft_slot_history.hold_status([{"since": _iso(now)}], None) == "degraded"
    assert tft_slot_history.hold_status([{"since": _iso(now - timedelta(days=1))}], None) == "failing"
