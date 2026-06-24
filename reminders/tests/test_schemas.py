from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import SubscribeRequest


def _payload(**overrides):
    base = {
        "email": "guest@example.com",
        "name": "Alice",
        "party_size": 2,
        "sessions": ["Dinner"],
        "venues": ["15 Stamford Restaurant"],
        "date_start": (date.today() + timedelta(days=3)).isoformat(),
        "date_end": (date.today() + timedelta(days=20)).isoformat(),
    }
    base.update(overrides)
    return base


def test_valid_payload_passes():
    model = SubscribeRequest(**_payload())

    assert model.to_input().email == "guest@example.com"
    assert model.to_input().venues == ["15 Stamford Restaurant"]


def test_any_venue_normalizes():
    model = SubscribeRequest(**_payload(venues=["Any", "15 Stamford Restaurant"]))

    assert model.venues == ["any"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"party_size": 0},
        {"party_size": 21},
        {"sessions": []},
        {"sessions": ["Brunch"]},
        {"venues": ["No Such Restaurant"]},
        {"venues": []},
        {"date_start": (date.today() - timedelta(days=1)).isoformat()},
        {
            "date_start": (date.today() + timedelta(days=10)).isoformat(),
            "date_end": (date.today() + timedelta(days=2)).isoformat(),
        },
        {"date_end": (date.today() + timedelta(days=200)).isoformat()},
    ],
)
def test_invalid_payloads_rejected(overrides):
    with pytest.raises(ValidationError):
        SubscribeRequest(**_payload(**overrides))
