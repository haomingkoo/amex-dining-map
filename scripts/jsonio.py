"""Shared dataset JSON helpers.

Every pipeline writes its dataset the same way, and every consumer has to cope
with the same handful of container shapes. Both were hand-copied across the
scripts, so a change to either meant finding all the copies.

`load_json` is deliberately not here yet: it exists in eleven modules under two
different signatures, one returning a default for a missing file, and merging
those is a separate change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_json(path: Path, payload: Any) -> None:
    """Write a dataset the way every dataset in this repo is written."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Pull the record list out of whichever container shape a dataset uses."""
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "records", "restaurants", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    return []
