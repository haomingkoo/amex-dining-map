#!/usr/bin/env python3
"""Audit active data for unverified generated prose.

The public app should not present AI-written ambience, famous-dish, or
"worth a visit" wording as factual source data. Official source summaries are
allowed, but generated `summary_ai` fields are blocked from active datasets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATASETS = [
    Path("data/global-restaurants.json"),
    Path("data/japan-restaurants.json"),
    Path("data/love-dining.json"),
    Path("data/table-for-two.json"),
]


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "records", "restaurants", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable audit output")
    args = parser.parse_args()

    issues: list[str] = []
    scanned = 0
    for path in DATASETS:
        records = records_from_payload(json.loads(path.read_text(encoding="utf-8")))
        scanned += len(records)
        for record in records:
            if (record.get("summary_ai") or "").strip():
                issues.append(f"{path}: {record.get('id')} / {record.get('name')} has active summary_ai")

    payload = {
        "scanned_records": scanned,
        "issue_count": len(issues),
        "issues": issues,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Scanned {scanned} active records for generated prose.")
        if issues:
            print("\nGenerated prose still present:")
            for issue in issues:
                print(f"- {issue}")
        else:
            print("No active summary_ai fields found.")

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())

