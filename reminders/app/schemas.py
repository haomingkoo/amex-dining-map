"""Request validation for the subscribe endpoint (Pydantic v2)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.db import SubscriberInput

MAX_HORIZON_DAYS = 120
VENUES_PATH = Path(__file__).parent / "venues.json"


def load_known_venues(path: Path = VENUES_PATH) -> set[str]:
    """Lowercased set of acceptable venue names; empty if the bundle is missing."""
    try:
        names = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return set()
    return {str(name).strip().lower() for name in names if str(name).strip()}


_KNOWN_VENUES = load_known_venues()


class SubscribeRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    party_size: int
    sessions: list[Literal["Lunch", "Dinner"]]
    venues: list[str]
    date_start: date
    date_end: date
    website: str = ""  # honeypot — handled in the route, not validated here

    @field_validator("party_size")
    @classmethod
    def _party_size(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("party_size must be between 1 and 20")
        return value

    @field_validator("sessions")
    @classmethod
    def _sessions(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("pick at least one session")
        return list(dict.fromkeys(value))

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()[:80] or None

    @field_validator("venues")
    @classmethod
    def _venues(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("pick at least one venue")
        if any(item.lower() == "any" for item in cleaned):
            return ["any"]
        if _KNOWN_VENUES:
            unknown = [item for item in cleaned if item.lower() not in _KNOWN_VENUES]
            if unknown:
                raise ValueError(f"unknown venue(s): {', '.join(unknown)}")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _dates(self) -> "SubscribeRequest":
        today = date.today()
        if self.date_start > self.date_end:
            raise ValueError("date_start must be on or before date_end")
        if self.date_start < today:
            raise ValueError("date_start must not be in the past")
        if self.date_end > today + timedelta(days=MAX_HORIZON_DAYS):
            raise ValueError(f"date_end must be within {MAX_HORIZON_DAYS} days")
        return self

    def to_input(self) -> SubscriberInput:
        return SubscriberInput(
            email=str(self.email).lower(),
            name=self.name,
            party_size=self.party_size,
            sessions=list(self.sessions),
            venues=self.venues,
            date_start=self.date_start.isoformat(),
            date_end=self.date_end.isoformat(),
        )
