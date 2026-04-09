#!/usr/bin/env python3
"""Retry rejected matches using Claude-searched URL cache first, DDG fallback for misses.

Flow per reject:
  1. Check data/tabelog-url-cache.json for a pre-found Tabelog URL
  2. If found → enrich that specific page → assess match → Groq judge if borderline
  3. If not in cache → fall back to DDG + Yahoo search (existing behaviour)
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

from match_tabelog_candidates import (
    DATA_DIR,
    HTTP_CACHE,
    apply_margin_policy,
    atomic_write_json,
    candidate_sort_key,
    ddg_fallback_queries,
    enrich_candidate,
    external_candidate_score,
    fallback_search_queries,
    fetch_ddg_search_candidates,
    fetch_native_metadata,
    fetch_yahoo_search_candidates,
    groq_judge_match,
    load_http_cache,
    load_records,
    progress_bar,
    save_http_cache,
    tlog,
)
import socket
socket.setdefaulttimeout(10)  # Hard cap — no stalling on dead connections

RESULTS_PATH = DATA_DIR / "tabelog-match-results.json"
CACHE_PATH = DATA_DIR / "tabelog-match-http-cache.json"
URL_CACHE_PATH = DATA_DIR / "tabelog-url-cache.json"
PER_QUERY_LIMIT = 10
ENRICH_TOP_N = 5


def candidate_from_url(url: str) -> dict:
    """Build a minimal candidate dict from a known Tabelog URL."""
    return {
        "url": url,
        "name": "",
        "area_genre": "",
        "score_raw": None,
        "review_count": None,
        "score": 0.0,
        "query": "url_cache",
        "source_queries": ["url_cache"],
        "query_hits": 1,
    }


def ddg_yahoo_search(record: dict, pause: float) -> list[dict]:
    """DDG + Yahoo fallback for restaurants not in the URL cache."""
    aggregate: dict[str, dict] = {}

    def absorb(candidates: list[dict], label: str) -> None:
        for c in candidates[:PER_QUERY_LIMIT]:
            c["score"] = external_candidate_score(record, c, label)
            c["query"] = label
            url = c["url"]
            existing = aggregate.get(url)
            if existing is None or candidate_sort_key(c) > candidate_sort_key(existing):
                aggregate[url] = {**c, "source_queries": [label], "query_hits": 1}

    for query in ddg_fallback_queries(record):
        try:
            absorb(fetch_ddg_search_candidates(query["url"]), query["label"])
        except Exception:
            pass
        time.sleep(pause)

    for query in fallback_search_queries(record):
        try:
            absorb(fetch_yahoo_search_candidates(query["url"]), query["label"])
        except Exception:
            pass
        time.sleep(pause)

    if not aggregate:
        return []

    sorted_cands = sorted(aggregate.values(), key=candidate_sort_key, reverse=True)
    enriched: list[dict] = []
    for c in sorted_cands[:ENRICH_TOP_N]:
        try:
            enriched.append(enrich_candidate(record, c))
        except Exception:
            enriched.append(c)
        time.sleep(pause)

    enriched.sort(key=candidate_sort_key, reverse=True)
    return apply_margin_policy(enriched)


def main() -> None:
    load_http_cache(CACHE_PATH)
    results = json.loads(RESULTS_PATH.read_text())
    all_records = {r["id"]: r for r in load_records()}
    url_cache: dict[str, str | None] = json.loads(URL_CACHE_PATH.read_text()) if URL_CACHE_PATH.exists() else {}

    reject_indices = [
        i for i, r in enumerate(results)
        if (r.get("best_candidates") or [{}])[0].get("match_status") == "reject"
    ]

    cache_hits = sum(1 for i in reject_indices if url_cache.get(results[i]["id"]))
    tlog(f"Found {len(reject_indices)} rejects — {cache_hits} have cached URLs, {len(reject_indices)-cache_hits} need DDG fallback")

    run_start = datetime.datetime.now()
    upgraded = 0
    status_counts: dict[str, int] = {"verified": 0, "review": 0, "reject": 0}
    pause = 0.15

    for count, idx in enumerate(reject_indices, 1):
        r = results[idx]
        record = all_records.get(r["id"])
        if not record:
            status_counts["reject"] += 1
            progress_bar(count, len(reject_indices), run_start, r.get("name", ""), status_counts)
            continue

        # Use native metadata already stored in results — never re-fetch Pocket Concierge
        native_meta = r.get("native_meta") or {}
        record = dict(record)
        native_aliases: list[str] = []
        for alias in [native_meta.get("title_without_reading"), native_meta.get("title")]:
            alias = (alias or "").strip()
            if alias and alias not in native_aliases:
                native_aliases.append(alias)
        record["_native_aliases"] = native_aliases
        record["_native_title"] = native_meta.get("title_without_reading") or native_meta.get("title")
        record["_native_keywords"] = native_meta.get("keywords") or []

        cached_url = url_cache.get(r["id"])
        if cached_url:
            # Cache hit: enrich the specific URL directly
            try:
                candidate = enrich_candidate(record, candidate_from_url(cached_url))
                new_candidates = apply_margin_policy([candidate])
            except Exception:
                new_candidates = []
            time.sleep(pause)
        else:
            # Cache miss: DDG + Yahoo fallback
            new_candidates = ddg_yahoo_search(record, pause)

        # Groq judge for borderline candidates (free at this scale)
        if new_candidates and new_candidates[0].get("match_confidence", 0) < 50:
            groq_pick = groq_judge_match(record, new_candidates[:5])
            if groq_pick:
                new_candidates = sorted(new_candidates, key=candidate_sort_key, reverse=True)

        if new_candidates:
            top = new_candidates[0]
            new_status = top.get("match_status", "reject")
            old_conf = (r.get("best_candidates") or [{}])[0].get("match_confidence", 0)
            new_conf = top.get("match_confidence", 0)

            if new_status in ("verified", "review") or new_conf > old_conf:
                r["best_candidates"] = new_candidates[:5]
                r["queries"] = [{"query": "cached_url_retry" if cached_url else "ddg_yahoo_retry",
                                  "candidates": new_candidates[:5]}]
                if new_status != "reject":
                    upgraded += 1

            status_counts[new_status] = status_counts.get(new_status, 0) + 1
        else:
            status_counts["reject"] += 1

        progress_bar(count, len(reject_indices), run_start, r.get("name", ""), status_counts)

        if count % 10 == 0:
            atomic_write_json(RESULTS_PATH, results)
            save_http_cache(CACHE_PATH)

    sys.stderr.write("\n")
    sys.stderr.flush()

    atomic_write_json(RESULTS_PATH, results)
    save_http_cache(CACHE_PATH)

    tlog(f"Done! Upgraded {upgraded}/{len(reject_indices)} rejects")

    from collections import Counter
    final: Counter = Counter()
    for r in results:
        best = r.get("best_candidates") or []
        s = best[0].get("match_status", "no_candidates") if best else "no_candidates"
        final[s] += 1
    tlog(f"Final: verified={final['verified']}, review={final['review']}, reject={final['reject']}")


if __name__ == "__main__":
    main()
