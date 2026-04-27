#!/usr/bin/env python3
"""Send Table for Two alert emails for saved signup preferences.

The script is designed for GitHub Actions: refresh data/table-for-two.json,
load subscriptions from a private CSV endpoint or local JSON file, send SMTP
emails for newly matched slots, then store only salted sent-key hashes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_DATA_PATH = "data/table-for-two.json"
DEFAULT_SENT_LOG_PATH = "data/table-for-two-alert-sent.json"
DEFAULT_SITE_URL = "https://amex-explorer.kooexperience.com/#/table-for-two"
MAX_MATCHES_PER_EMAIL = 24
ALERT_TIMEZONE = "Asia/Singapore"
CSV_FETCH_ATTEMPTS = 3
CSV_FETCH_TIMEOUT_SECONDS = 60
CSV_FETCH_BACKOFF_SECONDS = 5


@dataclass(frozen=True)
class Subscription:
    email: str
    name: str
    party_size: int
    dates: tuple[str, ...]
    date_start: str
    date_end: str
    sessions: tuple[str, ...]
    venues: tuple[str, ...]
    unsubscribe_url: str
    source_label: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_singapore() -> date:
    return datetime.now(ZoneInfo(ALERT_TIMEZONE)).date()


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def normalize_venue_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_text(url: str) -> str:
    last_error: BaseException | None = None
    for attempt in range(1, CSV_FETCH_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "amex-dining-map table-for-two alerts"},
        )
        try:
            with urllib.request.urlopen(request, timeout=CSV_FETCH_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8-sig")
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt >= CSV_FETCH_ATTEMPTS:
                break
            time.sleep(CSV_FETCH_BACKOFF_SECONDS * attempt)
    raise RuntimeError("Could not fetch subscriptions CSV after retries") from last_error


def split_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(split_values(item))
        return parts
    raw = str(value or "").strip()
    if not raw:
        return []
    return [
        part.strip()
        for part in re.split(r"[\n,;|]+", raw)
        if part.strip()
    ]


def parse_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def parse_dates(value: Any) -> tuple[str, ...]:
    return tuple(sorted({date for date in (parse_date(part) for part in split_values(value)) if date}))


def parse_party_size(value: Any, default: int = 2) -> int:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return default
    return max(1, int(match.group(0)))


def parse_sessions(value: Any) -> tuple[str, ...]:
    sessions = []
    for part in split_values(value):
        normalized = normalize_text(part)
        if normalized in {"all", "any", "any session", "either"}:
            continue
        if "lunch" in normalized:
            sessions.append("lunch")
        elif "afternoon" in normalized and "tea" in normalized:
            sessions.append("afternoon tea")
        elif "dinner" in normalized:
            sessions.append("dinner")
    return tuple(sorted(set(sessions)))


def parse_enabled(value: Any) -> bool:
    raw = normalize_text(value)
    return raw not in {"false", "no", "n", "0", "off", "disabled", "paused"}


def value_from_row(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    by_normalized_key = {normalize_header(key): value for key, value in row.items()}
    for alias in aliases:
        value = by_normalized_key.get(normalize_header(alias))
        if value not in (None, ""):
            return value
    return ""


def build_venue_aliases(venues: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for record in venues:
        venue_id = record.get("id")
        if not venue_id:
            continue
        for value in (
            venue_id,
            record.get("name"),
            record.get("app_name"),
            record.get("dining_city_name"),
        ):
            key = normalize_venue_key(value)
            if key:
                aliases[key] = venue_id
    return aliases


def parse_venues(value: Any, venue_aliases: dict[str, str]) -> tuple[str, ...]:
    venue_ids = []
    for part in split_values(value):
        normalized = normalize_text(part)
        if normalized in {"all", "any", "any venue", "all venues"}:
            continue
        venue_id = venue_aliases.get(normalize_venue_key(part))
        if venue_id:
            venue_ids.append(venue_id)
    return tuple(sorted(set(venue_ids)))


def subscription_from_row(row: dict[str, Any], venue_aliases: dict[str, str], source_label: str) -> Subscription | None:
    enabled = value_from_row(row, ("enabled", "active", "send alerts"))
    if enabled and not parse_enabled(enabled):
        return None

    email = value_from_row(row, ("email", "email address", "your email"))
    if "@" not in email:
        return None

    name = value_from_row(row, ("name", "first name", "your name"))
    dates = parse_dates(value_from_row(row, ("dates", "date", "exact dates", "desired dates", "free dates", "alert dates")))
    date_start = parse_date(value_from_row(row, ("date start", "start date", "from date")))
    date_end = parse_date(value_from_row(row, ("date end", "end date", "to date")))
    return Subscription(
        email=email.strip(),
        name=name.strip(),
        party_size=parse_party_size(value_from_row(row, ("party size", "pax", "seats", "people")), default=2),
        dates=dates,
        date_start=date_start,
        date_end=date_end,
        sessions=parse_sessions(value_from_row(row, ("session", "sessions", "meal", "meals"))),
        venues=parse_venues(value_from_row(row, ("venues", "venue", "restaurants", "restaurant")), venue_aliases),
        unsubscribe_url=str(
            value_from_row(
                row,
                (
                    "unsubscribe url",
                    "unsubscribe link",
                    "unsubscribe",
                    "manage url",
                    "manage link",
                    "preferences url",
                    "preferences link",
                ),
            )
            or ""
        ).strip(),
        source_label=source_label,
    )


def load_csv_subscriptions(raw_csv: str, venue_aliases: dict[str, str], source_label: str) -> list[Subscription]:
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = list(reader)
    return [
        subscription
        for index, row in enumerate(rows, start=1)
        if (subscription := subscription_from_row(row, venue_aliases, f"{source_label} row {index}"))
    ]


def load_json_subscriptions(path: Path, venue_aliases: dict[str, str]) -> list[Subscription]:
    if not path.exists():
        return []
    payload = load_json(path)
    rows = payload.get("subscriptions", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a list or a subscriptions list")
    return [
        subscription
        for index, row in enumerate(rows, start=1)
        if isinstance(row, dict)
        if (subscription := subscription_from_row(row, venue_aliases, f"{path} row {index}"))
    ]


def load_sent_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"updated_at": "", "sent_keys": {}}
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {"updated_at": "", "sent_keys": {}}
    sent_keys = payload.get("sent_keys") or payload.get("sent") or {}
    return {"updated_at": payload.get("updated_at", ""), "sent_keys": dict(sent_keys)}


def salted_hash(parts: list[Any], salt: str) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{salt}:{raw}".encode("utf-8")).hexdigest()


def append_query_params(url: str, params: dict[str, str]) -> str:
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value)
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(query),
            parts.fragment,
        )
    )


def unsubscribe_url_for(subscription: Subscription, salt: str, base_url: str) -> str:
    if subscription.unsubscribe_url:
        return subscription.unsubscribe_url
    if not salt or not base_url:
        return ""
    token = salted_hash(["unsubscribe", subscription.email.casefold()], salt)
    return append_query_params(base_url, {"email": subscription.email, "token": token})


def slot_max_seats(slot: dict[str, Any], fallback: int = 2) -> int:
    values = slot.get("available_seats")
    listed = 0
    if isinstance(values, list):
        numeric_values = [int(value) for value in values if str(value).isdigit()]
        listed = max(numeric_values) if numeric_values else 0
    max_seats = int(slot.get("max_seats") or slot.get("total_available_seats") or fallback or 0)
    return max(listed, max_seats)


def venue_slots(record: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for meal in record.get("availability", {}).get("meals") or []:
        if meal.get("status") != "available":
            continue
        meal_name = meal.get("meal") or "Session"
        fallback_max = int(meal.get("max_seats") or meal.get("seats") or 2)
        if isinstance(meal.get("slots"), list) and meal["slots"]:
            for slot in meal["slots"]:
                if not isinstance(slot, dict):
                    continue
                slots.append(
                    {
                        "venue_id": record.get("id"),
                        "venue_name": record.get("app_name") or record.get("name"),
                        "date": slot.get("date") or meal.get("date") or "",
                        "time": slot.get("time") or "",
                        "meal": slot.get("meal") or meal_name,
                        "max_seats": slot_max_seats(slot, fallback=fallback_max),
                        "checked_at": record.get("availability", {}).get("checked_at")
                        or record.get("availability", {}).get("captured_at")
                        or "",
                    }
                )
            continue
        dates = [meal.get("date"), *(meal.get("dates") or [])]
        dates = [date for date in dates if date]
        times = meal.get("times") or []
        for date in dates or [""]:
            for time in times:
                slots.append(
                    {
                        "venue_id": record.get("id"),
                        "venue_name": record.get("app_name") or record.get("name"),
                        "date": date,
                        "time": time,
                        "meal": meal_name,
                        "max_seats": fallback_max,
                        "checked_at": record.get("availability", {}).get("checked_at")
                        or record.get("availability", {}).get("captured_at")
                        or "",
                    }
                )
    return slots


def date_matches(subscription: Subscription, slot_date: str) -> bool:
    if subscription.dates and slot_date not in subscription.dates:
        return False
    if subscription.date_start and slot_date and slot_date < subscription.date_start:
        return False
    if subscription.date_end and slot_date and slot_date > subscription.date_end:
        return False
    return True


def slot_matches(subscription: Subscription, slot: dict[str, Any]) -> bool:
    if slot_max_seats(slot) < subscription.party_size:
        return False
    if subscription.venues and slot.get("venue_id") not in subscription.venues:
        return False
    if subscription.sessions and normalize_text(slot.get("meal")) not in subscription.sessions:
        return False
    return date_matches(subscription, str(slot.get("date") or ""))


def matching_slots(subscription: Subscription, venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = []
    for record in venues:
        if record.get("availability", {}).get("status") != "live_available":
            continue
        for slot in venue_slots(record):
            if slot_matches(subscription, slot):
                matches.append(slot)
    return sorted(matches, key=lambda item: (item.get("date") or "", item.get("time") or "", item.get("venue_name") or ""))


def iso_date(value: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def subscription_expiry_date(subscription: Subscription) -> date | None:
    exact_dates = [parsed for value in subscription.dates if (parsed := iso_date(value))]
    if exact_dates:
        start = iso_date(subscription.date_start)
        end = iso_date(subscription.date_end)
        filtered_dates = [
            value
            for value in exact_dates
            if (not start or value >= start) and (not end or value <= end)
        ]
        return max(filtered_dates or exact_dates)
    return iso_date(subscription.date_end)


def subscription_is_expired(subscription: Subscription, today: date) -> bool:
    expiry = subscription_expiry_date(subscription)
    return bool(expiry and expiry < today)


def subscription_scope_lines(subscription: Subscription) -> list[str]:
    lines = [f"Party size: {subscription.party_size}"]
    if subscription.dates:
        lines.append(f"Dates: {', '.join(subscription.dates)}")
    elif subscription.date_start or subscription.date_end:
        start = subscription.date_start or "any start"
        end = subscription.date_end or "any end"
        lines.append(f"Date range: {start} to {end}")
    if subscription.sessions:
        lines.append(f"Sessions: {', '.join(session.title() for session in subscription.sessions)}")
    if subscription.venues:
        lines.append(f"Venues: {len(subscription.venues)} selected")
    return lines


def subscription_state_key(subscription: Subscription, kind: str, salt: str) -> str:
    return salted_hash(
        [
            kind,
            subscription.email.casefold(),
            subscription.party_size,
            subscription.dates,
            subscription.date_start,
            subscription.date_end,
            subscription.sessions,
            subscription.venues,
        ],
        salt,
    )


def slot_key(subscription: Subscription, slot: dict[str, Any], salt: str) -> str:
    return salted_hash(
        [
            subscription.email.casefold(),
            subscription.party_size,
            slot.get("venue_id"),
            slot.get("date"),
            slot.get("meal"),
            slot.get("time"),
            slot.get("max_seats"),
        ],
        salt,
    )


def format_slot(slot: dict[str, Any]) -> str:
    date = slot.get("date") or "date not specified"
    meal = slot.get("meal") or "Session"
    time = slot.get("time") or "time not specified"
    max_seats = slot.get("max_seats") or "?"
    return f"{slot.get('venue_name')} - {date} {meal} {time} (up to {max_seats} pax)"


def add_common_headers(
    message: EmailMessage,
    sender: str,
    recipient: str,
    reply_to: str = "",
    unsubscribe_url: str = "",
    one_click_unsubscribe: bool = False,
) -> None:
    message["From"] = sender
    message["To"] = recipient
    if reply_to:
        message["Reply-To"] = reply_to
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        if one_click_unsubscribe:
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"


def build_email(
    subscription: Subscription,
    slots: list[dict[str, Any]],
    sender: str,
    site_url: str,
    reply_to: str = "",
    unsubscribe_url: str = "",
    one_click_unsubscribe: bool = False,
) -> EmailMessage:
    subject = f"Table for Two alert: {len(slots)} matching slot{'s' if len(slots) != 1 else ''}"
    greeting = f"Hi {subscription.name}," if subscription.name else "Hi,"
    shown_slots = slots[:MAX_MATCHES_PER_EMAIL]
    extra_count = max(0, len(slots) - len(shown_slots))
    lines = [
        greeting,
        "",
        f"These cached Table for Two slots matched your {subscription.party_size}-pax alert:",
        "",
        *[f"- {format_slot(slot)}" for slot in shown_slots],
    ]
    if extra_count:
        lines.append(f"- ... and {extra_count} more")
    lines.extend(
        [
            "",
            "Book and redeem in the Amex Experiences App. This email is based on cached DiningCity AMEXPlatSG availability and should be reconfirmed before making plans.",
            "",
            site_url,
        ]
    )
    if unsubscribe_url:
        lines.extend(["", f"Unsubscribe: {unsubscribe_url}"])
    text_body = "\n".join(lines)
    html_items = "".join(f"<li>{html.escape(format_slot(slot))}</li>" for slot in shown_slots)
    if extra_count:
        html_items += f"<li>... and {extra_count} more</li>"
    html_body = f"""
    <p>{html.escape(greeting)}</p>
    <p>These cached Table for Two slots matched your {subscription.party_size}-pax alert:</p>
    <ul>{html_items}</ul>
    <p>Book and redeem in the Amex Experiences App. Reconfirm cached DiningCity AMEXPlatSG availability before making plans.</p>
    <p><a href="{html.escape(site_url)}">Open Table for Two explorer</a></p>
    """
    if unsubscribe_url:
        html_body += f"""
        <p style="color:#6b7280;font-size:12px">
          <a href="{html.escape(unsubscribe_url)}">Unsubscribe from these alerts</a>
        </p>
        """

    message = EmailMessage()
    message["Subject"] = subject
    add_common_headers(message, sender, subscription.email, reply_to, unsubscribe_url, one_click_unsubscribe)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def build_expired_email(
    subscription: Subscription,
    sender: str,
    signup_url: str,
    reply_to: str = "",
    unsubscribe_url: str = "",
    one_click_unsubscribe: bool = False,
) -> EmailMessage:
    subject = "Table for Two alert expired"
    greeting = f"Hi {subscription.name}," if subscription.name else "Hi,"
    scope_lines = subscription_scope_lines(subscription)
    lines = [
        greeting,
        "",
        "We did not find any cached Table for Two slots matching your alert before your selected dates passed.",
    ]
    if scope_lines:
        lines.extend(["", "Alert details:", *[f"- {line}" for line in scope_lines]])
    if signup_url:
        lines.extend(["", "You can create a new alert here:", signup_url])
    if unsubscribe_url:
        lines.extend(["", f"Unsubscribe: {unsubscribe_url}"])
    text_body = "\n".join(lines)
    html_scope = "".join(f"<li>{html.escape(line)}</li>" for line in scope_lines)
    html_body = f"""
    <p>{html.escape(greeting)}</p>
    <p>We did not find any cached Table for Two slots matching your alert before your selected dates passed.</p>
    {f"<p>Alert details:</p><ul>{html_scope}</ul>" if html_scope else ""}
    {f'<p><a href="{html.escape(signup_url)}">Create a new alert</a></p>' if signup_url else ""}
    """
    if unsubscribe_url:
        html_body += f"""
        <p style="color:#6b7280;font-size:12px">
          <a href="{html.escape(unsubscribe_url)}">Unsubscribe from these alerts</a>
        </p>
        """

    message = EmailMessage()
    message["Subject"] = subject
    add_common_headers(message, sender, subscription.email, reply_to, unsubscribe_url, one_click_unsubscribe)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def smtp_config_from_env() -> dict[str, Any]:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ.get("SMTP_FROM", user).strip()
    reply_to = os.environ.get("SMTP_REPLY_TO", "").strip()
    unsubscribe_base_url = os.environ.get("ALERT_UNSUBSCRIBE_BASE_URL", "").strip()
    one_click_unsubscribe = parse_enabled(os.environ.get("ALERT_ONE_CLICK_UNSUBSCRIBE") or "false")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "reply_to": reply_to,
        "unsubscribe_base_url": unsubscribe_base_url,
        "one_click_unsubscribe": one_click_unsubscribe,
    }


def send_messages(messages: list[EmailMessage], config: dict[str, Any]) -> None:
    if not messages:
        return
    if not config["host"] or not config["sender"]:
        raise RuntimeError("SMTP_HOST and SMTP_FROM or SMTP_USER are required when matches need emails")
    if config["port"] == 465:
        with smtplib.SMTP_SSL(config["host"], config["port"], context=ssl.create_default_context(), timeout=30) as server:
            if config["user"]:
                server.login(config["user"], config["password"])
            for message in messages:
                server.send_message(message)
        return
    with smtplib.SMTP(config["host"], config["port"], timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        if config["user"]:
            server.login(config["user"], config["password"])
        for message in messages:
            server.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_DATA_PATH)
    parser.add_argument("--subscriptions", default="data/table-for-two-alerts.json")
    parser.add_argument("--subscriptions-csv-url", default=os.environ.get("TABLE_FOR_TWO_ALERTS_CSV_URL", ""))
    parser.add_argument("--sent-log", default=DEFAULT_SENT_LOG_PATH)
    parser.add_argument("--site-url", default=os.environ.get("ALERT_SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--signup-url", default=os.environ.get("TABLE_FOR_TWO_ALERT_SIGNUP_URL", ""))
    parser.add_argument("--today", default="", help="Override today's date as YYYY-MM-DD for expiry testing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-emails", type=int, default=50)
    args = parser.parse_args()

    payload = load_json(args.data)
    venues = payload.get("venues") or []
    venue_aliases = build_venue_aliases(venues)
    subscriptions = load_json_subscriptions(Path(args.subscriptions), venue_aliases)
    if args.subscriptions_csv_url:
        subscriptions.extend(load_csv_subscriptions(fetch_text(args.subscriptions_csv_url), venue_aliases, "csv"))

    if not subscriptions:
        print("No Table for Two alert subscriptions configured.")
        return 0

    salt = os.environ.get("ALERT_HASH_SALT", "")
    if not salt and not args.dry_run:
        raise RuntimeError("ALERT_HASH_SALT is required so sent-log hashes are not reversible")

    sent_log_path = Path(args.sent_log)
    sent_log = load_sent_log(sent_log_path)
    sent_keys: dict[str, str] = sent_log["sent_keys"]
    smtp_config = smtp_config_from_env()
    messages: list[EmailMessage] = []
    newly_sent_keys: list[str] = []
    pending_sent_keys: set[str] = set()
    today = iso_date(args.today) if args.today else today_singapore()
    if today is None:
        raise ValueError("--today must be YYYY-MM-DD")

    for subscription in subscriptions:
        matches = matching_slots(subscription, venues)
        new_matches = [
            slot
            for slot in matches
            if slot_key(subscription, slot, salt) not in sent_keys
            and slot_key(subscription, slot, salt) not in pending_sent_keys
        ]
        fulfilled_key = subscription_state_key(subscription, "matched", salt)
        expired_key = subscription_state_key(subscription, "expired", salt)
        unsubscribe_url = unsubscribe_url_for(subscription, salt, smtp_config["unsubscribe_base_url"])
        if new_matches:
            new_slot_keys = [slot_key(subscription, slot, salt) for slot in new_matches]
            messages.append(
                build_email(
                    subscription,
                    new_matches,
                    sender=smtp_config["sender"] or "dinnertime@kooexperience.com",
                    site_url=args.site_url,
                    reply_to=smtp_config["reply_to"],
                    unsubscribe_url=unsubscribe_url,
                    one_click_unsubscribe=smtp_config["one_click_unsubscribe"],
                )
            )
            newly_sent_keys.extend(new_slot_keys)
            pending_sent_keys.update(new_slot_keys)
            newly_sent_keys.append(fulfilled_key)
            pending_sent_keys.add(fulfilled_key)
        elif (
            subscription_is_expired(subscription, today)
            and fulfilled_key not in sent_keys
            and fulfilled_key not in pending_sent_keys
            and expired_key not in sent_keys
            and expired_key not in pending_sent_keys
        ):
            messages.append(
                build_expired_email(
                    subscription,
                    sender=smtp_config["sender"] or "dinnertime@kooexperience.com",
                    signup_url=args.signup_url or args.site_url,
                    reply_to=smtp_config["reply_to"],
                    unsubscribe_url=unsubscribe_url,
                    one_click_unsubscribe=smtp_config["one_click_unsubscribe"],
                )
            )
            newly_sent_keys.append(expired_key)
            pending_sent_keys.add(expired_key)
        if len(messages) >= args.max_emails:
            break

    if args.dry_run:
        print(f"Loaded {len(subscriptions)} subscriptions; {len(messages)} emails would be sent.")
        for message in messages:
            print(f"- {message['To']}: {message['Subject']}")
        return 0

    send_messages(messages, smtp_config)
    timestamp = now_iso()
    for key in newly_sent_keys:
        sent_keys[key] = timestamp
    if messages:
        write_json(sent_log_path, {"updated_at": timestamp, "sent_keys": sent_keys})
    print(f"Loaded {len(subscriptions)} subscriptions; sent {len(messages)} Table for Two alert emails.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Table for Two alerts failed: {exc}", file=sys.stderr)
        raise
