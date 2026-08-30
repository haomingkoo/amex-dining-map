#!/usr/bin/env python3
"""Prepare an exact manifest for one concrete TFT menu candidate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import tft_menu_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--decision", choices=sorted(tft_menu_reviews.DECISIONS), required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--review-note", required=True)
    parser.add_argument("--data", type=Path, default=Path("data/table-for-two.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing manifest: {args.output}")
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    reviewed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = tft_menu_reviews.prepare_manifest(
        payload,
        args.candidate_id,
        args.decision,
        reviewed_at,
        args.reviewed_by,
        args.review_note,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {args.decision} manifest for {args.candidate_id}")
    if args.decision == "approved":
        print("Apply it with --pdf pointing to the exact reviewed candidate PDF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
