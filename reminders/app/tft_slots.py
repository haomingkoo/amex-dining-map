"""Pure parsing, matching, and formatting for observed AMEXPlatSG slots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo


PROJECT = "AMEXPlatSG"
STALE_AFTER = timedelta(minutes=30)
MAX_RANGE_DAYS = 31
WEEKEND_RANGE_DAYS = 30
MAX_RESULTS = 8
PREFERRED_TIME_WINDOW_MINUTES = 60
SGT = ZoneInfo("Asia/Singapore")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"\d{2}:\d{2}")


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
    return (
        "Use /slots venue | party size | lunch or dinner | YYYY-MM-DD, "
        "YYYY-MM-DD..YYYY-MM-DD, or weekend | optional HH:MM.\n"
        "Examples:\n"
        "/slots VUE | 2 | dinner | 2026-10-29 | 19:00\n"
        "/slots any | 2 | dinner | weekend"
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


def answer(
    request: SlotRequest,
    catalog_venues: list[dict],
    snapshot: dict,
    now: datetime,
    official_source_line: str,
    explorer_line: str,
) -> str:
    if snapshot.get("source_project") != PROJECT:
        return "The slot source metadata could not be verified safely."
    names = {str(venue.get("id")): str(venue.get("name")) for venue in catalog_venues}
    wanted_ids = set(names)
    preferred = _minutes(request.preferred_time) if request.preferred_time else None
    matches = []
    stale = []
    unavailable = []
    fresh_coverage = 0
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
        fresh_coverage += 1
        fresh_checked.append(checked)
        if venue.get("status") != "live_available":
            continue
        for meal in venue.get("meals") or []:
            if (
                (
                    request.meal != "Lunch or Dinner"
                    and meal.get("meal") != request.meal
                )
                or meal.get("status") != "available"
            ):
                continue
            for slot in meal.get("slots") or []:
                slot_date = str(slot.get("date") or "")
                slot_time = str(slot.get("time") or "")
                slot_minutes = _minutes(slot_time)
                if (
                    not _in_range(slot_date, request)
                    or slot_minutes is None
                    or int(slot.get("max_seats") or 0) < request.party_size
                    or (
                        preferred is not None
                        and abs(slot_minutes - preferred)
                        > PREFERRED_TIME_WINDOW_MINUTES
                    )
                ):
                    continue
                matches.append(
                    {
                        "venue_id": venue_id,
                        "venue_name": names[venue_id],
                        "meal": meal.get("meal"),
                        "date": slot_date,
                        "time": slot_time,
                        "max_seats": int(slot.get("max_seats") or 0),
                        "checked_at": checked,
                        "distance": abs(slot_minutes - preferred)
                        if preferred is not None
                        else 0,
                    }
                )
    unavailable.extend(sorted(wanted_ids - seen_ids))
    matches.sort(
        key=lambda item: (
            item["distance"],
            item["date"],
            item["time"],
            item["venue_name"].casefold(),
        )
    )
    filters = (
        f"{request.party_size} pax, {request.meal}, "
        f"{'weekends in the next 30 days' if request.weekend_only else request.start_date.isoformat()}"
        f"{f' to {request.end_date.isoformat()}' if request.end_date != request.start_date and not request.weekend_only else ''}"
        f"{f', within 60 minutes of {request.preferred_time.strftime('%H:%M')} SGT' if request.preferred_time else ''}"
    )
    if matches:
        rows = []
        for item in matches[:MAX_RESULTS]:
            checked = item["checked_at"].astimezone(SGT).strftime("%d %b, %H:%M SGT")
            meal_label = (
                f"{str(item['meal']).lower()}, "
                if request.meal == "Lunch or Dinner"
                else ""
            )
            rows.append(
                f"• {item['venue_name']} — {item['date']} {item['time']}, "
                f"{meal_label}"
                f"up to {item['max_seats']} pax (checked {checked})"
            )
        body = "Observed matching AMEXPlatSG slots:\n" + "\n".join(rows)
        if len(matches) > MAX_RESULTS:
            body += f"\n• {len(matches) - MAX_RESULTS} more matching observations"
    elif fresh_coverage:
        latest = max(fresh_checked).astimezone(SGT).strftime(
            "%d %b %Y, %H:%M SGT"
        )
        body = (
            "No matching slot was observed in the fresh cached AMEXPlatSG checks. "
            "This does not mean the Amex Experiences App is sold out. "
            f"Latest matching venue check: {latest}."
        )
    elif stale:
        latest = max(checked for _venue_id, checked in stale)
        body = (
            "The matching venue snapshot is older than 30 minutes, so current "
            "availability cannot be determined. Last checked: "
            f"{latest.astimezone(SGT).strftime('%d %b %Y, %H:%M SGT')}."
        )
    else:
        body = "The matching venue selection has no verifiable AMEXPlatSG slot snapshot."
    if stale or unavailable:
        body += (
            f"\nCoverage note: {len(stale)} stale and {len(unavailable)} unverifiable "
            "matching venue snapshots were excluded."
        )
    return (
        f"Table for Two — observed slots\n\n{body}\n\nFilters: {filters}.\n"
        "Cached DiningCity AMEXPlatSG observations only. Booking and voucher redemption "
        "remain in the Amex Experiences App.\n"
        f"{official_source_line}\n{explorer_line}"
    )
