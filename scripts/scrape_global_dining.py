#!/usr/bin/env python3
"""Scrape Amex Platinum Dining global restaurant list from platinumdining.caffeinesoftware.com

Fetches all non-Japan restaurant pages via the sitemap, extracts JSON-LD structured data,
and saves to data/global-restaurants.json. Supports diff mode to detect additions/removals.

Usage:
    python3 scripts/scrape_global_dining.py              # Full scrape
    python3 scripts/scrape_global_dining.py --diff       # Compare against snapshot, print changes
    python3 scripts/scrape_global_dining.py --dry-run    # Fetch + show stats, don't write files
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "global-restaurants.json"
SNAPSHOT_PATH = DATA_DIR / "global-dining-snapshot.json"
SOURCE_META_PATH = DATA_DIR / "global-dining-source.json"

BASE_URL = "https://platinumdining.caffeinesoftware.com"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
# Sitemap references platinumdining.co.uk; we remap to caffeinesoftware.com for fetching
SITEMAP_DOMAIN = "https://platinumdining.co.uk"

# Countries that are handled by Pocket Concierge — skip them
SKIP_COUNTRIES = {"japan"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def http_get(url: str, retries: int = 3, timeout: int = 15) -> str:
    """Simple HTTP GET with retries."""
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            if attempt == retries - 1:
                raise
            time.sleep(1.5 ** attempt)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 ** attempt)
    return ""


def remap_url(url: str) -> str:
    """Remap sitemap domain (platinumdining.co.uk) to fetchable domain (caffeinesoftware.com)."""
    return url.replace(SITEMAP_DOMAIN, BASE_URL)


def fetch_sitemap_urls() -> list[str]:
    """Download sitemap and return all restaurant page URLs (3-level paths)."""
    print("Fetching sitemap...", file=sys.stderr)
    xml_content = http_get(SITEMAP_URL)
    if not xml_content:
        raise RuntimeError("Failed to fetch sitemap")

    root = ET.fromstring(xml_content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Check if it's a sitemap index
    sitemaps = root.findall("sm:sitemap/sm:loc", ns)
    if sitemaps:
        all_urls: list[str] = []
        for sitemap_loc in sitemaps:
            sub_url = remap_url(sitemap_loc.text or "")
            if not sub_url:
                continue
            sub_xml = http_get(sub_url)
            if not sub_xml:
                continue
            sub_root = ET.fromstring(sub_xml)
            for url_el in sub_root.findall("sm:url/sm:loc", sub_xml):
                all_urls.append(remap_url(url_el.text or ""))
            time.sleep(0.3)
        return all_urls

    # Single sitemap
    return [remap_url(el.text or "") for el in root.findall("sm:url/sm:loc", ns) if el.text]


ISO_COUNTRY_MAP = {
    "AU": "Australia", "AT": "Austria", "CA": "Canada", "FR": "France",
    "DE": "Germany", "HK": "Hong Kong", "IT": "Italy", "MX": "Mexico",
    "MC": "Monaco", "NZ": "New Zealand", "SG": "Singapore", "ES": "Spain",
    "TW": "Taiwan", "TH": "Thailand", "GB": "United Kingdom", "US": "United States",
}


def is_restaurant_url(url: str) -> bool:
    """Return True if the URL is a 3-level restaurant detail page."""
    path = url.replace(BASE_URL, "").replace(SITEMAP_DOMAIN, "").strip("/")
    parts = path.split("/")
    if len(parts) != 3:
        return False
    country_slug = parts[0].lower()
    if country_slug in SKIP_COUNTRIES:
        return False
    if parts[0] in ("api", "_next", "static", "sitemap", "map"):
        return False
    return True


def extract_json_ld(html: str) -> dict[str, Any] | None:
    """Extract the first Restaurant schema.org JSON-LD block from HTML."""
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1))
            # Handle @graph arrays
            if isinstance(data, dict) and data.get("@graph"):
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Restaurant":
                        return item
            if isinstance(data, dict) and data.get("@type") == "Restaurant":
                return data
        except Exception:
            continue
    return None


def slug_to_country_name(slug: str) -> str:
    """Convert a URL slug to a display country name."""
    mapping = {
        "australia": "Australia",
        "austria": "Austria",
        "canada": "Canada",
        "france": "France",
        "germany": "Germany",
        "hong-kong": "Hong Kong",
        "italy": "Italy",
        "mexico": "Mexico",
        "monaco": "Monaco",
        "new-zealand": "New Zealand",
        "singapore": "Singapore",
        "spain": "Spain",
        "taiwan": "Taiwan",
        "thailand": "Thailand",
        "united-kingdom": "United Kingdom",
        "united-states": "United States",
    }
    return mapping.get(slug, slug.replace("-", " ").title())


def slug_to_region_name(slug: str) -> str:
    return slug.replace("-", " ").title()


def build_record(url: str, json_ld: dict[str, Any]) -> dict[str, Any]:
    """Build a restaurant record from a JSON-LD block and source URL."""
    path = url.replace(BASE_URL, "").replace(SITEMAP_DOMAIN, "").strip("/")
    parts = path.split("/")
    country_slug = parts[0] if len(parts) >= 1 else ""
    region_slug = parts[1] if len(parts) >= 2 else ""
    restaurant_slug = parts[2] if len(parts) >= 3 else ""

    country = slug_to_country_name(country_slug)
    region = slug_to_region_name(region_slug)

    addr = json_ld.get("address") or {}
    if isinstance(addr, str):
        addr = {}

    street = addr.get("streetAddress") or ""
    locality = addr.get("addressLocality") or ""
    state = addr.get("addressRegion") or region
    postal = addr.get("postalCode") or ""
    raw_country_code = addr.get("addressCountry") or ""
    addr_country = ISO_COUNTRY_MAP.get(raw_country_code.upper(), raw_country_code) or country

    # Some records have the state in addressLocality — extract suburb from street if so
    # e.g. street="1 Burbury Cl, Barton", locality="Australian Capital Territory"
    city = locality
    if not city or city == state:
        # Try extracting the last part of streetAddress as suburb
        street_parts = [p.strip() for p in street.split(",") if p.strip()]
        if len(street_parts) >= 2:
            city = street_parts[-1]
        else:
            city = state or region

    # Build full address string
    address_parts = [p for p in [street, locality, state, postal] if p]
    full_address = ", ".join(address_parts)
    if addr_country and addr_country not in full_address:
        full_address = f"{full_address}, {addr_country}" if full_address else addr_country

    # Coordinates
    geo = json_ld.get("geo") or {}
    lat = geo.get("latitude") or geo.get("lat")
    lng = geo.get("longitude") or geo.get("long") or geo.get("lng")
    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lat = lng = None

    # Cuisine
    cuisine_raw = json_ld.get("servesCuisine") or ""
    if isinstance(cuisine_raw, list):
        cuisines = [c for c in cuisine_raw if c]
    else:
        cuisines = [cuisine_raw] if cuisine_raw else []

    name = json_ld.get("name") or restaurant_slug.replace("-", " ").title()
    website = json_ld.get("url") or json_ld.get("sameAs") or ""

    record_id = f"amex-global-{country_slug}-{restaurant_slug}"

    search_parts = [name, city, state, country, *cuisines, street]
    search_text = " ".join(p.lower() for p in search_parts if p)

    return {
        "id": record_id,
        "source": "Amex Platinum Dining",
        "source_url": url,
        "country": country,
        "region": state or region,
        "city": city,
        "district": None,
        "name": name,
        "cuisines": cuisines,
        "source_localized_address": full_address,
        "lat": lat,
        "lng": lng,
        "coordinate_confidence": "source" if (lat and lng) else "none",
        "website_url": website or None,
        "external_signals": {},
        "search_text": search_text,
        # Fields present in Japan data (default values for non-Japan)
        "price_lunch_band_key": None,
        "price_dinner_band_key": None,
        "price_lunch_band_tier": None,
        "price_dinner_band_tier": None,
        "price_lunch_band_label": None,
        "price_dinner_band_label": None,
        "price_lunch_min_jpy": None,
        "price_lunch_max_jpy": None,
        "price_dinner_min_jpy": None,
        "price_dinner_max_jpy": None,
        "child_policy_norm": "unknown",
        "english_menu": None,
        "reservation_type": None,
        "known_for_tags": [],
        "signature_dish_tags": [],
        "nearest_stations": [],
        "summary_official": None,
    }


def record_hash(record: dict[str, Any]) -> str:
    """Stable hash of a restaurant record for change detection."""
    key = json.dumps({
        "name": record.get("name"),
        "source_url": record.get("source_url"),
        "source_localized_address": record.get("source_localized_address"),
        "lat": record.get("lat"),
        "lng": record.get("lng"),
        "cuisines": record.get("cuisines"),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_snapshot() -> dict[str, dict[str, Any]]:
    """Load the last snapshot. Returns {id: record}."""
    if not SNAPSHOT_PATH.exists():
        return {}
    return {r["id"]: r for r in json.loads(SNAPSHOT_PATH.read_text())}


def print_diff(old: dict[str, dict], new: dict[str, dict]) -> None:
    """Print a human-readable diff of additions and removals."""
    added = [r for id_, r in new.items() if id_ not in old]
    removed = [r for id_, r in old.items() if id_ not in new]

    changed = []
    for id_, new_r in new.items():
        if id_ in old and record_hash(old[id_]) != record_hash(new_r):
            changed.append((old[id_], new_r))

    print(f"\n{'='*60}")
    print(f"DIFF: +{len(added)} added  -{len(removed)} removed  ~{len(changed)} changed")
    print(f"{'='*60}\n")

    if added:
        print("ADDED:")
        for r in sorted(added, key=lambda x: (x["country"], x["city"], x["name"])):
            print(f"  + {r['name']}  ({r['city']}, {r['country']})")

    if removed:
        print("\nREMOVED:")
        for r in sorted(removed, key=lambda x: (x["country"], x["city"], x["name"])):
            print(f"  - {r['name']}  ({r['city']}, {r['country']})")

    if changed:
        print(f"\nCHANGED: {len(changed)} records had data updates")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", action="store_true",
                        help="Compare new scrape against snapshot and print changes")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but don't write output files")
    parser.add_argument("--pause", type=float, default=0.25,
                        help="Seconds to pause between requests (default: 0.25)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to N restaurants (for testing)")
    args = parser.parse_args()

    # ── 1. Get all restaurant URLs from sitemap ──────────────────────
    all_urls = fetch_sitemap_urls()
    restaurant_urls = [u for u in all_urls if is_restaurant_url(u)]
    print(f"Sitemap: {len(all_urls)} total URLs → {len(restaurant_urls)} restaurant pages", file=sys.stderr)

    if args.limit:
        restaurant_urls = restaurant_urls[:args.limit]
        print(f"(limited to {args.limit} for testing)", file=sys.stderr)

    # ── 2. Fetch each restaurant page and extract JSON-LD ────────────
    records: list[dict[str, Any]] = []
    failed: list[str] = []
    start = datetime.datetime.now()

    for i, url in enumerate(restaurant_urls, 1):
        elapsed = (datetime.datetime.now() - start).total_seconds()
        rate = i / elapsed if elapsed > 0 else 0
        eta = (len(restaurant_urls) - i) / rate if rate > 0 else 0
        sys.stderr.write(
            f"\r[{i}/{len(restaurant_urls)}] {rate:.1f} req/s  ETA {eta/60:.0f}m  "
            f"ok={len(records)} fail={len(failed)}   "
        )
        sys.stderr.flush()

        try:
            html = http_get(url, retries=2)
            if not html:
                failed.append(url)
                continue
            json_ld = extract_json_ld(html)
            if not json_ld:
                failed.append(url)
                continue
            record = build_record(url, json_ld)
            records.append(record)
        except Exception as e:
            failed.append(url)
        time.sleep(args.pause)

    sys.stderr.write("\n")

    print(f"\nScraped {len(records)} restaurants, {len(failed)} failed", file=sys.stderr)

    if failed:
        print(f"Failed URLs (first 10):", file=sys.stderr)
        for u in failed[:10]:
            print(f"  {u}", file=sys.stderr)

    # ── 3. Stats ─────────────────────────────────────────────────────
    from collections import Counter
    by_country = Counter(r["country"] for r in records)
    mapped = sum(1 for r in records if r.get("lat") and r.get("lng"))
    print(f"\nCoverage: {mapped}/{len(records)} records have coordinates")
    print(f"\nBy country:")
    for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
        print(f"  {country}: {count}")

    if args.dry_run:
        print("\n(dry-run: no files written)")
        return

    # ── 4. Diff against snapshot ──────────────────────────────────────
    old_snapshot = load_snapshot()
    new_by_id = {r["id"]: r for r in records}
    if old_snapshot or args.diff:
        print_diff(old_snapshot, new_by_id)

    # ── 5. Write output files ─────────────────────────────────────────
    fetched_at = datetime.datetime.utcnow().isoformat() + "Z"

    OUTPUT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} records → {OUTPUT_PATH}")

    SNAPSHOT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")

    meta = {
        "fetched_at": fetched_at,
        "record_count": len(records),
        "mapped_count": mapped,
        "source_url": BASE_URL,
        "countries": dict(sorted(by_country.items())),
        "failed_count": len(failed),
    }
    SOURCE_META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote metadata → {SOURCE_META_PATH}")
    print(f"\nRun again with --diff to detect changes on next scrape.")


if __name__ == "__main__":
    main()
