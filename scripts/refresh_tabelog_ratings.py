#!/usr/bin/env python3
"""Re-fetch Tabelog pages of already-matched Japan venues to update score and review count.

No matching is re-run: each current venue's stored Tabelog URL is fetched fresh
(the HTTP cache is not loaded). Pages that fail or show no rating are listed and
left unchanged. Stops on 403/429 or repeated failures (likely a block).
"""

from __future__ import annotations

import argparse
import time
import urllib.error
from datetime import date

try:
    from scripts.jsonio import load_json, save_json
    from scripts.match_tabelog_candidates import canonical_candidate_url, fetch_detail_metadata
    from scripts.promote_tabelog_matches import QUALITY_SIGNALS_PATH, honest_stars
except ImportError:  # running as `python3 scripts/<file>.py`
    from jsonio import load_json, save_json
    from match_tabelog_candidates import canonical_candidate_url, fetch_detail_metadata
    from promote_tabelog_matches import QUALITY_SIGNALS_PATH, honest_stars

DATA_DIR = QUALITY_SIGNALS_PATH.parent
JAPAN_PATH = DATA_DIR / "japan-restaurants.json"
PAUSE_SECONDS = 3.0
BLOCK_STATUSES = {403, 429}
MAX_CONSECUTIVE_FAILURES = 3


def refreshed_signal(old: dict, detail: dict, today: str) -> dict | None:
    """Return the updated tabelog signal, or None when the page carries no rating."""
    if detail.get("rating_value") is None or detail.get("rating_count") is None:
        return None
    score = float(detail["rating_value"])
    signal = {
        **old,
        "score_raw": score,
        "honest_stars": honest_stars(score),
        "review_count": int(detail["rating_count"]),
        "last_checked_at": today,
    }
    if detail.get("moved_from"):
        signal["url"] = canonical_candidate_url(detail["url"])
    return signal


def oldest_checked_first(signals: dict, current_ids: set[str]) -> list[str]:
    ids = [rid for rid in signals if rid in current_ids and "tabelog" in signals[rid]]
    return sorted(ids, key=lambda rid: (str(signals[rid]["tabelog"].get("last_checked_at") or ""), rid))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only refresh the N least recently checked venues")
    args = parser.parse_args()

    signals = load_json(QUALITY_SIGNALS_PATH)
    current_ids = {record["id"] for record in load_json(JAPAN_PATH)}
    ids = oldest_checked_first(signals, current_ids)[: args.limit]
    today = date.today().isoformat()
    unchanged: list[str] = []
    consecutive_failures = 0

    for count, rid in enumerate(ids, 1):
        old = signals[rid]["tabelog"]
        if old.get("last_checked_at") == today:
            print(f"[{count}/{len(ids)}] {rid} already checked today", flush=True)
            continue
        signal = None
        try:
            detail = fetch_detail_metadata(old["url"])
            signal = refreshed_signal(old, detail, today)
            reason = "no_rating" if detail else "no_ld_json"
        except urllib.error.HTTPError as error:
            if error.code in BLOCK_STATUSES:
                raise SystemExit(f"Blocked with HTTP {error.code} at {old['url']}; stopping.") from error
            reason = f"http_{error.code}"
        except (urllib.error.URLError, TimeoutError) as error:
            reason = f"network: {error}"
        if signal is None:
            unchanged.append(rid)
            print(f"  unchanged {rid} ({reason}): {old['url']}", flush=True)
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise SystemExit(f"{MAX_CONSECUTIVE_FAILURES} failures in a row at {old['url']}; likely blocked.")
        else:
            signals[rid]["tabelog"] = signal
            save_json(QUALITY_SIGNALS_PATH, signals)  # per venue, so an interrupted run resumes
            consecutive_failures = 0
        print(f"[{count}/{len(ids)}] {rid}", flush=True)
        time.sleep(PAUSE_SECONDS)

    print(f"Done: {len(ids)} venues, {len(unchanged)} unchanged this run")


if __name__ == "__main__":
    main()
