"""Shared dataset JSON helpers.

`load_json` is not here yet: eleven modules define it under two signatures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_json(path: Path, payload: Any) -> None:
    """Write a dataset in this repo's standard shape."""
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
