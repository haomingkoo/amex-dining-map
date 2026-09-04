"""Shared UTC timestamp helpers.

Every pipeline writes and reads the same `YYYY-MM-DDTHH:MM:SSZ` shape, and the
lenient parse was hand-rolled in four places with slightly different handling of
naive input. Strict, field-named parsing stays in the modules that raise their own
domain errors, because the message is the point there.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso_now() -> str:
    """Now, as the second-precision UTC stamp every dataset stores."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: object) -> datetime | None:
    """Parse a stored timestamp to aware UTC, or None if it is unusable.

    A naive timestamp is rejected rather than assumed to be UTC: guessing the zone
    is how a stale record reads as fresh.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
