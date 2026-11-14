"""Long notifications: a counted headline, at most five items, then "+N more" with a link."""

from __future__ import annotations

import re
from datetime import date, timedelta

from app import owner_alerts, telegram_digest, telegram_reminders, tft_guide, tft_slots
from app.owner_alerts import OwnerAlertEvent, format_owner_digest
from tests.test_owner_alert_digest import EXPLORER, PROGRAMS, _program_event
from tests.test_telegram_buttons_digest import SGT_NINE_THIRTY, _span, conn  # noqa: F401
from tests.test_telegram_reminders import NOW, connection, create_reminder, fresh_snapshot
from tests.test_tft_slots import answer, snapshot


TELEGRAM_LIMIT = 4096
ITEM_PREFIXES = ("+ ", "− ", "~ ", "⚠ ", "• ")
SITE = "https://amex-explorer.kooexperience.com/#/table-for-two"


def _items(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(ITEM_PREFIXES)]


def _represented(text: str) -> int:
    """Events behind the item lines; merged lines end with (×N)."""
    return sum(
        int(m.group(1)) if (m := re.search(r"\(×(\d+)\)$", line)) else 1 for line in _items(text)
    )


def _more(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"^\+(\d+) more", text, flags=re.MULTILINE)]


# ---------------------------------------------------------------- owner digest


def test_owner_digest_shows_five_items_then_counts_the_rest_with_link():
    raw = [_program_event(i, PROGRAMS[0], "added", f"Sushi {i}") for i in range(30)]
    message = format_owner_digest([OwnerAlertEvent.model_validate(e) for e in raw], EXPLORER)

    assert message.splitlines()[0] == "Amex Explorer · 30 updates"
    assert len(_items(message)) == owner_alerts.DIGEST_ITEMS == 5
    assert "+25 more" in message
    assert f"Explorer: {EXPLORER}/#/japan" in message
    assert "…and" not in message


def test_owner_digest_caps_items_across_programs_and_counts_each_section():
    raw = [
        _program_event(len(PROGRAMS) * 10 + i, program, "added", f"{program[0]} venue {i}")
        for index, program in enumerate(PROGRAMS)
        for i in range(index * 10, index * 10 + 4)
    ]
    message = format_owner_digest([OwnerAlertEvent.model_validate(e) for e in raw], EXPLORER)

    assert message.splitlines()[0] == f"Amex Explorer · {len(raw)} updates"
    assert len(_items(message)) <= 5
    assert sum(_more(message)) == len(raw) - _represented(message)
    for name, _program_id, route in PROGRAMS:
        assert f"{name} · 4 added" in message
        assert f"Explorer: {EXPLORER}/{route}" in message


def test_owner_digest_stays_under_telegram_limit_for_a_huge_batch():
    raw = [_program_event(i, PROGRAMS[i % len(PROGRAMS)], "added", "S" * 500) for i in range(500)]
    message = format_owner_digest([OwnerAlertEvent.model_validate(e) for e in raw], EXPLORER)

    assert len(message) < 1500
    assert len(_items(message)) <= 5
    assert sum(_more(message)) + _represented(message) == 500


# ---------------------------------------------------------------- daily digest


def test_daily_digest_counts_dates_lists_five_and_links_the_rest(conn):  # noqa: F811
    start = date(2026, 11, 3)
    for offset in range(12):
        day = (start + timedelta(days=offset)).isoformat()
        _span(conn, "tft-colony", day, "12:45", "return", "2026-11-01T05:00:00Z")
    text = telegram_digest.compose(
        conn, ["tft-colony"], "2026-11-01T01:00:00Z", tft_guide.load_catalog(), SGT_NINE_THIRTY
    )

    assert text.splitlines()[0] == "Table for Two digest, Mon 2 Nov: 12 new dates open"
    assert len(_items(text)) == 5
    assert f"+7 more: {tft_guide.explorer_url(venue_id='tft-colony')}" in text
    assert text.endswith("/digest stop turns this off.")


def test_daily_digest_for_every_venue_links_the_full_list_and_fits_telegram(conn):  # noqa: F811
    catalog = tft_guide.load_catalog()
    venue_ids = [str(v["id"]) for v in catalog["venues"]]
    for venue_id in venue_ids:
        for offset in range(20):
            day = (date(2026, 11, 3) + timedelta(days=offset)).isoformat()
            _span(conn, venue_id, day, "12:45", "return", "2026-11-01T05:00:00Z")
    text = telegram_digest.compose(conn, ["*"], "2026-11-01T01:00:00Z", catalog, SGT_NINE_THIRTY)

    total = len(venue_ids) * 20
    assert text.splitlines()[0].endswith(f": {total} new dates open at {len(venue_ids)} venues")
    assert len(_items(text)) == 5
    assert f"+{total - 5} more: {SITE}\n" in text
    assert len(text) < TELEGRAM_LIMIT


# ---------------------------------------------------------------- reminder alert


def _wide_snapshot(days: int) -> dict:
    payload = fresh_snapshot()
    payload["venues"][0]["meals"][0]["slots"] = [
        {"date": (date(2026, 9, 1) + timedelta(days=offset)).isoformat(), "time": "19:00", "max_seats": 2}
        for offset in range(days)
    ]
    return payload


def test_reminder_alert_counts_dates_lists_five_and_links_the_rest(tmp_path):
    conn = connection(tmp_path / "reminders.db")
    try:
        create_reminder(conn, date_value="2026-08-30..2026-10-30")
        result = telegram_reminders.claim_notifications(conn, _wide_snapshot(12), NOW)
        text = result.notifications[0].text
    finally:
        conn.close()

    assert text.splitlines()[0] == "🔔 VUE has dinner open on 12 dates"
    assert len(_items(text)) == 5
    assert "+7 more dates" in text
    assert "#/table-for-two?venue=tft-vue&party=2&meal=dinner" in text
    assert len(text) < TELEGRAM_LIMIT


# ---------------------------------------------------------------- /slots reply


def test_slots_reply_lists_five_dates_then_counts_the_rest():
    payload = snapshot()
    vue = next(v for v in payload["venues"] if v["id"] == "tft-vue")
    vue["meals"][0]["slots"] = [
        {"date": f"2026-10-{day:02d}", "time": "19:00", "max_seats": 2} for day in range(1, 13)
    ]
    result = answer("which dates does VUE have in October?", payload)

    assert len(_items(result)) == tft_slots.MAX_RESULTS == 5
    assert "+7 more dates" in result
    assert result.splitlines()[-1].startswith(tft_guide.EXPLORER_PREFIX)
