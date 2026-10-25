from __future__ import annotations

from datetime import date

import pytest

from app.telegram_reminders import _parse_dates

SUNDAY = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("november?", ("2026-11-01", "2026-11-30", [])),
        ("Nov", ("2026-11-01", "2026-11-30", [])),
        ("october", ("2026-10-25", "2026-10-31", [])),
        ("2026-11-01 to 2026-11-30", ("2026-11-01", "2026-11-30", [])),
        ("1 Nov to 15 Nov", ("2026-11-01", "2026-11-15", [])),
        ("1 to 15 nov", ("2026-11-01", "2026-11-15", [])),
        ("nov 3 - nov 9", ("2026-11-03", "2026-11-09", [])),
        ("14 Nov", ("2026-11-14", "2026-11-14", [])),
        ("14/11", ("2026-11-14", "2026-11-14", [])),
        ("14 nov, 21 nov", ("2026-11-14", "2026-11-21", ["2026-11-14", "2026-11-21"])),
        ("14 nov and 21 nov", ("2026-11-14", "2026-11-21", ["2026-11-14", "2026-11-21"])),
        ("tomorrow", ("2026-10-26", "2026-10-26", [])),
        ("2026-11-01..2026-11-05", ("2026-11-01", "2026-11-05", [])),
        ("2026-11-01 2026-11-30", ("2026-11-01", "2026-11-30", [])),
        ("Next 30 days", ("2026-10-25", "2026-11-23", [])),
        ("next week", ("2026-10-25", "2026-10-31", [])),
        ("next 2 weeks", ("2026-10-25", "2026-11-07", [])),
        ("anytime", ("2026-10-25", "2026-11-23", [])),
    ],
)
def test_parse_dates_accepts_natural_input(text: str, expected: tuple) -> None:
    result = _parse_dates(text, SUNDAY)

    assert result == expected


def test_weekends_in_a_month_lists_saturdays_and_sundays() -> None:
    start, end, dates = _parse_dates("weekends in november", SUNDAY)

    assert dates == ["2026-11-01", "2026-11-07", "2026-11-08", "2026-11-14", "2026-11-15",
                     "2026-11-21", "2026-11-22", "2026-11-28", "2026-11-29"]


def test_this_weekend_on_a_sunday_is_today_only() -> None:
    assert _parse_dates("this weekend", SUNDAY) == ("2026-10-25", "2026-10-25", [])


def test_next_weekend_on_a_sunday_is_the_following_saturday_and_sunday() -> None:
    assert _parse_dates("next weekend", SUNDAY)[2] == ["2026-10-31", "2026-11-01"]


@pytest.mark.parametrize("text", ["2025-11-01", "1 jan 2020", "1 nov to 30 dec", "whenever", "31/02", "", "next 60 days"])
def test_parse_dates_still_rejects_past_too_long_or_unreadable(text: str) -> None:
    assert _parse_dates(text, SUNDAY) is None
