#!/usr/bin/env python3
"""Promote reviewed Tabelog matches into the quality signal file."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
QUALITY_SIGNALS_PATH = DATA_DIR / "restaurant-quality-signals.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def honest_stars(score_raw: float) -> float:
    if score_raw >= 4.0:
        return 5
    if score_raw >= 3.5:
        return 4.5
    if score_raw >= 3.4:
        return 4
    if score_raw >= 3.3:
        return 3.5
    if score_raw >= 3.1:
        return 3
    if score_raw >= 3.0:
        return 2
    return 1


def normalize_review_entry(entry: dict) -> tuple[str, dict]:
    record_id = entry.get("id")
    if not record_id:
        raise ValueError(f"missing id in review entry: {entry}")

    score_raw = entry.get("score_raw")
    review_count = entry.get("review_count")
    url = entry.get("url")
    notes = entry.get("notes")
    if score_raw is None or review_count is None or not url or not notes:
        raise ValueError(f"review entry for {record_id} is missing required fields")

    signal = {
        "score_raw": float(score_raw),
        "honest_stars": entry.get("honest_stars", honest_stars(float(score_raw))),
        "review_count": int(review_count),
        "url": url,
        "match_confidence": entry.get("match_confidence", "reviewed_batch"),
        "last_checked_at": entry.get("last_checked_at", date.today().isoformat()),
        "notes": notes,
    }

    for optional_key in ("native_name", "native_address", "google_query"):
        if entry.get(optional_key):
            signal[optional_key] = entry[optional_key]

    return record_id, {"tabelog": signal}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing reviewed Tabelog matches")
    parser.add_argument(
        "--output",
        type=Path,
        default=QUALITY_SIGNALS_PATH,
        help="Path to write updated quality signals JSON",
    )
    args = parser.parse_args()

    reviewed = load_json(args.input, [])
    if not isinstance(reviewed, list):
        raise SystemExit("Reviewed input must be a JSON array.")

    signals = load_json(args.output, {})
    updated = 0
    for entry in reviewed:
        record_id, payload = normalize_review_entry(entry)
        signals[record_id] = {
            **signals.get(record_id, {}),
            **payload,
        }
        updated += 1

    ordered = {key: signals[key] for key in sorted(signals)}
    save_json(args.output, ordered)
    print(f"Promoted {updated} reviewed Tabelog matches into {args.output}")


if __name__ == "__main__":
    main()
