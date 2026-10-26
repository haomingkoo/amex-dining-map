"""Pure parsing, matching, and formatting for AMEXPlatSG slots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo


PROJECT = "AMEXPlatSG"
STALE_AFTER = timedelta(minutes=30)
# Releases land about 53-61 days ahead, so lookups must reach that far.
MAX_RANGE_DAYS = 62
WEEKEND_RANGE_DAYS = MAX_RANGE_DAYS
MAX_RESULTS = 8
PREFERRED_TIME_WINDOW_MINUTES = 60
SGT = ZoneInfo("Asia/Singapore")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"\d{2}:\d{2}")
MEAL_PLURALS = {"Lunch": "lunches", "Dinner": "dinners"}
SOURCE_NOTE = "Times come from DiningCity and can change; book in the Amex Experiences app."
UNAVAILABLE = "I cannot load Table for Two times right now. Please try again in a few minutes."


@dataclass(frozen=True)
class SlotRequest:
    venue_text: str
    party_size: int
    meal: str
    start_date: date
    end_date: date
    weekend_only: bool
    preferred_time: time | None


def usage() -> str:
    example = (datetime.now(SGT).date() + timedelta(days=14)).isoformat()  # always a future date
    return (
        "Use /slots venue, plus lunch or dinner, weekend, or a month if you like:\n"
        "/slots VUE dinner weekend\n"
        "/slots colony\n"
        "/slots any lunch in December\n"
        "Or the exact form: /slots venue | party | lunch or dinner | date or range | optional HH:MM\n"
        f"e.g. /slots VUE | 2 | dinner | {example} | 19:00"
    )


def parse_request(message: str, now: datetime) -> SlotRequest | str:
    lowered = message.casefold()
    if not (lowered == "/slots" or lowered.startswith("/slots ")):
        return usage()
    parts = [part.strip() for part in message[6:].strip().split("|")]
    if len(parts) not in {4, 5} or any(not part for part in parts[:4]):
        return usage()
    venue_text, party_text, meal_text, date_text = parts[:4]
    try:
        party_size = int(party_text)
    except ValueError:
        party_size = 0
    if not 1 <= party_size <= 10:
        return "Party size must be a whole number from 1 to 10.\n" + usage()
    meal = meal_text.casefold()
    if meal not in {"lunch", "dinner"}:
        return "Meal must be lunch or dinner.\n" + usage()
    today = now.astimezone(SGT).date()
    weekend_only = date_text.casefold() == "weekend"
    if weekend_only:
        start_date = today
        end_date = today + timedelta(days=WEEKEND_RANGE_DAYS - 1)
    else:
        values = date_text.split("..")
        if len(values) not in {1, 2}:
            return "Use one ISO date or a .. date range.\n" + usage()
        if any(DATE_RE.fullmatch(value) is None for value in values):
            return "Dates must use YYYY-MM-DD.\n" + usage()
        try:
            start_date = date.fromisoformat(values[0])
            end_date = date.fromisoformat(values[-1])
        except ValueError:
            return "Dates must use YYYY-MM-DD.\n" + usage()
    if start_date < today or end_date < start_date:
        return "Choose today or a future date, with the range in ascending order."
    if end_date > today + timedelta(days=365):
        return "The lookup range cannot extend more than 365 days from today."
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        return f"Date ranges are limited to {MAX_RANGE_DAYS} days per lookup."
    preferred_time = None
    if len(parts) == 5:
        if TIME_RE.fullmatch(parts[4]) is None:
            return "Preferred time must use HH:MM in Singapore time.\n" + usage()
        try:
            preferred_time = time.fromisoformat(parts[4])
        except ValueError:
            return "Preferred time must use HH:MM in Singapore time.\n" + usage()
        if preferred_time.second or preferred_time.microsecond:
            return "Preferred time must use HH:MM in Singapore time.\n" + usage()
    return SlotRequest(
        venue_text=venue_text,
        party_size=party_size,
        meal=meal.title(),
        start_date=start_date,
        end_date=end_date,
        weekend_only=weekend_only,
        preferred_time=preferred_time,
    )


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _minutes(value: Any) -> int | None:
    try:
        parsed = value if isinstance(value, time) else time.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _in_range(value: str, request: SlotRequest) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    if not request.start_date <= parsed <= request.end_date:
        return False
    return not request.weekend_only or parsed.weekday() >= 5


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b}"


def clock(value: str) -> str:
    """'18:00' -> '6:00pm'."""
    parsed = time.fromisoformat(value)
    return f"{parsed.hour % 12 or 12}:{parsed.minute:02d}{'am' if parsed.hour < 12 else 'pm'}"


def checked_label(moment: datetime) -> str:
    local = moment.astimezone(SGT)
    return f"{local.day} {local:%b}, {clock(local.strftime('%H:%M'))}"


def _span(dates: list[str]) -> str:
    first, last = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
    if first == last:
        return f"{first.day} {first:%b}"
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.day} {last:%b}"
    return f"{first.day} {first:%b}–{last.day} {last:%b}"


def _when(request: SlotRequest, today: date) -> str:
    if request.start_date == request.end_date:
        return f" on {_day(request.start_date)}"
    if (request.start_date, request.end_date) == (today, today + timedelta(days=MAX_RANGE_DAYS - 1)):
        return f" in the next {MAX_RANGE_DAYS} days"
    year = f" {request.end_date.year}" if request.end_date.year != today.year else ""
    return f" from {_day(request.start_date)} to {_day(request.end_date)}{year}"


def _search(request: SlotRequest, venue: str | None, today: date) -> str:
    """What was asked for, e.g. 'weekend dinners for 2 at Estate in the next 62 days'."""
    noun = MEAL_PLURALS.get(request.meal, "lunch or dinner")
    if request.start_date == request.end_date:
        noun = request.meal.lower()
    phrase = f"{'weekend ' if request.weekend_only else ''}{noun} for {request.party_size}"
    phrase += f" at {venue}" if venue else ""
    phrase += _when(request, today)
    if request.preferred_time:
        phrase += f", around {clock(request.preferred_time.strftime('%H:%M'))}"
    return phrase


Flag = Callable[[dict], "str | None"]


def _flagged(row: str, flag: Flag | None, item: dict) -> str:
    note = flag(item) if flag else None
    return f"{row}. {note}" if note else row


def _date_rows(
    matches: list[dict], request: SlotRequest, multi: bool, flag: Flag | None = None
) -> list[str]:
    """One line per venue, date and meal, so a range reads as dates rather than slots."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for item in matches:
        groups.setdefault((item["venue_name"], item["date"], str(item["meal"])), []).append(item)
    rows = []
    for (venue_name, slot_date, meal), items in list(groups.items())[:MAX_RESULTS]:
        times = sorted(item["time"] for item in items)
        span = clock(times[0]) if len(times) == 1 else f"{clock(times[0])}–{clock(times[-1])}"
        meal_label = f"{meal.lower()} " if request.meal == "Lunch or Dinner" else ""
        rows.append(_flagged(
            f"• {venue_name + ', ' if multi else ''}{_day(date.fromisoformat(slot_date))}: "
            f"{meal_label}{span} ({len(times)} time{'s' if len(times) > 1 else ''})",
            flag,
            items[0],
        ))
    if len(groups) > MAX_RESULTS:
        rows.append(f"• {len(groups) - MAX_RESULTS} more dates")
    return rows


def _slot_rows(
    matches: list[dict], request: SlotRequest, multi: bool, flag: Flag | None = None
) -> list[str]:
    rows = []
    for item in matches[:MAX_RESULTS]:
        meal_label = f" {str(item['meal']).lower()}" if request.meal == "Lunch or Dinner" else ""
        rows.append(_flagged(
            f"• {item['venue_name'] + ': ' if multi else ''}"
            f"{_day(date.fromisoformat(item['date']))} {clock(item['time'])}{meal_label} "
            f"(up to {item['max_seats']} people)",
            flag,
            item,
        ))
    if len(matches) > MAX_RESULTS:
        rows.append(f"• {len(matches) - MAX_RESULTS} more times")
    return rows


def _alternative(label: str, slots: list[dict], multi: bool) -> str:
    """'Weekday dinners are open on 11 days, 2–18 Nov. Earliest: Mon 2 Nov, 6:00pm.'"""
    first = min(slots, key=lambda item: (item["date"], item["time"]))
    earliest = f"{_day(date.fromisoformat(first['date']))}, {clock(first['time'])}"
    earliest += f" at {first['venue_name']}" if multi else ""
    days = sorted({item["date"] for item in slots})
    if len(days) == 1:
        return f"{label} are open on one day: {earliest.replace(', ', ', from ', 1)}."
    return f"{label} are open on {len(days)} days, {_span(days)}. Earliest: {earliest}."


def _no_match(
    request: SlotRequest, fresh: list[dict], venue: str | None, multi: bool, today: date
) -> tuple[str, SlotRequest]:
    """Say nothing matched, then the nearest open alternative and the request that finds it."""
    window_end = today + timedelta(days=MAX_RANGE_DAYS - 1)
    window = [item for item in fresh if today.isoformat() <= item["date"] <= window_end.isoformat()]
    lines = [f"No {_search(request, venue, today)}."]
    one_meal = request.meal in MEAL_PLURALS
    same_meal = [item for item in window if not one_meal or item["meal"] == request.meal]
    relaxable = (
        request.weekend_only
        or request.preferred_time is not None
        or (request.start_date, request.end_date) != (today, window_end)
    )
    noun = MEAL_PLURALS.get(request.meal, "tables")
    wider = replace(
        request, start_date=today, end_date=window_end, weekend_only=False, preferred_time=None
    )
    if relaxable and same_meal:
        weekdays = all(date.fromisoformat(item["date"]).weekday() < 5 for item in same_meal)
        label = f"Weekday {noun}" if request.weekend_only and weekdays else noun.capitalize()
        lines.append(_alternative(label, same_meal, multi))
        return "\n".join(lines), wider
    other = [
        item for item in window
        if one_meal and item["meal"] in MEAL_PLURALS and item["meal"] != request.meal
    ]
    if other:
        if relaxable:
            single = request.start_date == request.end_date and not request.weekend_only
            lines.append(f"No {request.meal.lower() if single else noun} on other days either.")
        lines.append(_alternative(MEAL_PLURALS[other[0]["meal"]].capitalize(), other, multi))
        return "\n".join(lines), replace(wider, meal=other[0]["meal"])
    where = f"at {venue}" if venue else "at any venue"
    lines.append(f"Nothing else is open for {request.party_size} {where} in the next {MAX_RANGE_DAYS} days.")
    return "\n".join(lines), request


def answer(
    request: SlotRequest,
    catalog_venues: list[dict],
    snapshot: dict,
    now: datetime,
    explorer_line: Callable[[SlotRequest], str],
    flag: Flag | None = None,
) -> str:
    """explorer_line(request) gives the link line for the request the reply describes.

    flag(item) may return a short warning for a slot, e.g. a blackout day.
    """
    if snapshot.get("source_project") != PROJECT:
        return UNAVAILABLE
    names = {str(venue.get("id")): str(venue.get("name")) for venue in catalog_venues}
    wanted_ids = set(names)
    multi = len(names) > 1
    venue_label = None if multi else next(iter(names.values()), None)
    preferred = _minutes(request.preferred_time) if request.preferred_time else None
    fresh = []
    stale = []
    unavailable = []
    fresh_checked = []
    seen_ids = set()
    for venue in snapshot.get("venues") or []:
        venue_id = str(venue.get("id") or "")
        if venue_id not in wanted_ids:
            continue
        seen_ids.add(venue_id)
        checked = _timestamp(venue.get("checked_at"))
        if (
            venue.get("project") != PROJECT
            or checked is None
            or checked > now + timedelta(minutes=5)
        ):
            unavailable.append(venue_id)
            continue
        if now - checked > STALE_AFTER:
            stale.append((venue_id, checked))
            continue
        if venue.get("status") not in {"live_available", "live_no_seats"}:
            unavailable.append(venue_id)
            continue
        fresh_checked.append(checked)
        if venue.get("status") != "live_available":
            continue
        for meal in venue.get("meals") or []:
            if meal.get("status") != "available":
                continue
            for slot in meal.get("slots") or []:
                slot_date = str(slot.get("date") or "")
                slot_time = str(slot.get("time") or "")
                slot_minutes = _minutes(slot_time)
                try:
                    date.fromisoformat(slot_date)
                except ValueError:
                    continue
                if slot_minutes is None or int(slot.get("max_seats") or 0) < request.party_size:
                    continue
                fresh.append(
                    {
                        "venue_id": venue_id,
                        "venue_name": names[venue_id],
                        "meal": meal.get("meal"),
                        "date": slot_date,
                        "time": slot_time,
                        "minutes": slot_minutes,
                        "max_seats": int(slot.get("max_seats") or 0),
                    }
                )
    matches = [
        {**item, "distance": abs(item["minutes"] - preferred) if preferred is not None else 0}
        for item in fresh
        if (request.meal == "Lunch or Dinner" or item["meal"] == request.meal)
        and _in_range(item["date"], request)
        and (preferred is None or abs(item["minutes"] - preferred) <= PREFERRED_TIME_WINDOW_MINUTES)
    ]
    unavailable.extend(sorted(wanted_ids - seen_ids))
    matches.sort(
        key=lambda item: (
            item["distance"],
            item["date"],
            item["time"],
            item["venue_name"].casefold(),
        )
    )
    today = now.astimezone(SGT).date()
    linked = request
    who = venue_label or "these venues"
    if matches:
        rows = (
            _date_rows(matches, request, multi, flag)
            if request.end_date != request.start_date and preferred is None
            else _slot_rows(matches, request, multi, flag)
        )
        body = f"Open tables, {_search(request, venue_label, today)}:\n" + "\n".join(rows)
    elif fresh_checked:
        body, linked = _no_match(request, fresh, venue_label, multi, today)
    elif stale:
        latest = max(checked for _venue_id, checked in stale)
        body = (
            f"I cannot see current times for {who} right now. The last check was "
            f"{checked_label(latest)}, which is too old to rely on."
        )
    else:
        body = f"I do not have current times for {who} right now."
    left_out = len(stale) + len(unavailable)
    if fresh_checked and left_out:
        body += (
            f"\n{left_out} venue{'s were' if left_out != 1 else ' was'} left out "
            "because I do not have a recent check."
        )
    note = (
        f"Last checked {checked_label(min(fresh_checked))}. {SOURCE_NOTE}"
        if fresh_checked
        else SOURCE_NOTE
    )
    return f"{body}\n\n{note}\n{explorer_line(linked)}"
