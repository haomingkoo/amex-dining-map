"""Deterministic Table for Two venue and official-menu answers."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app import tft_documents, tft_slot_source, tft_slots


CATALOG_PATH = Path(__file__).with_name("tft_guide_catalog.json")
MENU_STALE_AFTER = timedelta(hours=36)
RELEASE_STALE_AFTER = timedelta(hours=36)
MAX_REPLY_LENGTH = 3900
SGT = ZoneInfo("Asia/Singapore")


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> dict:
    return json.loads(path.read_text())


def normalize_venue(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    return normalized.removeprefix("tft ").strip()


def _trusted_https_url(value: Any, allowed_hosts: set[str]) -> str | None:
    raw = str(value or "")
    if "\\" in raw or any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in raw
    ):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return raw


def _trusted_amex_url(value: Any) -> str | None:
    raw = str(value or "")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host != "americanexpress.com" and not host.endswith(".americanexpress.com"):
        return None
    return _trusted_https_url(raw, {host})


def _official_source_line(catalog: dict, label: str = "Official TFT page") -> str:
    url = _trusted_amex_url(catalog.get("official_url"))
    if url is None:
        return "Official TFT source metadata could not be verified safely."
    return f"{label}: {url}"


def explorer_url(
    venue_id: str | None = None,
    party_size: int | None = None,
    meal: str | None = None,
    date_value: str | None = None,
    day: str | None = None,
    preferred_time: str | None = None,
) -> str:
    params = []
    if venue_id and re.fullmatch(r"[a-z0-9-]{1,80}", venue_id):
        params.append(("venue", venue_id))
    if party_size is not None and 1 <= party_size <= 10:
        params.append(("party", str(party_size)))
    if meal in {"Lunch", "Dinner"}:
        params.append(("meal", meal.lower()))
    if date_value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
        params.append(("date", date_value))
    if day in {"weekend", "weekday"}:
        params.append(("day", day))
    if preferred_time and re.fullmatch(r"(?:[01]\d|2[0-3]):(?:00|30)", preferred_time):
        params.append(("time", preferred_time))
    query = urlencode(params)
    return "https://amex-explorer.kooexperience.com/#/table-for-two" + (f"?{query}" if query else "")


def _explorer_line(venue: dict) -> str:
    venue_id = str(venue.get("id") or "")
    if re.fullmatch(r"[a-z0-9-]{1,80}", venue_id) is None:
        return "Explorer venue link could not be verified safely."
    return f"Open venue: {explorer_url(venue_id=venue_id)}"


def resolve_venue(query: str, catalog: dict) -> list[dict]:
    wanted = normalize_venue(query)
    matches = []
    for venue in catalog.get("venues") or []:
        values = [
            venue.get("id", ""),
            venue.get("name", ""),
            venue.get("dining_city_name", ""),
            *(venue.get("aliases") or []),
        ]
        if wanted and wanted in {normalize_venue(str(value)) for value in values if value}:
            matches.append(venue)
    return matches


def _date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _date_sgt(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    return moment.astimezone(SGT).strftime("%d %b %Y, %H:%M SGT")


def _valid_published_menu(menu: dict, now: datetime) -> tuple[bool, bool]:
    if menu.get("status") != "published" or not menu.get("sha256"):
        return False, False
    if _trusted_amex_url(menu.get("url")) is None:
        return False, False
    try:
        checked = datetime.fromisoformat(str(menu["checked_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False, False
    if checked.tzinfo is None or checked > now + timedelta(minutes=5):
        return False, False
    return True, now - checked > MENU_STALE_AFTER


def _menu_source_context(menu: dict, catalog: dict, now: datetime) -> str:
    checked_value = menu.get("checked_at")
    checked_label = _date(checked_value)
    try:
        checked = datetime.fromisoformat(str(checked_value).replace("Z", "+00:00"))
        if checked.tzinfo is None or checked > now + timedelta(minutes=5):
            freshness = " Freshness is unknown; verify the official source."
        elif now - checked > MENU_STALE_AFTER:
            freshness = " The index check is older than 36 hours; verify it is still current."
        else:
            freshness = ""
    except (TypeError, ValueError):
        freshness = " Freshness is unknown; verify the official source."
    menu_source = catalog.get("menu_source") or {}
    review_count = menu_source.get("review_queue_count") or 0
    review = ""
    if menu_source.get("review_required"):
        review = (
            f" The menu index has {review_count} item"
            f"{'s' if review_count != 1 else ''} awaiting manual review."
        )
    elif catalog.get("manual_review_required"):
        review = " The wider program source snapshot is awaiting manual review."
    return f"Menu index checked: {checked_label}.{freshness}{review}"


def _help() -> str:
    return (
        "Table for Two helper\n\n"
        "/about — what this source-grounded helper covers\n"
        "/venues — list bundled roster snapshot\n"
        "/venue VUE — reviewed venue details\n"
        "/menu VUE platinum — official Amex menu\n"
        "/menu VUE centurion — Centurion variant\n"
        "/release VUE dinner — observed first-detection pattern\n"
        "/slots — observed slots with date and any/weekend examples\n"
        "/terms eligibility — reviewed official T&C summary\n"
        "/faq unavailable dates — reviewed official FAQ summary\n"
        "/remind — create a one-shot slot reminder when enabled\n"
        "/reminders — list your active Telegram reminders\n"
        "/cancel RXXXXXX — cancel one active Telegram reminder\n"
        "/delete_me — delete your Telegram reminder data\n"
        "/help — show these commands\n\n"
        "I use a generated source catalogue and do not guess. Confirm offers and bookings "
        "in the Amex Experiences App."
    )


def _roster_context(catalog: dict, now: datetime) -> str:
    try:
        checked = datetime.fromisoformat(
            str(catalog["roster_checked_at"]).replace("Z", "+00:00")
        )
        if checked.tzinfo is None or checked > now + timedelta(minutes=5):
            freshness = " Roster freshness is unknown; verify the official source."
        elif now - checked > MENU_STALE_AFTER:
            freshness = " Roster snapshot is older than 36 hours; verify the official source."
        else:
            freshness = ""
    except (KeyError, TypeError, ValueError):
        freshness = " Roster freshness is unknown; verify the official source."
    review = (
        " Source snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    return f"Roster checked: {_date(catalog.get('roster_checked_at'))}.{review}{freshness}"


def _about(catalog: dict, now: datetime) -> str:
    return (
        "American Express Table for Two by Platinum\n\n"
        "This helper uses a reviewed Table for Two venue roster, indexed official Amex "
        "menus, page-reviewed T&C and FAQ summaries, and bounded AMEXPlatSG slot and "
        "release observations. It does not determine personal eligibility, interpret "
        "terms, guarantee seats, or make a booking.\n\n"
        f"{_roster_context(catalog, now)}\n"
        f"{_official_source_line(catalog)}\n"
        f"Open Table for Two: {explorer_url()}\n\n"
        "Try /venues, /venue VUE, /terms benefit, /faq unavailable dates, or /slots."
    )[:MAX_REPLY_LENGTH]


def _safe_venue_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return None
    if any(
        character in "\r\n" or unicodedata.category(character).startswith("C")
        for character in value
    ):
        return None
    return value


def _venue_details(venue: dict, catalog: dict, now: datetime) -> str:
    name = _safe_venue_text(venue.get("name"), 120)
    venue_id = str(venue.get("id") or "")
    if name is None or re.fullmatch(r"[a-z0-9-]{1,80}", venue_id) is None:
        return "That venue's reviewed metadata could not be verified safely. Use /venues."
    address = _safe_venue_text(venue.get("address"), 300)
    category = _safe_venue_text(venue.get("category"), 40)
    details = [
        f"Address: {address}" if address else "Address: unavailable in the reviewed snapshot",
        f"Format: {category.title()}" if category else "Format: not specified",
    ]
    valid_menus = []
    stale_menu = False
    for key, menu in sorted((venue.get("menus") or {}).items()):
        if not isinstance(menu, dict):
            continue
        valid, stale = _valid_published_menu(menu, now)
        if valid:
            label = _safe_venue_text(menu.get("label"), 40) or key.title()
            valid_menus.append(label)
            stale_menu = stale_menu or stale
    if valid_menus:
        details.append("Indexed official menus: " + ", ".join(valid_menus))
        if stale_menu:
            details.append("One or more menu checks are older than 36 hours; verify the official source.")
    else:
        buffet = any(
            isinstance(menu, dict) and menu.get("status") == "buffet_no_menu_expected"
            for menu in (venue.get("menus") or {}).values()
        )
        details.append(
            "Current index marks this as a buffet; a set-menu PDF is not expected."
            if buffet
            else "No reviewed official menu PDF is currently matched; this does not prove no menu exists."
        )
    return (
        f"{name} — reviewed venue details\n\n"
        + "\n".join(details)
        + f"\n\n{_roster_context(catalog, now)}\n"
        + _menu_source_context(catalog.get("menu_source") or {}, catalog, now)
        + f"\n{_official_source_line(catalog)}\n{_explorer_line(venue)}"
    )[:MAX_REPLY_LENGTH]


def _natural_venue_query(message: str) -> tuple[str, str] | None:
    for intent, pattern in (
        ("details", r"where is (.+?)"),
        ("details", r"tell me about (.+?)"),
        ("menu", r"does (.+?) have (?:an? )?(?:official )?menu"),
    ):
        match = re.fullmatch(pattern + r"[?!.]*", message, flags=re.IGNORECASE)
        if match:
            return intent, match.group(1).strip()
    return None


def _release_time(value: str | None, now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed > now + timedelta(minutes=5):
        return None
    return parsed.astimezone(timezone.utc)


def _valid_release_pattern(
    pattern: dict, now: datetime, snapshot: datetime
) -> bool:
    try:
        count = int(pattern["observation_count"])
        median = float(pattern["median_lead_days"])
        minimum = int(pattern["lead_days_min"])
        maximum = int(pattern["lead_days_max"])
        share = float(pattern.get("typical_time_observation_share") or 0)
    except (KeyError, TypeError, ValueError):
        return False
    typical = pattern.get("typical_first_seen_sgt")
    latest = _release_time(pattern.get("latest_observation_at"), now)
    return (
        count >= 3
        and 0 <= minimum <= median <= maximum
        and 0 <= share <= 1
        and pattern.get("meal") in {"Lunch", "Dinner"}
        and pattern.get("confidence") in {"early", "medium", "high"}
        and (
            typical is None
            or re.fullmatch(r"(?:[01]\d|2[0-3]):(?:00|30)", str(typical))
            is not None
        )
        and latest is not None
        and latest <= snapshot
    )


def _release_pattern_line(pattern: dict, now: datetime) -> str:
    count = int(pattern["observation_count"])
    median = float(pattern["median_lead_days"])
    minimum = int(pattern["lead_days_min"])
    maximum = int(pattern["lead_days_max"])
    median_label = f"{median:g}"
    line = (
        f"{pattern['meal']}: median first-detected lead {median_label} days "
        f"(range {minimum}–{maximum}); {count} observations; "
        f"tracker confidence: {pattern['confidence']}."
    )
    typical = pattern.get("typical_first_seen_sgt")
    share = float(pattern.get("typical_time_observation_share") or 0)
    if typical and share >= 0.6:
        line += (
            f" First detected around {typical} SGT in about {share:.0%} of observations; "
            "scheduled polling can make detection later than the actual release."
        )
    line += f" Latest included detection: {_date_sgt(pattern['latest_observation_at'])}."
    return line


def _release_answer(venue: dict, meal: str | None, catalog: dict, now: datetime) -> str:
    source = catalog.get("release_source") or {}
    snapshot = _release_time(source.get("updated_at"), now)
    if source.get("project") != "AMEXPlatSG" or snapshot is None:
        return (
            f"{venue['name']} — observed release pattern\n\n"
            "The bundled history timestamp could not be verified safely, so I will not "
            "report a timing pattern.\n"
            f"{_official_source_line(catalog)}\n{_explorer_line(venue)}"
        )[:MAX_REPLY_LENGTH]
    patterns = [
        pattern
        for pattern in venue.get("release_patterns") or []
        if _valid_release_pattern(pattern, now, snapshot)
    ]
    if meal:
        patterns = [
            pattern for pattern in patterns if str(pattern.get("meal")).casefold() == meal
        ]
    if not patterns:
        meal_label = f" {meal.title()}" if meal else ""
        return (
            f"{venue['name']} — observed release pattern\n\n"
            f"There are not enough valid repeated{meal_label} observations to report a pattern. "
            "I will not extrapolate a release schedule.\n"
            f"History snapshot: {_date(source.get('updated_at'))}\n"
            f"{_official_source_line(catalog)}\n{_explorer_line(venue)}"
        )[:MAX_REPLY_LENGTH]
    lines = "\n\n".join(_release_pattern_line(pattern, now) for pattern in patterns)
    if now - snapshot > RELEASE_STALE_AFTER:
        freshness = "History snapshot is older than 36 hours; treat the pattern as stale."
    else:
        freshness = "History snapshot is within 36 hours."
    review = (
        " The wider TFT source snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    return (
        f"{venue['name']} — observed first-detection pattern\n\n{lines}\n\n"
        "Observed by scheduled AMEXPlatSG cache checks—not an Amex or restaurant release policy. "
        "Polling cadence can delay detection. This does not show current seat availability.\n"
        f"History snapshot: {_date(source.get('updated_at'))}. {freshness}{review}\n"
        f"{_official_source_line(catalog)}\n{_explorer_line(venue)}"
    )[:MAX_REPLY_LENGTH]


def _venues(catalog: dict, now: datetime) -> str:
    names = "\n".join(f"• {venue['name']}" for venue in catalog.get("venues") or [])
    caveat = (
        "\nSource snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    try:
        checked = datetime.fromisoformat(
            str(catalog["roster_checked_at"]).replace("Z", "+00:00")
        )
        if checked.tzinfo is None or checked > now + timedelta(minutes=5):
            freshness = "\nRoster freshness is unknown; verify the official source."
        elif now - checked > MENU_STALE_AFTER:
            freshness = "\nRoster snapshot is older than 36 hours; verify the official source."
        else:
            freshness = ""
    except (KeyError, TypeError, ValueError):
        freshness = "\nRoster freshness is unknown; verify the official source."
    return (
        f"Table for Two — cached roster\n\n{names}\n\n"
        f"Roster checked: {_date(catalog.get('roster_checked_at'))}{caveat}{freshness}\n"
        f"{_official_source_line(catalog, 'Official source')}\n\n"
        "Try /menu VUE platinum"
    )[:MAX_REPLY_LENGTH]


def _menu_answer(venue: dict, card: str | None, catalog: dict, now: datetime) -> str:
    menus = venue.get("menus") or {}
    available = [
        key for key, menu in menus.items() if _valid_published_menu(menu, now)[0]
    ]
    if card is None and len(available) > 1:
        lines = []
        for key in available:
            menu = menus[key]
            valid, stale = _valid_published_menu(menu, now)
            label = menu.get("label") or key.title()
            if valid:
                stale_note = " (older than 36h)" if stale else ""
                lines.append(
                    f"{label}: {menu['url']}\nChecked: {_date(menu.get('checked_at'))}{stale_note}"
                )
            else:
                lines.append(f"{label}: stored metadata could not be verified safely")
        review_note = "\n" + _menu_source_context(
            catalog.get("menu_source") or {}, catalog, now
        ) if (catalog.get("menu_source") or {}).get("review_required") else ""
        return (
            f"{venue['name']} — official menu variants\n\n"
            + "\n\n".join(lines)
            + review_note
            + "\n\nPlatinum and Centurion are separate files. Confirm the current offer in the Amex Experiences App."
            + f"\n{_explorer_line(venue)}"
        )[:MAX_REPLY_LENGTH]
    selected = card or (available[0] if len(available) == 1 else None)
    menu = menus.get(selected) if selected else menus.get("default")
    if (
        menu is None
        and selected is not None
        and (menus.get("default") or {}).get("status") != "published"
    ):
        menu = menus.get("default")
    if not menu:
        other = ", ".join((menus[key].get("label") or key.title()) for key in available)
        suffix = f" An indexed official {other} listing is available, but I will not substitute it." if other else ""
        heading = f"{selected.title()} menu" if selected else "menu"
        missing_label = f"{selected.title()} PDF" if selected else "menu PDF"
        return (
            f"{venue['name']} — {heading}\n\n"
            f"No indexed official {missing_label} is in the current Amex index.{suffix}\n"
            f"This does not prove no such menu exists.\n"
            f"{_menu_source_context(catalog.get('menu_source') or {}, catalog, now)}\n"
            f"{_official_source_line(catalog)}\n"
            f"{_explorer_line(venue)}"
        )
    status = menu.get("status")
    if status == "buffet_no_menu_expected":
        return (
            f"{venue['name']}\n\nThis is listed as a buffet venue, so a Table for Two "
            f"set-menu PDF is not expected in the current index.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"{_official_source_line(catalog)}\n"
            f"{_explorer_line(venue)}"
        )
    if status != "published":
        heading = f"{selected.title()} menu" if selected else "menu"
        return (
            f"{venue['name']} — {heading}\n\n"
            f"No official PDF was matched in the stored Amex menu scan. "
            f"Manual review is pending; this does not prove no menu exists.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"{_official_source_line(catalog)}\n{_explorer_line(venue)}"
        )
    valid, stale = _valid_published_menu(menu, now)
    if not valid:
        heading = f"{selected.title()} menu" if selected else "menu"
        return (
            f"{venue['name']} — {heading}\n\n"
            "The stored menu metadata could not be verified safely. Check the Amex app.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"{_official_source_line(catalog)}\n{_explorer_line(venue)}"
        )
    stale_note = " The index check is older than 36 hours; verify it is still current." if stale else ""
    menu_source = catalog.get("menu_source") or {}
    review_count = menu_source.get("review_queue_count") or 0
    review_note = (
        f" The menu index has {review_count} item"
        f"{'s' if review_count != 1 else ''} awaiting manual review."
        if menu_source.get("review_required")
        else " The wider program source snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    label = menu.get("label") or (selected.title() if selected else "Menu")
    return (
        f"{venue['name']} — {label} menu\n\n"
        f"Official Amex PDF: {menu['url']}\n"
        f"Menu listing checked: {_date(menu.get('checked_at'))}.{stale_note}{review_note}\n\n"
        "Platinum and Centurion files are separate. Confirm the current offer and booking details in the Amex Experiences App.\n"
        f"{_explorer_line(venue)}"
    )[:MAX_REPLY_LENGTH]


def handle_message(
    text: str,
    catalog: dict,
    now: datetime | None = None,
    slot_loader=None,
) -> str:
    message = " ".join(text.strip().split())
    lowered = message.casefold()
    current = now or datetime.now(timezone.utc)
    start_venue = re.fullmatch(r"/start venue_([a-z0-9-]{1,80})", lowered)
    if start_venue:
        matches = resolve_venue(start_venue.group(1), catalog)
        if len(matches) == 1:
            return _menu_answer(matches[0], None, catalog, current)
        return "That venue link is not in the reviewed TFT roster. Use /venues."
    if lowered.startswith("/start "):
        return _help()
    if lowered in {"/start", "/help", "help"}:
        return _help()
    about_questions = {
        "what is table for two",
        "what is tft",
        "how does table for two work",
        "how does tft work",
        "tell me about table for two",
        "tell me about tft",
    }
    if lowered == "/about" or normalize_venue(message) in about_questions:
        return _about(catalog, current)
    if lowered == "/venues":
        return _venues(catalog, current)
    if lowered == "/venue":
        return "Which venue? Try /venue VUE or use /venues."
    natural_venue = _natural_venue_query(message)
    venue_intent, venue_query = (
        ("details", message[len("/venue") :].strip())
        if lowered.startswith("/venue ")
        else natural_venue or (None, None)
    )
    if venue_query is not None:
        matches = resolve_venue(venue_query, catalog)
        if len(matches) != 1:
            return (
                "I could not match that to one exact Table for Two venue. "
                "Use /venues, then send /venue <exact venue>."
            )
        if venue_intent == "menu":
            return _menu_answer(matches[0], None, catalog, current)
        return _venue_details(matches[0], catalog, current)

    document_answer = tft_documents.answer(message, catalog, current)
    if document_answer is not None:
        return document_answer

    natural_slot_query = re.fullmatch(
        r"(?:which|what) (?:tft|table for two) venues? (?:have|has) weekend slots?\??",
        lowered,
    ) is not None
    if lowered == "/slots" or lowered.startswith("/slots ") or natural_slot_query:
        if natural_slot_query:
            today = current.astimezone(SGT).date()
            parsed = tft_slots.SlotRequest(
                venue_text="any",
                party_size=2,
                meal="Lunch or Dinner",
                start_date=today,
                end_date=today + timedelta(days=tft_slots.WEEKEND_RANGE_DAYS - 1),
                weekend_only=True,
                preferred_time=None,
            )
        else:
            parsed = tft_slots.parse_request(message, current)
        if isinstance(parsed, str):
            return parsed
        source = catalog.get("slot_source") or {}
        if (
            source.get("url") != tft_slot_source.SOURCE_URL
            or source.get("project") != tft_slots.PROJECT
            or source.get("stale_after_minutes") != 30
        ):
            return "The slot source metadata could not be verified safely."
        if parsed.venue_text.casefold() == "any":
            venues = list(catalog.get("venues") or [])
            venue_id = None
        else:
            venues = resolve_venue(parsed.venue_text, catalog)
            if len(venues) != 1:
                return (
                    "I could not match that to one exact Table for Two venue. "
                    "Use /venues, or use any to search all venues."
                )
            venue_id = str(venues[0].get("id") or "")
        explorer = "Open filtered Table for Two: " + explorer_url(
            venue_id=venue_id,
            party_size=parsed.party_size,
            meal=parsed.meal if parsed.meal in {"Lunch", "Dinner"} else None,
            date_value=None if parsed.weekend_only else parsed.start_date.isoformat(),
            day="weekend" if parsed.weekend_only else None,
            preferred_time=(
                parsed.preferred_time.strftime("%H:%M")
                if parsed.preferred_time is not None
                else None
            ),
        )
        try:
            snapshot = (slot_loader or tft_slot_source.load_snapshot)()
        except tft_slot_source.SlotSourceUnavailable:
            return (
                "I could not load the bounded AMEXPlatSG slot source right now, so I "
                "will not make an availability claim.\n"
                f"{_official_source_line(catalog)}\n{explorer}"
            )
        return tft_slots.answer(
            parsed,
            venues,
            snapshot,
            current,
            _official_source_line(catalog),
            explorer,
        )[:MAX_REPLY_LENGTH]

    if lowered == "/release" or lowered.startswith("/release "):
        query = message[len("/release") :].strip()
        if not query:
            return "Which venue? Try /release VUE dinner or use /venues."
        meal = None
        for candidate in ("lunch", "dinner"):
            if re.search(rf"\b{candidate}\b", query, flags=re.IGNORECASE):
                meal = candidate
                query = re.sub(
                    rf"\b{candidate}\b", " ", query, flags=re.IGNORECASE
                )
                break
        query = " ".join(query.split())
        matches = resolve_venue(query, catalog)
        if len(matches) != 1:
            return (
                "I could not match that to one exact Table for Two venue. "
                "Use /venues, then send /release <exact venue> lunch or dinner."
            )
        return _release_answer(
            matches[0], meal, catalog, current
        )

    is_menu_command = lowered == "/menu" or lowered.startswith("/menu ")
    wants_menu = is_menu_command or "menu" in lowered
    query = message[5:].strip() if is_menu_command else message
    card = None
    for tokens, value in (("black card", "centurion"), ("centurion", "centurion"), ("platinum", "platinum"), ("plat", "platinum")):
        if re.search(rf"\b{re.escape(tokens)}\b", query, flags=re.IGNORECASE):
            card = value
            query = re.sub(rf"\b{re.escape(tokens)}\b", " ", query, flags=re.IGNORECASE)
            break
    if not is_menu_command:
        query = re.sub(
            r"^show me\s+(?:the\s+)?", "", query, flags=re.IGNORECASE
        )
    query = re.sub(r"\b(?:official|menu|please)\b", " ", query, flags=re.IGNORECASE)
    query = " ".join(query.split())
    if not query:
        return "Which venue? Try /menu VUE platinum or use /venues."
    matches = resolve_venue(query, catalog)
    if not matches and query.casefold().startswith("the "):
        matches = resolve_venue(query[4:], catalog)
    if len(matches) != 1:
        return (
            "I could not match that to one exact Table for Two venue. "
            "Use /venues, then send /menu <exact venue> platinum or centurion."
        )
    if not wants_menu and not lowered.startswith("/"):
        wants_menu = True
    if not wants_menu:
        return _help()
    return _menu_answer(matches[0], card, catalog, current)
