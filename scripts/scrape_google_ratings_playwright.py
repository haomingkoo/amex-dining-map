#!/usr/bin/env python3
"""
Enrich restaurant datasets with Google Maps ratings using Playwright.

Extracts: rating, review_count (when available), google_name, google_address, maps_url

Covers:
  - data/global-restaurants.json   (Global Dining Credit, ~2470 records)
  - data/japan-restaurants.json    (Pocket Concierge Japan, ~844 records)
  - data/love-dining.json          (Love Dining SG, 78 records)
  - data/table-for-two.json        (Table for Two SG current and historical records)
  - data/plat-stays.json           (Plat Stay hotels, 69 records)

Usage:
    # Full run
    python3 scripts/scrape_google_ratings_playwright.py

    # Specific datasets
    python3 scripts/scrape_google_ratings_playwright.py --datasets love japan stays tft

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
    data/google-maps-ratings.json  — {id: {rating, review_count, status, google_name, google_address, maps_url}}
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
RATINGS_PATH = DATA_DIR / "google-maps-ratings.json"
PAGE_LOAD_TIMEOUT_MS = 30_000
RATING_SELECTOR_TIMEOUT_MS = 12_000
PLACE_CARD_SETTLE_SECONDS = 3
# A result further than this from the record's pin is a different place.
MAX_MATCH_DISTANCE_KM = 2.0
# Closing a venue hides its rating, so the closed place must sit on the pin.
MAX_CLOSED_DISTANCE_KM = 0.5

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ─── Query generation ─────────────────────────────────────────────────────────

def make_target(record: dict, dataset: str) -> str:
    name = record.get("name", "")
    source_map = record.get("source_google_map_url")
    if dataset == "global" and source_map:
        return source_map
    if dataset == "japan":
        city = record.get("city", "")
        prefecture = record.get("prefecture", "")
        loc = city or prefecture or "Japan"
        district = record.get("district", "")
        return f"{name} {district} {loc} Japan" if district else f"{name} {loc} Japan"
    if dataset == "love":
        hotel = record.get("hotel", "")
        address = record.get("address", "")
        addr_short = re.split(r"Singapore \d{6}", address)[0].strip().rstrip(",")
        if hotel:
            return f"{name} {hotel} Singapore"
        return f"{name} {addr_short} Singapore" if addr_short else f"{name} Singapore"
    if dataset == "tft":
        display_name = record.get("dining_city_name") or name
        address = record.get("address", "")
        addr_short = re.split(r"Singapore \d{6}", address)[0].strip().rstrip(",")
        return f"{display_name} {addr_short} Singapore" if addr_short else f"{display_name} Singapore"
    if dataset == "stays":
        # For hotels, use simple query first (name + country only)
        # This avoids long addresses that may cause timeouts or mismatches
        country = record.get("country", "")
        return f"{name} {country}".strip()
    address = record.get("source_localized_address", "")
    if address:
        return f"{name} {address}"
    country = record.get("country", "")
    city = record.get("city", "")
    loc = f"{city}, {country}" if city and city != country else country
    return f"{name} {loc}"


def text_query(record: dict) -> str:
    name = record.get("name", "")
    city = record.get("city", "")
    country = record.get("country", "")
    loc = f"{city} {country}" if city and city != country else country
    return f"{name} {loc}".strip()


def candidate_targets(record: dict, dataset: str) -> list[str]:
    """Targets to try in order. Source map links rot, so global records fall back to a text query."""
    if dataset != "global" or not record.get("source_google_map_url"):
        return [make_target(record, dataset)]
    source_map = record["source_google_map_url"]
    # g.page links redirect through Google Search, which serves a bot check.
    if "//g.page/" in source_map:
        return [text_query(record)]
    return [source_map, text_query(record)]


def classify_maps_url(url: str | None) -> str:
    url = url or ""
    if "google.com/sorry/" in url:
        return "blocked"
    if "/maps/dir/" in url:
        return "directions"
    if "/maps/place//" in url:
        return "empty_place"
    if "/maps/place/" in url:
        return "place"
    if "/maps/search/" in url:
        return "search"
    return "other"


def parse_place_coords(url: str | None) -> tuple[float, float] | None:
    """The place pin from a Maps URL. Search and empty-place viewports are not a place."""
    pins = re.findall(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url or "")
    if pins:
        return float(pins[-1][0]), float(pins[-1][1])
    if classify_maps_url(url) != "place":
        return None
    viewport = re.search(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url or "")
    return (float(viewport.group(1)), float(viewport.group(2))) if viewport else None


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def match_problem(result: dict, record: dict) -> str | None:
    """Why a scraped place is not this record, or None when it matches or cannot be checked."""
    if record.get("lat") is None or record.get("lng") is None:
        return None
    place = parse_place_coords(result.get("maps_url"))
    if place is None:
        return f"no place coordinates in {classify_maps_url(result.get('maps_url'))} URL"
    km = distance_km(place, (float(record["lat"]), float(record["lng"])))
    if result.get("status") == "permanently_closed" and km > MAX_CLOSED_DISTANCE_KM:
        return f"closed place is {km:.1f} km from the record (max {MAX_CLOSED_DISTANCE_KM} km)"
    if km > MAX_MATCH_DISTANCE_KM:
        return f"place is {km:.1f} km from the record (max {MAX_MATCH_DISTANCE_KM} km)"
    return None


def page_status(url_kind: str, panel_text: str) -> str | None:
    if url_kind == "place" and "Permanently closed" in panel_text:
        return "permanently_closed"
    return None


def oldest_first(pairs: list[tuple], existing: dict) -> list[tuple]:
    """Never-scraped records first, then the oldest ratings, so a query budget rotates fairly."""
    return sorted(pairs, key=lambda pair: str((existing.get(pair[1].get("id")) or {}).get("scraped_at") or ""))


def build_queries(records: list[dict], dataset: str, skip_ids: set[str]) -> list[tuple[list[str], dict]]:
    """Return [(targets, record), ...]."""
    pairs = []
    for rec in records:
        rid = rec.get("id", "")
        if not rid or rid in skip_ids:
            continue
        pairs.append((candidate_targets(rec, dataset), rec))
    return pairs


# ─── Dataset loaders ──────────────────────────────────────────────────────────

def load_datasets(names: list[str]) -> dict[str, list[dict]]:
    datasets: dict[str, list[dict]] = {}
    mapping = {
        "global": DATA_DIR / "global-restaurants.json",
        "japan":  DATA_DIR / "japan-restaurants.json",
        "love":   DATA_DIR / "love-dining.json",
        "tft":    DATA_DIR / "table-for-two.json",
        "stays":  DATA_DIR / "plat-stays.json",
    }
    for name in names:
        path = mapping.get(name)
        if path and path.exists():
            payload = json.loads(path.read_text())
            datasets[name] = payload.get("venues", []) if name == "tft" and isinstance(payload, dict) else payload
            print(f"  {name}: {len(datasets[name])} records")
        else:
            print(f"  {name}: file not found, skipping")
    return datasets


# ─── Playwright scraper ────────────────────────────────────────────────────────

async def scrape_one(page, target: str, rid: str) -> dict | None:
    """Scrape Google Maps for a single query or direct map target. Returns result dict or None."""
    if target.startswith("http://") or target.startswith("https://"):
        search_url = target
    else:
        search_url = f"https://www.google.com/maps/search/{target.replace(' ', '+')}"
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    try:
        await page.goto(search_url, wait_until="commit", timeout=PAGE_LOAD_TIMEOUT_MS)
        # A missing rating span is expected for search-result pages; extraction below decides.
        try:
            await page.wait_for_selector('span[aria-hidden="true"]', timeout=RATING_SELECTOR_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            print(f"    {rid}: no rating span after {RATING_SELECTOR_TIMEOUT_MS}ms, continuing")
        await asyncio.sleep(PLACE_CARD_SETTLE_SECONDS)

        # Hotel cards often spend a few more seconds on a transient /search/ URL
        # before resolving to the real place page.
        current_url = page.url
        for _ in range(3):
            if "/place/" in current_url:
                break
            await asyncio.sleep(2)
            current_url = page.url

        # If still on search results page (not redirected to place), click the first result.
        if "/search/" in current_url and "/place/" not in current_url:
            try:
                # Click the first result link (usually an <a> with href containing /maps/place/)
                first_place = await page.query_selector('a[href*="/maps/place/"]')
                if first_place:
                    await first_place.click()
                    # Wait for place page to fully load (h1 should change from "Results")
                    for _ in range(5):
                        await asyncio.sleep(1)
                        h1_text = await page.evaluate("document.querySelector('h1')?.textContent.trim() || ''")
                        if h1_text and h1_text.lower() != "results":
                            break
                    current_url = page.url
            except PlaywrightError as exc:
                print(f"    WARNING {rid}: could not open first search result: {exc}")

        maps_url = current_url if "google.com/maps" in current_url else None

        # Extract via JS evaluation
        data = await page.evaluate("""() => {
            let rating = null;
            let reviewCount = null;
            let name = null;
            let address = null;
            const h1Text = (document.querySelector('h1')?.textContent || '').trim();
            const panels = [...document.querySelectorAll('div[role="main"]')];
            const panel = panels.find(el => el.getAttribute('aria-label') === h1Text) || panels[0];
            const panelText = panel?.innerText || '';

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

            const addressSelectors = [
                'button[data-item-id="address"]',
                '[data-item-id="address"] button',
                'button[aria-label^="Address:"]',
            ];
            for (const selector of addressSelectors) {
                const el = document.querySelector(selector);
                const t = (el?.textContent || '').trim();
                if (t) {
                    address = t;
                    break;
                }
            }

            // Fallback: button text with digits, excluding hotel price/date widgets.
            if (!address) {
                for (const btn of document.querySelectorAll('button')) {
                    const t = btn.textContent.trim();
                    if (!t) continue;
                    if (t.startsWith('$')) continue;
                    if (/\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\\b/i.test(t)) continue;
                    if (t.length > 10 && /\\d/.test(t) && !/^[0-9]/.test(t)) {
                        address = t;
                        break;
                    }
                }
            }

            return { rating, reviewCount, name, address, panelText };
        }""")

        rating = data.get("rating")
        google_name = (data.get("name") or "").strip()
        url_kind = classify_maps_url(page.url)
        status = page_status(url_kind, data.get("panelText") or "")
        if status:
            rating = None

        # Accept result if we have a rating, even if still on search results page
        # (where name might be "Results"). Search results can show valid ratings.
        if rating is None and status is None:
            print(f"    {rid}: no rating on {url_kind} page url={page.url} h1={google_name!r}")
            return None

        review_count_raw = data.get("reviewCount")
        raw_address = data.get("address") or ""
        # Strip Google Maps private-use navigation marker (\ue0c8)
        clean_address = re.sub(r"[\ue0c0-\ue0ff]", "", raw_address).strip() or None

        return {
            "rating": float(rating) if rating is not None else None,
            "review_count": int(review_count_raw) if review_count_raw and rating is not None else None,
            "status": status,
            "google_name": google_name if google_name.lower() != "results" else None,
            "google_address": clean_address,
            "maps_url": maps_url,
            "scraped_at": time.strftime("%Y-%m-%d"),
        }

    except Exception as exc:
        print(f"    ✗ {rid}: {exc}")
        return None


async def scrape_record(page, targets: list[str], record: dict) -> dict | None:
    """Try each target in turn; return the first result that matches the record."""
    rid = record.get("id", "")
    if record.get("lat") is None or record.get("lng") is None:
        print(f"    {rid}: record has no coordinates, results are unguarded")
    for target in targets:
        result = await scrape_one(page, target, rid)
        if result is None:
            continue
        problem = match_problem(result, record)
        if problem is None:
            return result
        print(f"    {rid}: rejected {result.get('google_name')!r} from {target!r}: {problem}")
    return None


async def worker(
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
                targets, record = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            rid = record.get("id", "")
            result = await scrape_record(page, targets, record)
            if result:
                results[rid] = result
                if result["status"]:
                    print(f"  [{worker_id}] ✓ {rid}: {result['status']}")
                else:
                    print(f"  [{worker_id}] ✓ {rid}: {result['rating']} ({result['review_count']} reviews)")
            else:
                print(f"  [{worker_id}] – {rid}: no data")

            queue.task_done()
            await asyncio.sleep(rate_limit_delay)

        await browser.close()


async def run_scraper(
    queries: list[tuple[list[str], dict]],
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
                worker(q, batch_results, i + 1, delay)
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
    p.add_argument("--datasets", nargs="+", default=["global", "japan", "love", "tft", "stays"],
                   choices=["global", "japan", "love", "tft", "stays"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ids-file",
                   help="Optional newline-delimited list of record IDs to refresh")
    p.add_argument("--missing-only", action="store_true",
                   help="Skip records already in ratings cache")
    p.add_argument("--max-age-days", type=int,
                   help="Refresh only missing ratings or ratings older than this many days")
    p.add_argument("--max-queries", type=int, default=0,
                   help="Bound this run to the first N eligible records (0 = unlimited)")
    p.add_argument("--concurrency", type=int, default=3,
                   help="Parallel browser instances (default: 3)")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Queries per batch before saving (default: 100)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_age_days is not None and args.max_age_days < 0:
        raise SystemExit("--max-age-days must be zero or greater")
    if args.max_queries < 0:
        raise SystemExit("--max-queries must be zero or greater")
    if args.concurrency < 1 or args.batch_size < 1:
        raise SystemExit("--concurrency and --batch-size must be positive")

    existing: dict[str, dict] = {}
    if RATINGS_PATH.exists():
        existing = json.loads(RATINGS_PATH.read_text())
        print(f"Existing cache: {len(existing)} records")

    skip_ids = set(existing.keys()) if args.missing_only else set()
    if args.max_age_days is not None and not args.missing_only:
        cutoff = datetime.date.today() - datetime.timedelta(days=args.max_age_days)
        for record_id, rating in existing.items():
            try:
                checked = datetime.date.fromisoformat(str(rating.get("scraped_at") or ""))
            except (AttributeError, ValueError):
                continue
            if checked >= cutoff:
                skip_ids.add(record_id)

    allowed_ids: set[str] | None = None
    if args.ids_file:
        allowed_ids = {
            line.strip()
            for line in Path(args.ids_file).read_text().splitlines()
            if line.strip()
        }
        print(f"ID filter: {len(allowed_ids)} records from {args.ids_file}")

    print(f"\nLoading datasets: {args.datasets}")
    datasets = load_datasets(args.datasets)
    if not datasets:
        print("No datasets loaded.")
        sys.exit(1)

    all_queries: list[tuple[list[str], dict]] = []
    for name, records in datasets.items():
        if allowed_ids is not None:
            records = [rec for rec in records if rec.get("id") in allowed_ids]
        pairs = build_queries(records, name, skip_ids)
        print(f"  {name}: {len(pairs)} queries (of {len(records)} records)")
        all_queries.extend(pairs)

    if args.max_queries > 0:
        all_queries = oldest_first(all_queries, existing)[: args.max_queries]

    print(f"\nTotal queries: {len(all_queries)}")
    if not all_queries:
        print("Nothing to scrape.")
        return

    if args.dry_run:
        for targets, record in all_queries[:20]:
            print(f"  {record.get('id')}: {' -> '.join(targets)}")
        if len(all_queries) > 20:
            print(f"  ... and {len(all_queries) - 20} more")
        return

    merged = asyncio.run(run_scraper(all_queries, args.concurrency, existing, args.batch_size))

    added = len(merged) - len(existing)
    print(f"\nDone. Added {added} new ratings. Total: {len(merged)}")
    print(f"Output → {RATINGS_PATH}")


if __name__ == "__main__":
    main()
