#!/usr/bin/env python3
"""Publish or reject a review-gated public update."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("update_id")
    parser.add_argument("--file", default="data/updates.json")
    parser.add_argument("--status", choices=("published", "rejected"), default="published")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    path = Path(args.file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = [update for update in payload.get("updates", []) if update.get("id") == args.update_id]
    if not matches:
        parser.error(f"update not found: {args.update_id}")

    update = matches[0]
    update["status"] = args.status
    update["reviewed_at"] = now_iso()
    if args.note:
        update["review_note"] = args.note
    payload["updated_at"] = update["reviewed_at"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.update_id}: {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
