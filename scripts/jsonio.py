"""Shared dataset JSON helpers.

Other `load_json(path, default)` variants stay in their own modules: they differ
from `load_json_or` on whether corrupt JSON is an error or a missing file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    """Read a dataset. Raises if the file is missing or malformed."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_or(path: Path, default: Any) -> Any:
    """Read a dataset, or `default` when the file does not exist. Malformed JSON raises."""
    if not path.exists():
        return default
    return load_json(path)


def save_json(path: str | Path, payload: Any) -> None:
    """Write a dataset in this repo's standard shape."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def manifest_sha256(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's canonical ASCII JSON form."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
