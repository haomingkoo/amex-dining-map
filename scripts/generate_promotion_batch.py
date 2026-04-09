#!/usr/bin/env python3
"""Generate a promotion batch from verified/review matches not yet in quality signals.

Usage:
    python3 scripts/generate_promotion_batch.py
    python3 scripts/generate_promotion_batch.py --include-review  # include review tier too
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_PATH = DATA_DIR / "tabelog-match-results.json"
SIGNALS_PATH = DATA_DIR / "restaurant-quality-signals.json"
OUTPUT_PATH = DATA_DIR / "review-promotion-batch.json"


def honest_stars(score_raw: float) -> float:
    if score_raw >= 4.0: return 5
    if score_raw >= 3.5: return 4.5
    if score_raw >= 3.4: return 4
    if score_raw >= 3.3: return 3.5
    if score_raw >= 3.1: return 3
    if score_raw >= 3.0: return 2
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-review", action="store_true",
                        help="Also include review-tier matches (default: verified only)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    results = json.loads(RESULTS_PATH.read_text())
    signals = json.loads(SIGNALS_PATH.read_text()) if SIGNALS_PATH.exists() else {}
    already_signaled = set(signals.keys())

    include_statuses = {"verified"}
    if args.include_review:
        include_statuses.add("review")

    batch = []
    skipped_no_detail = 0

    for r in results:
        rid = r.get("id")
        if not rid or rid in already_signaled:
            continue

        best = r.get("best_candidates") or []
        if not best:
            continue
        top = best[0]
        if top.get("match_status") not in include_statuses:
            continue

        detail = top.get("detail") or {}
        score_raw = detail.get("rating_value") or top.get("score_raw")
        review_count = detail.get("rating_count") or top.get("review_count")
        url = top.get("url") or detail.get("url")

        if not score_raw or not url:
            skipped_no_detail += 1
            continue

        # Build notes from match reasons
        reasons = top.get("match_reasons") or []
        confidence = top.get("match_confidence", 0)
        notes = f"Auto-matched: {', '.join(reasons)}" if reasons else f"Cache URL match (confidence {confidence})"

        entry = {
            "id": rid,
            "score_raw": float(score_raw),
            "honest_stars": honest_stars(float(score_raw)),
            "review_count": int(review_count) if review_count else 0,
            "url": url.replace("/en/", "/"),  # normalise to JP URL
            "match_confidence": f"auto_{top.get('match_status')}_{confidence}",
            "last_checked_at": date.today().isoformat(),
            "notes": notes,
        }

        native_name = detail.get("name") or top.get("name")
        if native_name:
            entry["native_name"] = native_name

        address = detail.get("street_address") or detail.get("full_address_text")
        if address:
            entry["native_address"] = address

        batch.append(entry)

    args.output.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n")
    print(f"Generated {len(batch)} entries → {args.output}")
    if skipped_no_detail:
        print(f"Skipped {skipped_no_detail} matches with missing score/URL (detail not fetched)")


if __name__ == "__main__":
    main()
