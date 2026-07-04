#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "love-dining.json"


def main() -> None:
    records = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    missing = [
        record["name"]
        for record in records
        if record.get("location_pin_hidden") is not True
        and (record.get("lat") is None or record.get("lng") is None)
    ]
    assert not missing, f"Love Dining records missing map pins: {', '.join(missing)}"


if __name__ == "__main__":
    main()
