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


# --- Release patterns ------------------------------------------------------

# A check window wider than this cannot place a release within a time of day.
PRECISE_WINDOW_MINUTES = 90
MIN_PRECISE_FOR_TIME = 5
TIME_CLUSTER_HOURS = 2
TIME_CLUSTER_SHARE = 0.6
MIN_DATES_FOR_ROLLING = 6
ROLLING_LEAD_SHARE = 0.5
BATCH_MIN_DATES = 5


def _utc(value: Any):
    try:
        from scripts.timeutil import parse_utc
    except ImportError:  # running as `python3 scripts/<file>.py`
        from timeutil import parse_utc
    return parse_utc(value)


def _sgt(moment):
    from zoneinfo import ZoneInfo

    return moment.astimezone(ZoneInfo("Asia/Singapore"))


def _hour_label(hour: int) -> str:
    hour %= 24
    if hour == 0:
        return "midnight"
    if hour == 12:
        return "noon"
    return f"{hour % 12} {'am' if hour < 12 else 'pm'}"


def _time_cluster(midpoints: list[float]) -> dict | None:
    """The two-hour span of the day holding most first sightings, if one does."""
    if len(midpoints) < MIN_PRECISE_FOR_TIME:
        return None
    best_start, best_count = 0, -1
    for start in range(24):
        count = sum(1 for value in midpoints if (value - start) % 24 < TIME_CLUSTER_HOURS)
        if count > best_count:
            best_start, best_count = start, count
    share = best_count / len(midpoints)
    if share < TIME_CLUSTER_SHARE:
        return None
    return {
        "start_hour": best_start,
        "end_hour": (best_start + TIME_CLUSTER_HOURS) % 24,
        "share": round(share, 2),
        "label": (
            "around midnight"
            if best_start == 23
            else f"between {_hour_label(best_start)} and {_hour_label(best_start + TIME_CLUSTER_HOURS)}"
        ),
    }


def release_patterns(venue_id: str, observations: list[dict], as_of: date) -> dict:
    """When new dates first appeared for a venue, from the committed first-seen history."""
    new = [
        item
        for item in observations
        if item.get("venue_id") == venue_id
        and not item.get("baseline")
        and int(item.get("lead_days", -1)) >= 0
        and _utc(item.get("first_seen_at")) is not None
    ]
    hours = [0] * 24
    days_of_month = [0] * 31
    meals: dict[str, list[dict]] = defaultdict(list)
    precise = 0
    for item in new:
        seen = _utc(item["first_seen_at"])
        days_of_month[_sgt(seen).day - 1] += 1
        meals[str(item["meal"])].append(item)
        after = _utc(item.get("checked_after"))
        if after and 0 < (seen - after).total_seconds() <= PRECISE_WINDOW_MINUTES * 60:
            local = _sgt(after + (seen - after) / 2)
            hours[local.hour] += 1
            precise += 1
    meal_patterns = []
    for meal, items in sorted(meals.items(), key=lambda pair: {"Lunch": 0, "Afternoon Tea": 1, "Dinner": 2}.get(pair[0], 3)):
        leads = Counter(int(item["lead_days"]) for item in items)
        lead, lead_count = leads.most_common(1)[0]
        midpoints = []
        for item in items:
            seen, after = _utc(item["first_seen_at"]), _utc(item.get("checked_after"))
            if after and 0 < (seen - after).total_seconds() <= PRECISE_WINDOW_MINUTES * 60:
                local = _sgt(after + (seen - after) / 2)
                midpoints.append(local.hour + local.minute / 60)
        rolling = len(items) >= MIN_DATES_FOR_ROLLING and lead_count / len(items) >= ROLLING_LEAD_SHARE
        latest = max(_utc(item["first_seen_at"]) for item in items)
        meal_patterns.append({
            "meal": meal,
            "new_dates": len(items),
            "rolling_lead_days": lead if rolling else None,
            "lead_share": round(lead_count / len(items), 2),
            "precise_sightings": len(midpoints),
            "time_of_day": _time_cluster(midpoints),
            "last_new_date_at": latest.isoformat().replace("+00:00", "Z"),
            "quiet_days": (as_of - _sgt(latest).date()).days,
        })
    batches = Counter(item["first_seen_at"] for item in new)
    big = sorted(
        ({"at": at, "dates": count} for at, count in batches.items() if count >= BATCH_MIN_DATES),
        key=lambda item: item["at"],
    )[-3:]
    return {
        "new_dates": len(new),
        "precise_sightings": precise,
        "hour_counts": hours,
        "day_of_month_counts": days_of_month,
        "meals": meal_patterns,
        "batches": big,
    }


QUIET_DAYS_WORTH_SAYING = 7


def _day_month(moment) -> str:
    local = _sgt(moment)
    return f"{local.day} {local:%b}"


def release_lines(pattern: dict) -> list[str]:
    """Plain verdicts, each backed by the counts in the pattern."""
    lines = []
    for meal in pattern.get("meals") or []:
        name = meal["meal"].lower()
        lead = meal.get("rolling_lead_days")
        if lead is None:
            continue
        timing = meal.get("time_of_day")
        when = f", usually first seen {timing['label']}" if timing else ""
        if meal.get("quiet_days", 0) >= QUIET_DAYS_WORTH_SAYING:
            last = _day_month(_utc(meal["last_new_date_at"]))
            lines.append(
                f"Until {last}, new {name} dates opened one day at a time, {lead} days ahead{when}. None since."
            )
        else:
            lines.append(f"New {name} dates open one day at a time, {lead} days ahead{when}.")
    for batch in pattern.get("batches") or []:
        lines.append(f"{batch['dates']} new dates appeared at once on {_day_month(_utc(batch['at']))}.")
    return lines


def release_best_time(pattern: dict) -> str | None:
    """'lunch between 11 am and 1 pm (61 days ahead)' for meals that still release."""
    parts = []
    for meal in pattern.get("meals") or []:
        timing, lead = meal.get("time_of_day"), meal.get("rolling_lead_days")
        if timing and lead is not None and meal.get("quiet_days", 0) < QUIET_DAYS_WORTH_SAYING:
            parts.append(f"{meal['meal'].lower()} {timing['label']}, {lead} days ahead")
    return "; ".join(parts) or None


def furthest_open_dates(venue: dict) -> dict[str, str]:
    furthest: dict[str, str] = {}
    for meal in (venue.get("availability") or {}).get("meals") or []:
        for slot in meal.get("slots") or []:
            if slot.get("date"):
                name = str(meal.get("meal"))
                furthest[name] = max(str(slot["date"]), furthest.get(name, ""))
    return furthest


def venue_release(venue: dict, observations: list[dict], as_of: date) -> dict:
    pattern = release_patterns(str(venue["id"]), observations, as_of)
    return pattern | {
        "lines": release_lines(pattern),
        "best_time": release_best_time(pattern),
        "furthest_open_dates": furthest_open_dates(venue),
    }


def tracking_since(observations: list[dict]) -> str | None:
    """First date with a non-baseline sighting: when new-date tracking really began."""
    stamps = [
        str(item["first_seen_sgt"])[:10]
        for item in observations
        if item.get("first_seen_sgt") and not item.get("baseline")
    ]
    return min(stamps) if stamps else None


# --- Value verdict ---------------------------------------------------------

DEFAULT_PRICES = Path("data/reviews/tft-menu-prices.json")
# Singapore "++" adds a 10% service charge, then 9% GST on the total.
PLUS_PLUS = 1.1 * 1.09
HIGHER_THAN_USUAL = 1.15
LOWER_THAN_USUAL = 0.85
WELL_RATED = (4.5, 500)


def _price_text(extra: dict) -> str:
    basis = {"++": "++", "+": "+", "nett": " nett"}[extra["basis"]]
    if extra["per"] == "pair_at_10_percent_off":
        return f"S${extra['amount']}{basis} for two at 10% off"
    return f"S${extra['amount']}{basis}"


def _per_head_nett(extra: dict | None) -> float | None:
    """Comparable per-person price, or None when the basis is ambiguous."""
    if not extra or extra["basis"] == "+":
        return None
    amount = float(extra["amount"])
    if extra["per"] == "pair_at_10_percent_off":
        amount = amount / 0.9 / 2
    return amount * (PLUS_PLUS if extra["basis"] == "++" else 1.0)


def reviewed_prices(prices: dict, catalog_menus: dict[str, str]) -> dict[str, dict]:
    """Reviewed price entries whose menu hash still matches the current Platinum menu."""
    return {
        entry["venue_id"]: entry
        for entry in prices.get("menus") or []
        if catalog_menus.get(entry["venue_id"]) == entry["menu_sha256"]
    }


def program_typical(entries: dict[str, dict]) -> dict | None:
    per_head = sorted(
        value for entry in entries.values() if (value := _per_head_nett(entry.get("extra_diner"))) is not None
    )
    stated = Counter(
        _price_text(entry["extra_diner"])
        for entry in entries.values()
        if entry.get("extra_diner") and entry["extra_diner"]["per"] == "person"
    )
    if len(per_head) < 5 or not stated:
        return None
    return {"per_head_nett": round(statistics.median(per_head), 1), "label": stated.most_common(1)[0][0]}


def venue_verdict(venue: dict, entry: dict | None, typical: dict | None, rating: dict | None) -> dict:
    facts: list[str] = []
    extra = (entry or {}).get("extra_diner")
    tier = None
    if entry:
        facts.append(
            "One set is shared between the two of you."
            if entry["serving"] == "shared"
            else "Each of you gets a full set."
        )
    if extra:
        price = _price_text(extra)
        nett = _per_head_nett(extra)
        if extra["per"] == "pair_at_10_percent_off":
            facts.append(f"Extra diners pay {price}, so S${round(extra['amount'] / 0.9 / 2)} nett a head before the discount.")
        elif extra["basis"] == "++":
            facts.append(f"Extra diners pay {price} a head, about S${round(nett)} with service charge and GST.")
        else:
            facts.append(f"Extra diners pay {price} a head.")
        if typical:
            ratio = (nett or extra["amount"] * PLUS_PLUS) / typical["per_head_nett"]
            if nett is not None and ratio >= HIGHER_THAN_USUAL:
                tier = "higher"
            elif ratio <= LOWER_THAN_USUAL:
                tier = "lower"
            elif nett is not None:
                tier = "typical"
    elif entry:
        facts.append("Amex publishes no extra-diner price for this set; extra diners order à la carte.")
    google = (rating or {}) if isinstance(rating, dict) else {}
    stars, reviews = google.get("rating"), google.get("review_count")
    if isinstance(stars, (int, float)):
        count = f" from {reviews:,} reviews" if isinstance(reviews, int) else ""
        facts.append(f"Google rating {stars:g}{count}.")
    well_rated = (
        isinstance(stars, (int, float)) and isinstance(reviews, int)
        and stars >= WELL_RATED[0] and reviews >= WELL_RATED[1]
    )
    usual = typical["label"] if typical else None
    if extra and extra["per"] == "pair_at_10_percent_off":
        head = f"S${round(extra['amount'] / 0.9 / 2)} nett"
    elif extra:
        head = _price_text(extra)
    if tier == "higher":
        line = f"Good value: extra diners pay {head} a head for this set, more than the usual {usual}."
    elif tier == "lower" and extra["per"] == "pair_at_10_percent_off":
        line = (
            f"Lower value on paper: extra diners pay {head} a head before a 10% discount, "
            f"below the usual {usual}."
        )
    elif tier == "lower":
        line = f"Lower value on paper: extra diners pay {head} a head, below the usual {usual}."
    elif tier == "typical" and head == usual:
        line = f"Typical value: extra diners pay {head} a head, the usual Table for Two price."
    elif tier == "typical":
        line = f"Typical value: extra diners pay {head} a head, close to the usual {usual}."
    elif venue.get("category") == "buffet":
        line = (
            "Buffet. Amex publishes no price for it, so there is no value call"
            + (f", but it is well rated (Google {stars:g} from {reviews:,} reviews)." if well_rated else ".")
        )
    elif entry and entry["serving"] == "shared":
        line = "One set is shared between two, and Amex publishes no price to compare it with."
    else:
        line = "No published set price, so there is no value call" + (
            f". Well rated: Google {stars:g} from {reviews:,} reviews." if well_rated else "."
        )
    return {"line": line, "tier": tier, "facts": facts, "usual_price": usual}


def load_prices(path: Path = DEFAULT_PRICES) -> dict:
    return load_json(path)
