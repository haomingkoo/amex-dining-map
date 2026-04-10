#!/usr/bin/env python3
"""
Enrich restaurant datasets with Google Maps ratings using Playwright.

Extracts: rating, review_count (when available), google_name, google_address, maps_url

Covers:
  - data/global-restaurants.json   (Global Dining Credit, ~2470 records)
  - data/japan-restaurants.json    (Pocket Concierge Japan, ~844 records)
  - data/love-dining.json          (Love Dining SG, 79 records)

Usage:
    # Full run
    python3 scripts/scrape_google_ratings_playwright.py

    # Specific datasets
    python3 scripts/scrape_google_ratings_playwright.py --datasets love japan

    # Only missing records
    python3 scripts/scrape_google_ratings_playwright.py --missing-only

    # Concurrency (default 3; higher = more bot risk)
    python3 scripts/scrape_google_ratings_playwright.py --concurrency 3

    # Dry run — print queries without scraping
    python3 scripts/scrape_google_ratings_playwright.py --dry-run

Requirements:
    pip install playwright
    playwright install chromium

Output:
    data/google-maps-ratings.json  — {id: {rating, review_count, google_name, google_address, maps_url}}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
RATINGS_PATH = DATA_DIR / "google-maps-ratings.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ─── Query generation ─────────────────────────────────────────────────────────

def make_query(record: dict, dataset: str) -> str:
    name = record.get("name", "")
    if dataset == "japan":
        city = record.get("city", "")
        prefecture = record.get("prefecture", "")
        loc = city or prefecture or "Japan"
        return f"{name} {loc} Japan"
    if dataset == "love":
        hotel = record.get("hotel", "")
        address = record.get("address", "")
        addr_short = re.split(r"Singapore \d{6}", address)[0].strip().rstrip(",")
        if hotel:
            return f"{name} {hotel} Singapore"
        return f"{name} {addr_short} Singapore" if addr_short else f"{name} Singapore"
    country = record.get("country", "")
    city = record.get("city", "")
    loc = f"{city}, {country}" if city and city != country else country
    return f"{name} {loc}"


def build_queries(records: list[dict], dataset: str, skip_ids: set[str]) -> list[tuple[str, str]]:
    """Return [(query, record_id), ...]."""
    pairs = []
    for rec in records:
        rid = rec.get("id", "")
        if not rid or rid in skip_ids:
            continue
        pairs.append((make_query(rec, dataset), rid))
    return pairs


# ─── Dataset loaders ──────────────────────────────────────────────────────────

def load_datasets(names: list[str]) -> dict[str, list[dict]]:
    datasets: dict[str, list[dict]] = {}
    mapping = {
        "global": DATA_DIR / "global-restaurants.json",
        "japan":  DATA_DIR / "japan-restaurants.json",
        "love":   DATA_DIR / "love-dining.json",
    }
    for name in names:
        path = mapping.get(name)
        if path and path.exists():
            datasets[name] = json.loads(path.read_text())
            print(f"  {name}: {len(datasets[name])} records")
        else:
            print(f"  {name}: file not found, skipping")
    return datasets


# ─── Playwright scraper ────────────────────────────────────────────────────────

async def scrape_one(page, query: str, rid: str) -> dict | None:
    """Scrape Google Maps for a single query. Returns result dict or None."""
    search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    try:
        await page.goto(search_url, wait_until="commit", timeout=30000)
        # Wait for place card rating to appear
        try:
            await page.wait_for_selector('span[aria-hidden="true"]', timeout=12000)
        except Exception:
            pass
        await asyncio.sleep(3)

        # If still on search results page (not redirected to place), click the first result
        current_url = page.url
        if "/search/" in current_url and "/place/" not in current_url:
            try:
                # Click the first result link (usually an <a> with href containing /maps/place/)
                first_place = await page.query_selector('a[href*="/maps/place/"]')
                if first_place:
                    await first_place.click()
                    await asyncio.sleep(3)
                    current_url = page.url
            except Exception:
                pass

        maps_url = current_url if "google.com/maps" in current_url else None

        # Extract via JS evaluation
        data = await page.evaluate("""() => {
            let rating = null;
            let reviewCount = null;
            let name = null;
            let address = null;

            // Rating: standalone X.Y spans
            const spans = document.querySelectorAll('span');
            for (const s of spans) {
                const t = s.textContent.trim();
                if (/^[1-5][.][0-9]$/.test(t)) { rating = t; break; }
            }

            // Review count: check aria-labels first (most reliable)
            for (const el of document.querySelectorAll('[aria-label]')) {
                const lbl = el.getAttribute('aria-label') || '';
                // "4.5 stars, 320 reviews"
                const m2 = lbl.match(/([1-5][.][0-9]).*?([0-9][0-9,]*)\\s*review/i);
                if (m2) { rating = m2[1]; reviewCount = m2[2].replace(/,/g, ''); break; }
                // just "320 reviews"
                const m = lbl.match(/^([0-9][0-9,]*)\\s*(?:Google\\s+)?reviews?$/i);
                if (m) { reviewCount = m[1].replace(/,/g, ''); break; }
            }

            // Fallback: body text pattern "N reviews" or "N Google reviews"
            if (!reviewCount) {
                const bodyText = document.body.innerText;
                const countMatch = bodyText.match(/([1-9][0-9,]{1,6})\\s*(?:Google\\s+)?reviews?/i);
                if (countMatch) reviewCount = countMatch[1].replace(/,/g, '');
            }

            // Name: first h1 in sidebar
            const h1 = document.querySelector('h1');
            if (h1) name = h1.textContent.trim();

            // Address: button with a digit (usually the address button)
            for (const btn of document.querySelectorAll('button')) {
                const t = btn.textContent.trim();
                if (t.length > 10 && /\\d/.test(t) && !/^[0-9]/.test(t)) {
                    address = t; break;
                }
            }

            return { rating, reviewCount, name, address };
        }""")

        rating = data.get("rating")
        if rating is None:
            return None  # No useful data

        review_count_raw = data.get("reviewCount")
        raw_address = data.get("address") or ""
        # Strip Google Maps private-use navigation marker (\ue0c8)
        clean_address = re.sub(r"[\ue0c0-\ue0ff]", "", raw_address).strip() or None

        return {
            "rating": float(rating),
            "review_count": int(review_count_raw) if review_count_raw else None,
            "google_name": data.get("name"),
            "google_address": clean_address,
            "maps_url": maps_url,
            "scraped_at": time.strftime("%Y-%m-%d"),
        }

    except Exception as exc:
        print(f"    ✗ {rid}: {exc}")
        return None


async def worker(
    browser_factory,
    queue: asyncio.Queue,
    results: dict[str, dict],
    worker_id: int,
    rate_limit_delay: float,
) -> None:
    """Worker coroutine: process items from queue using its own browser page."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await ctx.new_page()

        while True:
            try:
                query, rid = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            result = await scrape_one(page, query, rid)
            if result:
                results[rid] = result
                print(f"  [{worker_id}] ✓ {rid}: {result['rating']} ({result['review_count']} reviews)")
            else:
                print(f"  [{worker_id}] – {rid}: no data")

            queue.task_done()
            await asyncio.sleep(rate_limit_delay)

        await browser.close()


async def run_scraper(
    queries: list[tuple[str, str]],
    concurrency: int,
    existing: dict[str, dict],
    batch_size: int,
) -> dict[str, dict]:
    """Run the full scrape and return merged ratings dict."""
    new_ratings: dict[str, dict] = {}

    # Process in batches
    batches = [queries[i:i+batch_size] for i in range(0, len(queries), batch_size)]
    print(f"\nProcessing {len(batches)} batch(es) of up to {batch_size}...")

    for batch_num, batch in enumerate(batches, 1):
        print(f"\n─── Batch {batch_num}/{len(batches)} ({len(batch)} queries) ───")
        q: asyncio.Queue = asyncio.Queue()
        for item in batch:
            q.put_nowait(item)

        batch_results: dict[str, dict] = {}
        # Each worker gets its own async_playwright context (they can't share easily)
        # Use concurrency workers, each with their own browser
        delay = max(1.0, 3.0 / concurrency)  # spread requests
        workers = [
            asyncio.create_task(
                worker(None, q, batch_results, i + 1, delay)
            )
            for i in range(min(concurrency, len(batch)))
        ]
        await asyncio.gather(*workers)

        new_ratings.update(batch_results)
        print(f"  Batch {batch_num}: matched {len(batch_results)}/{len(batch)}")

        # Reload file before saving to avoid overwriting concurrent runs
        current_on_disk: dict[str, dict] = {}
        if RATINGS_PATH.exists():
            try:
                current_on_disk = json.loads(RATINGS_PATH.read_text())
            except json.JSONDecodeError:
                pass
        merged = {**current_on_disk, **new_ratings}
        RATINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        print(f"  Saved {len(merged)} total → {RATINGS_PATH}")

    # Final merge from disk
    final_on_disk: dict[str, dict] = {}
    if RATINGS_PATH.exists():
        try:
            final_on_disk = json.loads(RATINGS_PATH.read_text())
        except json.JSONDecodeError:
            final_on_disk = {}
    return {**final_on_disk, **new_ratings}


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Google Maps ratings with Playwright")
    p.add_argument("--datasets", nargs="+", default=["global", "japan", "love"],
                   choices=["global", "japan", "love"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--missing-only", action="store_true",
                   help="Skip records already in ratings cache")
    p.add_argument("--concurrency", type=int, default=3,
                   help="Parallel browser instances (default: 3)")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Queries per batch before saving (default: 100)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    existing: dict[str, dict] = {}
    if RATINGS_PATH.exists():
        existing = json.loads(RATINGS_PATH.read_text())
        print(f"Existing cache: {len(existing)} records")

    skip_ids = set(existing.keys()) if args.missing_only else set()

    print(f"\nLoading datasets: {args.datasets}")
    datasets = load_datasets(args.datasets)
    if not datasets:
        print("No datasets loaded.")
        sys.exit(1)

    all_queries: list[tuple[str, str]] = []
    for name, records in datasets.items():
        pairs = build_queries(records, name, skip_ids)
        print(f"  {name}: {len(pairs)} queries (of {len(records)} records)")
        all_queries.extend(pairs)

    print(f"\nTotal queries: {len(all_queries)}")
    if not all_queries:
        print("Nothing to scrape.")
        return

    if args.dry_run:
        for q, rid in all_queries[:20]:
            print(f"  {rid}: {q}")
        if len(all_queries) > 20:
            print(f"  ... and {len(all_queries) - 20} more")
        return

    merged = asyncio.run(run_scraper(all_queries, args.concurrency, existing, args.batch_size))

    added = len(merged) - len(existing)
    print(f"\nDone. Added {added} new ratings. Total: {len(merged)}")
    print(f"Output → {RATINGS_PATH}")


if __name__ == "__main__":
    main()
