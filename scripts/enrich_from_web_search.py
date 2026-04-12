#!/usr/bin/env python3
"""
Enrich global restaurants with Michelin Guide descriptions via the Michelin Algolia API.

The Michelin Guide website uses Algolia's public search index (prod-restaurants-en).
This script queries that index directly — no browser automation required.

Cache behaviour:
  - Successful results (michelin / no_result) are cached indefinitely.
  - "no_result" entries expire after NO_RESULT_TTL_DAYS (default 90) and are retried.
  - "error" entries are always retried.
  - Pass --force to re-fetch everything regardless.

Output fields added to external_signals in global-restaurants.json:
  web_search_description         — Michelin inspector's description
  web_search_description_source  — "michelin"
  web_search_url                 — Full guide.michelin.com URL

Usage:
  python3 scripts/enrich_from_web_search.py              # missing / expired only
  python3 scripts/enrich_from_web_search.py --force      # re-fetch everything
  python3 scripts/enrich_from_web_search.py --limit 50   # test run
  python3 scripts/enrich_from_web_search.py --country Australia
  python3 scripts/enrich_from_web_search.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GLOBAL_PATH = DATA_DIR / "global-restaurants.json"
CACHE_PATH = DATA_DIR / "web-search-signals-cache.json"

ALGOLIA_INDEX = "prod-restaurants-en"

# no_result entries older than this many days are retried on the next run
NO_RESULT_TTL_DAYS = 90

# Minimum word count for a description to be worth storing
MIN_WORDS = 15


def load_algolia_credentials() -> tuple[str, str]:
    """Load Algolia app ID and API key from .env or environment variables.

    These are the Michelin Guide's public read-only search credentials, visible in
    any browser's Network tab when visiting guide.michelin.com. Store them in .env as
    MICHELIN_ALGOLIA_APP_ID and MICHELIN_ALGOLIA_API_KEY.
    """
    import os
    app_id = os.environ.get("MICHELIN_ALGOLIA_APP_ID", "")
    api_key = os.environ.get("MICHELIN_ALGOLIA_API_KEY", "")

    if not app_id or not api_key:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("MICHELIN_ALGOLIA_APP_ID="):
                    app_id = line.split("=", 1)[1].strip().strip("\"'")
                elif line.startswith("MICHELIN_ALGOLIA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip("\"'")

    if not app_id or not api_key:
        print("ERROR: MICHELIN_ALGOLIA_APP_ID and MICHELIN_ALGOLIA_API_KEY not found.")
        print("Add them to .env — obtain by inspecting network requests on guide.michelin.com.")
        sys.exit(1)

    return app_id, api_key


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def compact_space(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def strip_html(text: str) -> str:
    """Remove HTML tags, decode common entities, and strip Michelin status prefixes."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'").replace("&quot;", '"').replace("&#39;", "'")
    text = compact_space(text)
    # Strip "Note: Temporarily closed" and similar Michelin status prefixes
    text = re.sub(r"^Note:\s*[^.!?]+[.!?]?\s*", "", text, flags=re.IGNORECASE).strip()
    return text


_NAME_STOPWORDS = frozenset({
    # Generic English words
    "the", "a", "an", "at", "in", "of", "and", "by",
    # Generic restaurant type words — not useful for identity matching
    "restaurant", "restaurants", "bar", "bars", "cafe", "bistro",
    "grill", "grille", "kitchen", "house", "room", "dining",
    "brasserie", "taverna", "tavern", "trattoria", "osteria",
    # Common foreign equivalents
    "la", "le", "les", "de", "du", "des", "el", "los", "las",
    "das", "die", "der", "il", "lo", "gli",
})


def name_overlap_score(a: str, b: str) -> float:
    """
    Fraction of meaningful tokens in `a` that also appear in `b` (case-insensitive).
    Generic restaurant-type words (restaurant, bar, grill, …) are excluded so that
    e.g. "Restaurant Born" doesn't falsely match "Sin Huat Seafood Restaurant".
    """
    tokens_a = set(re.findall(r"[a-z0-9]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not tokens_a:
        return 0.0
    tokens_a -= _NAME_STOPWORDS
    tokens_b -= _NAME_STOPWORDS
    if not tokens_a:
        # All tokens were stopwords — fall back to exact match
        return 1.0 if a.lower().strip() == b.lower().strip() else 0.0
    shared = tokens_a & tokens_b
    return len(shared) / len(tokens_a)


def is_primarily_english(text: str) -> bool:
    if not text:
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii / max(len(text), 1) >= 0.2:
        return False
    words = re.findall(r"\b[a-z]+\b", text.lower())
    if len(words) >= 8:
        stopwords = {"the", "is", "in", "of", "and", "for", "at", "by", "with",
                     "an", "a", "it", "this", "that", "from", "or", "are", "has",
                     "have", "its", "as", "on", "to", "be", "was", "were", "not"}
        hits = sum(1 for w in words if w in stopwords)
        if hits < len(words) / 8:
            return False
    return True


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    """Merge-write: reload from disk first to avoid overwriting concurrent updates."""
    on_disk: dict[str, Any] = {}
    if CACHE_PATH.exists():
        try:
            on_disk = json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    on_disk.update(cache)
    CACHE_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False) + "\n")


def cache_is_fresh(entry: dict[str, Any]) -> bool:
    """Return True if the cache entry does not need to be retried."""
    source = entry.get("source", "")
    if source == "error":
        return False  # always retry errors
    if source == "michelin":
        return True   # successful finds are kept forever
    if source == "no_result":
        # Retry after NO_RESULT_TTL_DAYS
        searched_at = entry.get("searched_at", "")
        try:
            d = date.fromisoformat(searched_at)
            return date.today() - d < timedelta(days=NO_RESULT_TTL_DAYS)
        except (ValueError, TypeError):
            return False  # bad date → retry
    return False  # unknown source → retry


# ---------------------------------------------------------------------------
# Algolia search
# ---------------------------------------------------------------------------

def algolia_search(query: str, app_id: str, api_key: str, limit: int = 3) -> list[dict]:
    """Query Michelin's public Algolia index. Returns raw hits."""
    algolia_url = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
    body = json.dumps({
        "requests": [{
            "indexName": ALGOLIA_INDEX,
            "query": query,
            "hitsPerPage": limit,
            "attributesToRetrieve": [
                "name", "city", "country", "cuisines",
                "main_desc", "url", "chef", "region",
            ],
            "highlightPreTag": "",
            "highlightPostTag": "",
        }]
    }).encode()

    req = urllib.request.Request(
        algolia_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Algolia-API-Key": api_key,
            "X-Algolia-Application-Id": app_id,
            "Referer": "https://guide.michelin.com/",
            "Origin": "https://guide.michelin.com",
            "User-Agent": "Mozilla/5.0 (compatible; amex-dining-map/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("results", [{}])[0].get("hits", [])


def city_name(hit: dict) -> str:
    city = hit.get("city") or {}
    if isinstance(city, dict):
        return city.get("name") or ""
    return str(city)


def country_name(hit: dict) -> str:
    country = hit.get("country") or {}
    if isinstance(country, dict):
        return country.get("name") or ""
    return str(country)


def country_cname(hit: dict) -> str:
    """Return Algolia's URL-slug form of the country, e.g. 'united-states'."""
    country = hit.get("country") or {}
    if isinstance(country, dict):
        return country.get("cname") or ""
    return ""


def build_michelin_url(hit: dict) -> str:
    raw_url = (hit.get("url") or "").lstrip("/")
    if raw_url:
        return f"https://guide.michelin.com/{raw_url}"
    return ""


def find_michelin_match(
    hits: list[dict],
    target_name: str,
    target_country: str,
) -> dict | None:
    """
    Return the best Algolia hit that plausibly matches target_name + target_country.

    Match criteria:
    1. Country must match: either string contains the other, or any 4-char token from
       target_country appears in hit_country (handles "United Kingdom" ↔ "UK" etc.)
       The check is one-directional: we look for evidence the hit IS in the target country.
    2. Restaurant name tokens must have at least 0.5 overlap with target name tokens.
    """
    if not hits:
        return None

    target_country_lower = target_country.lower()
    target_name_lower = target_name.lower()

    # Normalize target_country to Algolia cname format: "United States" → "united-states"
    target_cname = re.sub(r"\s+", "-", target_country_lower)

    for hit in hits:
        hit_country = country_name(hit).lower()
        hit_cname = country_cname(hit).lower()
        hit_name = hit.get("name", "").strip().lower()

        # Country must match — multiple strategies to handle name variants:
        # e.g. "USA" (Algolia) vs "United States" (our data),
        #      "Hong Kong" vs "Hong Kong SAR", etc.
        long_toks = [t for t in re.findall(r"[a-z]+", target_country_lower) if len(t) >= 4]
        country_ok = (
            hit_country in target_country_lower           # "singapore" in "singapore"
            or target_country_lower in hit_country        # "hong kong" in "hong kong sar"
            or hit_cname == target_cname                  # "united-states" == "united-states"
            or (hit_cname and hit_cname in target_cname)  # "hong-kong" in "hong-kong-sar"
            # ALL long tokens must match — prevents "united" matching both US and UK
            or (bool(long_toks) and all(tok in hit_country for tok in long_toks))
        )
        if not country_ok:
            continue

        # Name must overlap meaningfully — threshold 0.6 requires >half of meaningful tokens
        overlap = name_overlap_score(target_name_lower, hit_name)
        if overlap >= 0.6:
            return hit

    return None


def enrich_restaurant(record: dict, app_id: str, api_key: str) -> dict[str, Any]:
    """Query Michelin Algolia for a single restaurant. Return a cache-entry dict."""
    name = compact_space(record.get("name"))
    city = compact_space(record.get("city") or record.get("region") or "")
    country = compact_space(record.get("country") or "")
    today = date.today().isoformat()

    base: dict[str, Any] = {
        "name": name,
        "country": country,
        "searched_at": today,
        "description": None,
        "source": "no_result",
        "url": None,
    }

    if not name:
        base["source"] = "error"
        base["error"] = "missing name"
        return base

    # Try "[name] [city]" then just "[name] [country]" as fallback
    queries = [f"{name} {city}", f"{name} {country}"]
    if not city:
        queries = [f"{name} {country}"]

    for query in queries:
        try:
            hits = algolia_search(query.strip(), app_id, api_key)
        except urllib.error.HTTPError as exc:
            base["source"] = "error"
            base["error"] = f"HTTP {exc.code}: {str(exc)[:100]}"
            return base
        except Exception as exc:
            base["source"] = "error"
            base["error"] = str(exc)[:200]
            return base

        hit = find_michelin_match(hits, name, country)
        if hit:
            raw_desc = hit.get("main_desc") or ""
            desc = strip_html(raw_desc)
            if len(desc.split()) >= MIN_WORDS and is_primarily_english(desc):
                url = build_michelin_url(hit)
                base["description"] = desc
                base["source"] = "michelin"
                base["url"] = url
                return base

    return base  # no_result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="Only process restaurants from this country")
    parser.add_argument("--limit", type=int, default=0, help="Max restaurants to process")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached and fresh")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed, no fetching")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Seconds between Algolia requests (default: 0.3)")
    args = parser.parse_args()

    app_id, api_key = load_algolia_credentials()

    data = json.loads(GLOBAL_PATH.read_text())
    cache = load_cache()

    # Build deduplicated work list — same (name, country) → one Algolia call, fan out
    def norm(s: str | None) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    seen_ids: set[str] = set()
    seen_nc: set[tuple[str, str]] = set()
    todo: list[dict] = []

    for record in data:
        if args.country and record.get("country") != args.country:
            continue
        rid = record["id"]
        if rid in seen_ids:
            continue
        seen_ids.add(rid)

        nc = (norm(record.get("name")), norm(record.get("country")))
        if nc in seen_nc:
            continue

        cached = cache.get(rid, {})
        if not args.force and cache_is_fresh(cached):
            continue

        seen_nc.add(nc)
        todo.append(record)

    uncached = len(todo)
    if args.limit:
        todo = todo[:args.limit]

    already_cached = len(seen_ids) - uncached
    print(f"Total unique restaurants: {len(seen_ids)}")
    print(f"Already cached / fresh:   {already_cached}")
    print(f"Needs processing:         {uncached}{f' (limited to {args.limit})' if args.limit else ''}")

    if not todo:
        print("Nothing to do.")
    elif args.dry_run:
        for r in todo[:20]:
            print(f"  DRY: {r['name']} ({r.get('country')})")
        if len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return
    else:
        local_cache: dict[str, Any] = {}
        found = 0
        for i, record in enumerate(todo, 1):
            try:
                result = enrich_restaurant(record, app_id, api_key)
            except Exception as exc:
                result = {
                    "searched_at": date.today().isoformat(),
                    "source": "error",
                    "error": str(exc)[:200],
                }

            rid = record["id"]
            local_cache[rid] = result

            # Fan-out: write same result for all records with matching (name, country)
            rec_nc = (norm(record.get("name")), norm(record.get("country")))
            for other in data:
                if other["id"] == rid:
                    continue
                other_nc = (norm(other.get("name")), norm(other.get("country")))
                if other_nc == rec_nc:
                    local_cache[other["id"]] = result

            if result["source"] == "michelin":
                found += 1
                print(f"  [{i}/{len(todo)}] ✓ {record['name']} ({record.get('country')}): "
                      f"{(result.get('description') or '')[:70]}...")
            elif result["source"] == "error":
                print(f"  [{i}/{len(todo)}] ✗ {record['name']}: {result.get('error', '')}")
            else:
                if i % 50 == 0:
                    print(f"  [{i}/{len(todo)}] – {record['name']} ({record.get('country')}): no result")

            # Incremental save every 50 records
            if i % 50 == 0 or i == len(todo):
                save_cache(local_cache)

            time.sleep(args.delay)

        save_cache(local_cache)
        cache.update(local_cache)
        print(f"\nDone. Processed {len(local_cache)} unique name/country pairs.")
        print(f"Michelin matches found: {found}")

    # Apply cache to global-restaurants.json
    print("\nApplying results to global-restaurants.json...")
    updated = 0
    for record in data:
        rid = record["id"]
        entry = cache.get(rid, {})
        desc = entry.get("description")
        source = entry.get("source")
        url = entry.get("url")

        signals = dict(record.get("external_signals") or {})

        if desc and source == "michelin":
            signals["web_search_description"] = desc
            signals["web_search_description_source"] = source
            signals["web_search_url"] = url or ""
            updated += 1
        elif args.force:
            # Clean up stale fields when force-re-running
            signals.pop("web_search_description", None)
            signals.pop("web_search_description_source", None)
            signals.pop("web_search_url", None)

        record["external_signals"] = signals

    GLOBAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Updated {updated} restaurant records with Michelin descriptions.")
    print(f"Output → {GLOBAL_PATH}")
    print(f"Cache  → {CACHE_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
