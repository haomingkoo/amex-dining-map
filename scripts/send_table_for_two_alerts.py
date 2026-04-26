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
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any


DEFAULT_DATA_PATH = "data/table-for-two.json"
DEFAULT_SENT_LOG_PATH = "data/table-for-two-alert-sent.json"
DEFAULT_SITE_URL = "https://amex-explorer.kooexperience.com/#/table-for-two"
MAX_MATCHES_PER_EMAIL = 24


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
    source_label: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "amex-dining-map table-for-two alerts"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


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
    dates = parse_dates(value_from_row(row, ("dates", "date", "desired dates", "free dates", "alert dates")))
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


def build_email(subscription: Subscription, slots: list[dict[str, Any]], sender: str, site_url: str, reply_to: str = "") -> EmailMessage:
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

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = subscription.email
    if reply_to:
        message["Reply-To"] = reply_to
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
    return {"host": host, "port": port, "user": user, "password": password, "sender": sender, "reply_to": reply_to}


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

    for subscription in subscriptions:
        matches = matching_slots(subscription, venues)
        new_matches = [slot for slot in matches if slot_key(subscription, slot, salt) not in sent_keys]
        if not new_matches:
            continue
        messages.append(
            build_email(
                subscription,
                new_matches,
                sender=smtp_config["sender"] or "dinnertime@kooexperience.com",
                site_url=args.site_url,
                reply_to=smtp_config["reply_to"],
            )
        )
        newly_sent_keys.extend(slot_key(subscription, slot, salt) for slot in new_matches)
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
