"""Inline buttons for the guide bot, and the commands their taps stand for."""

from __future__ import annotations

import re

from app import tft_guide


VENUE_ID_RE = re.compile(r"[a-z0-9-]{1,56}")
PICK_VENUE = "Which venue? Tap one."


def _button(label: str, data: str) -> dict:
    return {"text": label, "callback_data": data}


def main_menu() -> dict:
    return {
        "inline_keyboard": [
            [_button("Slots this week", "slots:any"), _button("Set a reminder", "remind")],
            [_button("Venue info", "pick:venue"), _button("Best time to look", "pick:best")],
        ]
    }


def venue_menu(venue_id: str) -> dict:
    return {
        "inline_keyboard": [
            [_button("Slots this week", f"slots:{venue_id}"), _button("Set a reminder", f"remind:{venue_id}")],
            [_button("Venue info", f"venue:{venue_id}"), _button("Best time to look", f"best:{venue_id}")],
        ]
    }


def venue_picker(action: str, catalog: dict) -> dict:
    venues = [
        venue for venue in catalog.get("venues") or []
        if VENUE_ID_RE.fullmatch(str(venue.get("id") or ""))
    ]
    buttons = [_button(str(venue["name"])[:40], f"{action}:{venue['id']}") for venue in venues]
    return {"inline_keyboard": [buttons[index:index + 2] for index in range(0, len(buttons), 2)]}


def callback_text(data: str) -> str | None:
    """The command a button tap stands for; None for anything unrecognised."""
    if data == "remind":
        return "/remind"
    action, _, venue_id = data.partition(":")
    if action == "slots" and venue_id == "any":
        return "/slots any this week"
    if not VENUE_ID_RE.fullmatch(venue_id):
        return None
    return {
        "slots": f"/slots {venue_id} this week",
        "remind": f"/start remind_{venue_id}",
        "venue": f"/venue {venue_id}",
        "best": f"/release {venue_id}",
    }.get(action)


def markup_for(text: str, catalog: dict) -> dict | None:
    """Buttons to show under the reply to this command."""
    message = " ".join(text.strip().split()).casefold()
    if message in {"/start", "/help", "help"}:
        return main_menu()
    match = re.fullmatch(r"/(?:venue|release) (.+)", message)
    if match:
        venues = tft_guide.resolve_venue(match.group(1), catalog)
        if len(venues) == 1 and VENUE_ID_RE.fullmatch(str(venues[0]["id"])):
            return venue_menu(str(venues[0]["id"]))
    return None
