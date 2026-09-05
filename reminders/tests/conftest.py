"""Shared reminders test setup.

tft_guide keeps the catalogue in use in module-level state so /healthz and the
guide answer from the same copy. That state outlives a test, so a test that
adopts a published catalogue leaves the next one reading it. The suite passed
alone and failed when collected alongside scripts/tests purely because the
ordering changed, which is the kind of failure that wastes an afternoon.

Resetting before every test makes each one start from the baked copy regardless
of what ran first.
"""

from __future__ import annotations

import pytest

from app import tft_guide


@pytest.fixture(autouse=True)
def _reset_catalog_in_use():
    """Start and finish every test on the baked catalogue."""
    tft_guide.use_baked_catalog()
    yield
    tft_guide.use_baked_catalog()
