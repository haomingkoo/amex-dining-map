"""Coarse 'are there already open tables?' check for the confirm email.

Deliberately venue+session level only — not the full slot/date/party matcher
that the alert job runs. Good enough to add urgency to the confirm email
without duplicating the matching pipeline. Fails closed (returns False) if the
data can't be fetched.

# ponytail: coarse by design; the precise match still happens in the alert job.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def open_tables_exist(
    venues: list[str], sessions: list[str], data_url: str, timeout: int = 4
) -> bool:
    try:
        with urllib.request.urlopen(data_url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False

    want_any = not venues or any(item.lower() == "any" for item in venues)
    want_venues = {item.lower() for item in venues}
    want_sessions = {item.lower() for item in sessions}
    for venue in data.get("venues", []):
        availability = venue.get("availability") or {}
        if availability.get("status") != "live_available":
            continue
        name = str(venue.get("name") or "").lower()
        if not want_any and name not in want_venues:
            continue
        for meal in availability.get("meals") or []:
            if meal.get("status") != "available":
                continue
            if not want_sessions or str(meal.get("meal") or "").lower() in want_sessions:
                return True
    return False
