#!/usr/bin/env python3
"""Per-venue Table for Two facts derived from reviewed terms and observed slots."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.jsonio import load_json
except ImportError:  # running as `python3 scripts/<file>.py`
    from jsonio import load_json


DEFAULT_RULES = Path("data/reviews/tft-blackout-rules.json")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# A meal needs this many distinct dates before its weekdays say anything.
MIN_DATES_FOR_DAYS = 6
# A weekday seen on fewer dates than this share of the meal's typical weekday is "rare".
RARE_DAY_SHARE = 0.25
BLACKOUT_LOOKAHEAD_DAYS = 400

DAY_LABELS = {
    "valentines_day": "Valentine's Day",
    "easter_weekend": "Easter weekend",
    "easter_sunday": "Easter Sunday",
    "mothers_day": "Mother's Day",
    "mothers_day_and_eve": "Mother's Day and its eve",
    "fathers_day": "Father's Day",
    "fathers_day_and_eve": "Father's Day and its eve",
    "thanksgiving": "Thanksgiving",
    "lunar_new_year_days_1_to_4": "Days 1 to 4 of Lunar New Year",
    "secretaries_day": "Secretaries' Week (22 Apr)",
    "f1_weekend": "F1 weekend",
    "formula_1": "Formula 1",
}
EVE_NAMES = {"Christmas Day": "Christmas Eve", "New Year's Day": "New Year's Eve"}
# Named in the terms without dates we can pin down.
UNDATED_DAYS = {"easter_weekend", "f1_weekend", "formula_1"}


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def _merchant_dates(key: str, year: int, holidays: list[dict]) -> list[tuple[date, str]]:
    label = DAY_LABELS[key]
    if key == "valentines_day":
        return [(date(year, 2, 14), label)]
    if key == "easter_sunday":
        return [(_easter(year), label)]
    if key in {"mothers_day", "mothers_day_and_eve"}:
        day = _nth_weekday(year, 5, 6, 2)
        pairs = [(day, "Mother's Day")]
        return pairs + ([(day - timedelta(days=1), "Eve of Mother's Day")] if key.endswith("_eve") else [])
    if key in {"fathers_day", "fathers_day_and_eve"}:
        day = _nth_weekday(year, 6, 6, 3)
        pairs = [(day, "Father's Day")]
        return pairs + ([(day - timedelta(days=1), "Eve of Father's Day")] if key.endswith("_eve") else [])
    if key == "thanksgiving":
        return [(_nth_weekday(year, 11, 3, 4), label)]
    if key == "secretaries_day":
        return [(date(year, 4, 22), "Secretaries' Week")]
    if key == "lunar_new_year_days_1_to_4":
        firsts = sorted(
            date.fromisoformat(item["date"])
            for item in holidays
            if item["name"] == "Chinese New Year" and item["date"].startswith(str(year))
        )
        if not firsts:
            return []
        return [(firsts[0] + timedelta(days=n), f"Lunar New Year day {n + 1}") for n in range(4)]
    return []


def blackout_dates(venue_id: str, rules: dict, today: date) -> list[dict]:
    """Dated blackouts from today onward: program-wide holidays and eves, then merchant days."""
    end = today + timedelta(days=BLACKOUT_LOOKAHEAD_DAYS)
    holidays = rules.get("public_holidays") or []
    found: dict[date, str] = {}
    for item in holidays:
        day = date.fromisoformat(item["date"])
        found.setdefault(day, item["name"])
        eve = day - timedelta(days=1)
        if eve not in found:
            name = item["name"].removesuffix(" holiday")
            found[eve] = EVE_NAMES.get(name, f"Eve of {name}")
    for merchant in rules.get("merchants") or []:
        if venue_id not in merchant.get("venue_ids", []):
            continue
        for key in merchant.get("days") or []:
            for year in range(today.year, end.year + 1):
                for day, label in _merchant_dates(key, year, holidays):
                    found.setdefault(day, label)
    return [
        {"date": day.isoformat(), "reason": reason}
        for day, reason in sorted(found.items())
        if today <= day <= end
    ]


def merchant_blackout_labels(venue_id: str, rules: dict) -> list[str]:
    labels = []
    for merchant in rules.get("merchants") or []:
        if venue_id in merchant.get("venue_ids", []):
            for key in merchant.get("days") or []:
                text = DAY_LABELS[key]
                labels.append(f"{text} (dates not given)" if key in UNDATED_DAYS else text)
    return labels


def days_label(days: Iterable[str]) -> str:
    """{'Sun','Mon','Tue','Wed','Thu'} -> 'Sun–Thu'; gaps give comma-separated runs."""
    wanted = {WEEKDAYS.index(day) for day in days}
    if not wanted:
        return ""
    if len(wanted) == 7:
        return "Every day"
    start = next(i for i in range(7) if i in wanted and (i - 1) % 7 not in wanted)
    runs, current = [], []
    for offset in range(7):
        index = (start + offset) % 7
        if index in wanted:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    parts = []
    for run in runs:
        if len(run) == 1:
            parts.append(WEEKDAYS[run[0]])
        elif len(run) == 2:
            parts.append(f"{WEEKDAYS[run[0]]}, {WEEKDAYS[run[1]]}")
        else:
            parts.append(f"{WEEKDAYS[run[0]]}–{WEEKDAYS[run[-1]]}")
    return ", ".join(parts)


def observed_meals(
    venue: dict, observations: list[dict], meal_order: dict[str, int] | None = None
) -> list[dict]:
    """Weekdays each meal has been offered on in the booking system, with today's seating times."""
    dates: dict[str, set[str]] = defaultdict(set)
    for item in observations:
        if item.get("venue_id") == venue.get("id") and item.get("meal") and item.get("slot_date"):
            dates[str(item["meal"])].add(str(item["slot_date"]))
    times: dict[str, list[str]] = defaultdict(list)
    for meal in (venue.get("availability") or {}).get("meals") or []:
        for slot in meal.get("slots") or []:
            if slot.get("time"):
                times[str(meal.get("meal"))].append(str(slot["time"]))
    order = meal_order or {"Lunch": 0, "Afternoon Tea": 1, "Dinner": 2, "All-day Dining": 3}
    meals = []
    for meal, seen in sorted(dates.items(), key=lambda item: order.get(item[0], 9)):
        per_day = Counter(WEEKDAYS[date.fromisoformat(value).weekday()] for value in seen)
        entry: dict[str, Any] = {"meal": meal, "dates_seen": len(seen)}
        if len(seen) >= MIN_DATES_FOR_DAYS:
            typical = statistics.median(count for count in per_day.values())
            regular = [day for day in WEEKDAYS if per_day[day] >= max(2, typical * RARE_DAY_SHARE)]
            rare = [day for day in WEEKDAYS if 0 < per_day[day] and day not in regular]
            entry |= {
                "days": regular,
                "days_label": days_label(regular),
                "rare_days": rare,
                "never_days": [day for day in WEEKDAYS if per_day[day] == 0],
            }
        if times.get(meal):
            entry["first_time"], entry["last_time"] = min(times[meal]), max(times[meal])
        meals.append(entry)
    return meals


def venue_eligibility(
    venue: dict, observations: list[dict], rules: dict, terms_sha256: str | None, today: date
) -> dict:
    venue_id = str(venue["id"])
    current = bool(terms_sha256) and terms_sha256 == rules.get("terms_sha256")
    result: dict[str, Any] = {
        "published_days": None,
        "terms_current": current,
        "observed_meals": observed_meals(venue, observations),
    }
    if current:
        result |= {
            "merchant_blackouts": merchant_blackout_labels(venue_id, rules),
            "blackout_dates": blackout_dates(venue_id, rules, today),
        }
    return result


def observed_since(observations: list[dict]) -> str | None:
    stamps = [str(item["first_seen_sgt"])[:10] for item in observations if item.get("first_seen_sgt")]
    return min(stamps) if stamps else None


def load_rules(path: Path = DEFAULT_RULES) -> dict:
    return load_json(path)
