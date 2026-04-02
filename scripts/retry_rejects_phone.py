#!/usr/bin/env python3
"""Retry rejected Tabelog matches using targeted phone/name search.

Instead of the full 50+ query sweep, this does 3-5 focused searches per
restaurant: phone on Tabelog, native name on Tabelog, phone on DDG.
Much faster than the full search pipeline.
"""

from __future__ import annotations

import json
import shutil
import sys
import datetime
from pathlib import Path

# Reuse everything from the main matcher
from match_tabelog_candidates import (
    DATA_DIR,
    PREFECTURE_SLUGS,
    HTTP_CACHE,
    atomic_write_json,
    canonical_candidate_url,
    candidate_match_assessment,
    candidate_score,
    candidate_sort_key,
    enrich_candidate,
    fetch_detail_metadata,
    fetch_native_metadata,
    fetch_search_candidates,
    fetch_ddg_search_candidates,
    load_http_cache,
    load_records,
    normalize_digits,
    normalize_unicode,
    phone_query_variants,
    save_http_cache,
    apply_margin_policy,
    groq_judge_match,
    progress_bar,
    tlog,
    JP_CHAR_RE,
)
import urllib.parse
import time


RESULTS_PATH = DATA_DIR / "tabelog-match-results.json"
SIGNALS_PATH = DATA_DIR / "restaurant-quality-signals.json"
CACHE_PATH = DATA_DIR / "tabelog-match-http-cache.json"


def targeted_search(record: dict, pause: float) -> list[dict]:
    """Run 3-5 targeted searches for a restaurant and return enriched candidates."""
    prefecture = (record.get("prefecture") or "").strip()
    slug = PREFECTURE_SLUGS.get(prefecture)
    phone = record.get("phone_number") or ""
    phone_variants = phone_query_variants(phone)
    native_title = record.get("_native_title") or ""
    name = record.get("name") or ""

    aggregate: dict[str, dict] = {}
    queries_run = 0

    def add_candidates(candidates: list[dict], label: str) -> None:
        for c in candidates:
            c["score"] = candidate_score(record, c, label)
            c["query"] = label
            url = c["url"]
            if url not in aggregate or candidate_sort_key(c) > candidate_sort_key(aggregate[url]):
                aggregate[url] = {**c, "source_queries": [label], "query_hits": 1}

    # 1. Phone search on Tabelog (most direct signal)
    if slug and phone_variants:
        for pv in phone_variants[:2]:
            url = f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(pv)}"
            try:
                add_candidates(fetch_search_candidates(url), f"phone_search:{pv}")
                queries_run += 1
            except Exception:
                pass
            time.sleep(pause)

        # Also try Japanese Tabelog
        for pv in phone_variants[:1]:
            url = f"https://tabelog.com/{slug}/rstLst/?sk={urllib.parse.quote(pv)}"
            try:
                add_candidates(fetch_search_candidates(url), f"jp_phone_search:{pv}")
                queries_run += 1
            except Exception:
                pass
            time.sleep(pause)

    # 2. Native name search on Tabelog
    if slug and native_title and JP_CHAR_RE.search(native_title):
        url = f"https://tabelog.com/{slug}/rstLst/?sk={urllib.parse.quote(native_title)}"
        try:
            add_candidates(fetch_search_candidates(url), f"jp_name_search:{native_title}")
            queries_run += 1
        except Exception:
            pass
        time.sleep(pause)

    # 3. English name search on Tabelog
    if slug and name:
        url = f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(name)}"
        try:
            add_candidates(fetch_search_candidates(url), f"en_name_search:{name}")
            queries_run += 1
        except Exception:
            pass
        time.sleep(pause)

    # 4. DDG phone search (catches restaurants not in Tabelog search)
    if phone_variants:
        for pv in phone_variants[:1]:
            ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(f'{pv} site:tabelog.com')}"
            try:
                add_candidates(fetch_ddg_search_candidates(ddg_url), f"ddg_phone:{pv}")
                queries_run += 1
            except Exception:
                pass
            time.sleep(pause)

    if not aggregate:
        return []

    # Enrich top candidates with detail pages
    sorted_cands = sorted(aggregate.values(), key=candidate_sort_key, reverse=True)
    enriched: list[dict] = []
    for c in sorted_cands[:5]:
        try:
            enriched.append(enrich_candidate(record, c))
        except Exception:
            enriched.append(c)
        time.sleep(pause)

    enriched.sort(key=candidate_sort_key, reverse=True)
    enriched = apply_margin_policy(enriched)
    return enriched


def honest_stars(score_raw: float) -> float:
    if score_raw >= 4.0: return 5
    if score_raw >= 3.5: return 4.5
    if score_raw >= 3.4: return 4
    if score_raw >= 3.3: return 3.5
    if score_raw >= 3.1: return 3
    if score_raw >= 3.0: return 2
    return 1


def main() -> None:
    load_http_cache(CACHE_PATH)
    results = json.loads(RESULTS_PATH.read_text())
    all_records = {r["id"]: r for r in load_records()}

    # Find rejects
    reject_indices: list[int] = []
    for i, r in enumerate(results):
        best = r.get("best_candidates") or []
        if best and best[0].get("match_status") == "reject":
            reject_indices.append(i)

    tlog(f"Found {len(reject_indices)} rejects to retry with targeted search")

    run_start = datetime.datetime.now()
    upgraded = 0
    status_counts = {"verified": 0, "review": 0, "reject": 0}
    pause = 0.4

    for count, idx in enumerate(reject_indices, 1):
        r = results[idx]
        record = all_records.get(r["id"])
        if not record:
            status_counts["reject"] += 1
            progress_bar(count, len(reject_indices), run_start, r.get("name", ""), status_counts)
            continue

        # Enrich record with native metadata
        native_meta = fetch_native_metadata(record.get("id") or "")
        record = dict(record)
        native_aliases = []
        for alias in [native_meta.get("title_without_reading"), native_meta.get("title")]:
            alias = (alias or "").strip()
            if alias and alias not in native_aliases:
                native_aliases.append(alias)
        record["_native_aliases"] = native_aliases
        record["_native_title"] = native_meta.get("title_without_reading") or native_meta.get("title")
        record["_native_keywords"] = native_meta.get("keywords") or []

        new_candidates = targeted_search(record, pause)

        if new_candidates:
            top = new_candidates[0]
            new_status = top.get("match_status", "reject")
            old_conf = (r.get("best_candidates") or [{}])[0].get("match_confidence", 0)
            new_conf = top.get("match_confidence", 0)

            if new_status in ("verified", "review") or new_conf > old_conf:
                # Update results with better match
                r["best_candidates"] = new_candidates[:5]
                r["queries"] = [{"query": "targeted_retry", "candidates": new_candidates[:5]}]
                if new_status != "reject":
                    upgraded += 1

            status_counts[new_status] = status_counts.get(new_status, 0) + 1
        else:
            status_counts["reject"] += 1

        progress_bar(count, len(reject_indices), run_start, r.get("name", ""), status_counts)

        # Save periodically
        if count % 10 == 0:
            atomic_write_json(RESULTS_PATH, results)
            save_http_cache(CACHE_PATH)

    sys.stderr.write("\n")
    sys.stderr.flush()

    # Final save
    atomic_write_json(RESULTS_PATH, results)
    save_http_cache(CACHE_PATH)

    tlog(f"Done! Upgraded {upgraded}/{len(reject_indices)} rejects")

    # Print final status breakdown
    from collections import Counter
    final = Counter()
    for r in results:
        best = r.get("best_candidates") or []
        s = best[0].get("match_status", "no_candidates") if best else "no_candidates"
        final[s] += 1
    tlog(f"Final: verified={final['verified']}, review={final['review']}, reject={final['reject']}")


if __name__ == "__main__":
    main()
