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


CATALOG_PATH = Path(__file__).with_name("tft_guide_catalog.json")
MENU_STALE_AFTER = timedelta(hours=36)
MAX_REPLY_LENGTH = 3900


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> dict:
    return json.loads(path.read_text())


def normalize_venue(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    return normalized.removeprefix("tft ").strip()


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


def _valid_published_menu(menu: dict, now: datetime) -> tuple[bool, bool]:
    if menu.get("status") != "published" or not menu.get("sha256"):
        return False, False
    parsed = urlparse(str(menu.get("url") or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "americanexpress.com" or host.endswith(".americanexpress.com")
    ):
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
    review = (
        " The wider program source snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    return f"Menu index checked: {checked_label}.{freshness}{review}"


def _help() -> str:
    return (
        "Table for Two helper\n\n"
        "/venues — list current cached roster\n"
        "/menu VUE platinum — official Amex menu\n"
        "/menu VUE centurion — Centurion variant\n"
        "/help — show these commands\n\n"
        "I use a generated source catalogue and do not guess. Confirm offers and bookings "
        "in the Amex Experiences App."
    )


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
        f"Official source: {catalog['official_url']}\n\n"
        "Try /menu VUE platinum"
    )[:MAX_REPLY_LENGTH]


def _menu_answer(venue: dict, card: str | None, catalog: dict, now: datetime) -> str:
    menus = venue.get("menus") or {}
    available = [key for key, menu in menus.items() if menu.get("status") == "published"]
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
        explorer = f"https://amex-explorer.kooexperience.com/{venue['explorer_route']}"
        review_note = (
            "\nThe wider program source snapshot is awaiting manual review."
            if catalog.get("manual_review_required")
            else ""
        )
        return (
            f"{venue['name']} — official menu variants\n\n"
            + "\n\n".join(lines)
            + review_note
            + "\n\nPlatinum and Centurion are separate files. Confirm the current offer in the Amex Experiences App."
            + f"\nOpen venue: {explorer}"
        )[:MAX_REPLY_LENGTH]
    selected = card or (available[0] if len(available) == 1 else None)
    menu = menus.get(selected) or menus.get("default")
    explorer = f"https://amex-explorer.kooexperience.com/{venue['explorer_route']}"
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
            f"Official TFT page: {catalog['official_url']}\n"
            f"Open venue: {explorer}"
        )
    status = menu.get("status")
    if status == "buffet_no_menu_expected":
        return (
            f"{venue['name']}\n\nThis is listed as a buffet venue, so a Table for Two "
            f"set-menu PDF is not expected in the current index.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"Official TFT page: {catalog['official_url']}\n"
            f"Open venue: {explorer}"
        )
    if status != "published":
        heading = f"{selected.title()} menu" if selected else "menu"
        return (
            f"{venue['name']} — {heading}\n\n"
            f"No official PDF was matched in the stored Amex menu scan. "
            f"Manual review is pending; this does not prove no menu exists.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"Official TFT page: {catalog['official_url']}\nOpen venue: {explorer}"
        )
    valid, stale = _valid_published_menu(menu, now)
    if not valid:
        heading = f"{selected.title()} menu" if selected else "menu"
        return (
            f"{venue['name']} — {heading}\n\n"
            "The stored menu metadata could not be verified safely. Check the Amex app.\n"
            f"{_menu_source_context(menu, catalog, now)}\n"
            f"Official TFT page: {catalog['official_url']}\nOpen venue: {explorer}"
        )
    stale_note = " The index check is older than 36 hours; verify it is still current." if stale else ""
    review_note = (
        " The wider program source snapshot is awaiting manual review."
        if catalog.get("manual_review_required")
        else ""
    )
    label = menu.get("label") or (selected.title() if selected else "Menu")
    return (
        f"{venue['name']} — {label} menu\n\n"
        f"Official Amex PDF: {menu['url']}\n"
        f"Menu listing checked: {_date(menu.get('checked_at'))}.{stale_note}{review_note}\n\n"
        "Platinum and Centurion files are separate. Confirm the current offer and booking details in the Amex Experiences App.\n"
        f"Open venue: {explorer}"
    )[:MAX_REPLY_LENGTH]


def handle_message(text: str, catalog: dict, now: datetime | None = None) -> str:
    message = " ".join(text.strip().split())
    lowered = message.casefold()
    if lowered in {"/start", "/help", "help"}:
        return _help()
    if lowered == "/venues":
        return _venues(catalog, now or datetime.now(timezone.utc))

    is_menu_command = lowered.startswith("/menu")
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
    return _menu_answer(matches[0], card, catalog, now or datetime.now(timezone.utc))
