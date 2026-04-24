#!/usr/bin/env python3
"""Sync Amex Platinum Dining global restaurant list from the official Amex app API.

Fetches non-Japan restaurant data from the official dining benefit app used by
https://www.americanexpress.com/en-sg/benefits/diningbenefit/ and saves it to
data/global-restaurants.json. Supports diff mode to detect additions/removals.

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
import difflib
from math import atan2, cos, radians, sin, sqrt
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "global-restaurants.json"
SNAPSHOT_PATH = DATA_DIR / "global-dining-snapshot.json"
SOURCE_META_PATH = DATA_DIR / "global-dining-source.json"
OVERRIDES_PATH = DATA_DIR / "coordinate-overrides.json"
GEOCODE_CACHE_PATH = DATA_DIR / "global-dining-geocode-cache.json"
GOOGLE_RATINGS_PATH = DATA_DIR / "google-maps-ratings.json"

OFFICIAL_PAGE_URL = "https://www.americanexpress.com/en-sg/benefits/diningbenefit/"
API_BASE_URL = "https://dining-offers-prod.amex.r53.tuimedia.com"
COUNTRIES_API_URL = f"{API_BASE_URL}/api/countries"
ORIGIN_MARKET = "SG"

# Legacy constants kept for compatibility with helpers that parse old source URLs.
BASE_URL = API_BASE_URL
SITEMAP_URL = f"{API_BASE_URL}/sitemap.xml"
SITEMAP_DOMAIN = API_BASE_URL

# Countries that are handled by Pocket Concierge — skip them
SKIP_COUNTRIES = {"japan"}
SKIP_COUNTRY_CODES = {"JP"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SOURCE_MAP_ALIGNMENT_KM = 0.35
GOOGLE_PLACE_ALIGNMENT_KM = 0.35
HEX_SLUG_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$", re.IGNORECASE)
POSTCODE_TOKEN_RE = re.compile(
    r"^(?:"
    r"\d{4,6}|"
    r"[a-z]\d[a-z]\d[a-z]\d|"
    r"[a-z]{1,2}\d[a-z\d]?\d[a-z]{2}"
    r")$",
    re.IGNORECASE,
)


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
            if e.code in {429, 500, 502, 503, 504} and attempt < retries - 1:
                time.sleep(1.5 ** attempt)
                continue
            if attempt == retries - 1:
                raise
            time.sleep(1.5 ** attempt)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 ** attempt)
    return ""


def http_json(url: str, retries: int = 3, timeout: int = 30) -> Any:
    body = http_get(url, retries=retries, timeout=timeout)
    if not body:
        raise RuntimeError(f"Empty response from {url}")
    return json.loads(body)


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
            for url_el in sub_root.findall("sm:url/sm:loc", ns):
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

COUNTRY_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "Australia": (-44.5, -10.0, 112.0, 154.0),
    "Austria": (46.0, 50.0, 9.0, 18.0),
    "Canada": (41.0, 84.0, -141.0, -52.0),
    "France": (41.0, 52.0, -6.0, 10.0),
    "Germany": (47.0, 56.0, 5.0, 16.0),
    "Hong Kong": (22.1, 22.6, 113.8, 114.5),
    "Italy": (35.0, 48.0, 6.0, 19.0),
    "Mexico": (14.0, 33.0, -119.0, -86.0),
    "Monaco": (43.70, 43.80, 7.40, 7.50),
    "New Zealand": (-48.0, -33.0, 166.0, 179.9),
    "Singapore": (1.1, 1.5, 103.5, 104.1),
    "Spain": (27.0, 44.0, -19.0, 5.0),
    "Taiwan": (21.5, 25.5, 119.0, 122.5),
    "Thailand": (5.0, 21.0, 97.0, 106.0),
    "United Kingdom": (49.0, 61.0, -9.0, 3.0),
    "United States": (18.0, 72.0, -171.0, -66.0),
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


def compact_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return 6371 * 2 * atan2(sqrt(a), sqrt(1 - a))


def within_country_bounds(country: str | None, lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    bounds = COUNTRY_BOUNDS.get(country or "")
    if not bounds:
        return True
    min_lat, max_lat, min_lng, max_lng = bounds
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def geocode_query(query: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "amex-dining-map/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data[0] if data else None
    except Exception:
        return None


def geocode_with_cache(query: str, cache: dict[str, Any]) -> dict[str, Any] | None:
    if query in cache:
        return cache[query]
    result = geocode_query(query)
    cache[query] = result
    save_json(GEOCODE_CACHE_PATH, cache)
    time.sleep(1.1)
    return result


def parse_google_map_coordinates(
    url: str | None,
    resolve_short_urls: bool = True,
) -> tuple[float | None, float | None]:
    if not url:
        return None, None

    candidates = [url]
    parsed = urllib.parse.urlparse(url)
    should_resolve = resolve_short_urls and ("goo.gl" in parsed.netloc or "maps.app.goo.gl" in parsed.netloc)
    if should_resolve:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                redirected = resp.geturl()
            if redirected and redirected not in candidates:
                candidates.insert(0, redirected)
        except Exception:
            pass

    for candidate in candidates:
        decoded = urllib.parse.unquote(candidate)
        for pattern in (
            r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
            r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)",
        ):
            match = re.search(pattern, decoded)
            if match:
                return float(match.group(1)), float(match.group(2))

        query = urllib.parse.parse_qs(urllib.parse.urlparse(candidate).query)
        for key in ("q", "query", "ll", "center"):
            value = query.get(key, [None])[0]
            if not value:
                continue
            match = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", urllib.parse.unquote(value))
            if match:
                return float(match.group(1)), float(match.group(2))

    return None, None


def parse_google_place_id(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        return urllib.parse.parse_qs(parsed.query).get("query_place_id", [None])[0]
    except Exception:
        return None


def normalized_ascii(value: str | None) -> str:
    if not value:
        return ""
    text = urllib.parse.unquote(value)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = re.sub(r"\bno\.?\b", " ", text)
    text = re.sub(r"\bsection\b", "sec", text)
    text = re.sub(r"\broad\b", "rd", text)
    text = re.sub(r"\bstreet\b", "st", text)
    text = re.sub(r"\bavenue\b", "ave", text)
    text = re.sub(r"\bwest\b", "w", text)
    text = re.sub(r"\beast\b", "e", text)
    text = re.sub(r"\bnorth\b", "n", text)
    text = re.sub(r"\bsouth\b", "s", text)
    text = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return compact_space(text)


def token_overlap(left: str | None, right: str | None) -> int:
    left_tokens = set(normalized_ascii(left).split())
    right_tokens = set(normalized_ascii(right).split())
    return len(left_tokens & right_tokens)


def text_similarity(left: str | None, right: str | None) -> float:
    a = normalized_ascii(left)
    b = normalized_ascii(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def names_match(left: str | None, right: str | None) -> bool:
    overlap = token_overlap(left, right)
    return overlap >= 2 or text_similarity(left, right) >= 0.72


def addresses_match(left: str | None, right: str | None) -> bool:
    overlap = token_overlap(left, right)
    return overlap >= 3 or text_similarity(left, right) >= 0.65


def google_rating_candidate(
    record: dict[str, Any],
    google_ratings: dict[str, Any],
) -> dict[str, Any] | None:
    rating = google_ratings.get(record["id"])
    if not isinstance(rating, dict):
        return None

    google_name = compact_space(rating.get("google_name"))
    if not google_name or google_name.lower() == "results":
        return None

    lat, lng = parse_google_map_coordinates(rating.get("maps_url"))
    if not within_country_bounds(record.get("country"), lat, lng):
        return None

    return {
        "lat": float(lat),
        "lng": float(lng),
        "place_id": parse_google_place_id(rating.get("maps_url")),
        "name_ok": names_match(record.get("name"), google_name),
        "address_ok": addresses_match(record.get("source_localized_address"), rating.get("google_address")),
        "google_name": google_name,
        "google_address": compact_space(rating.get("google_address")),
    }


def candidate_queries(record: dict[str, Any]) -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []

    address = compact_space(record.get("source_localized_address"))
    country = compact_space(record.get("country"))
    city = compact_space(record.get("city"))
    region = compact_space(record.get("region"))
    name = compact_space(record.get("name"))

    if address:
        queries.append(("nominatim_address_validation", f"{address}, {country}"))
        if name:
            queries.append(("nominatim_name_address_validation", f"{name}, {address}, {country}"))
    if name and city:
        queries.append(("nominatim_name_city_validation", f"{name}, {city}, {country}"))
    if name and region and region != city:
        queries.append(("nominatim_name_region_validation", f"{name}, {region}, {country}"))

    source_map = record.get("source_google_map_url")
    if source_map:
        parsed_map = urllib.parse.urlparse(source_map)
        for key in ("query", "q"):
            value = urllib.parse.parse_qs(parsed_map.query).get(key, [None])[0]
            cleaned = compact_space(urllib.parse.unquote(value)) if value else ""
            if cleaned:
                queries.append(("nominatim_source_map_query", cleaned))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source_label, query in queries:
        if not query or query in seen:
            continue
        seen.add(query)
        deduped.append((source_label, query))
    return deduped


def validated_fallback_coordinates(record: dict[str, Any], cache: dict[str, Any]) -> tuple[float, float, str] | None:
    map_lat, map_lng = parse_google_map_coordinates(record.get("source_google_map_url"))
    if within_country_bounds(record.get("country"), map_lat, map_lng):
        return float(map_lat), float(map_lng), "source_google_map_url"

    for source_label, query in candidate_queries(record):
        result = geocode_with_cache(query, cache)
        if not result:
            continue
        lat = float(result["lat"])
        lng = float(result["lon"])
        if within_country_bounds(record.get("country"), lat, lng):
            return lat, lng, source_label

    return None


def count_duplicate_values(values: list[str]) -> int:
    counts: dict[str, int] = {}
    duplicates = 0
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
        if counts[value] == 2:
            duplicates += 1
    return duplicates


def canonical_restaurant_slug(url: str | None) -> str:
    slug = (url or "").rstrip("/").split("/")[-1]
    slug = HEX_SLUG_SUFFIX_RE.sub("", slug)
    return normalized_ascii(slug)


def canonical_address(value: str | None, country: str | None) -> str:
    text = normalized_ascii(value)
    if not text:
        return ""

    country_norm = normalized_ascii(country)
    filtered_tokens: list[str] = []
    for token in text.split():
        if country_norm and token in country_norm.split():
            continue
        if POSTCODE_TOKEN_RE.fullmatch(token):
            continue
        filtered_tokens.append(token)
    return compact_space(" ".join(filtered_tokens))


def venue_fingerprint(record: dict[str, Any]) -> tuple[str, ...]:
    country = normalized_ascii(record.get("country"))
    name = normalized_ascii(record.get("name"))
    address = canonical_address(record.get("source_localized_address"), record.get("country"))
    website = normalized_ascii(record.get("website_url"))
    city = normalized_ascii(record.get("city"))

    if name and address:
        return ("name_address", country, name, address)
    if name and website and city:
        return ("name_website_city", country, name, website, city)
    return ("canonical_slug", country, canonical_restaurant_slug(record.get("source_url")))


def record_quality_score(record: dict[str, Any]) -> tuple[int, int, int, int]:
    slug = (record.get("source_url") or "").rstrip("/").split("/")[-1]
    is_plain_slug = int(not HEX_SLUG_SUFFIX_RE.search(slug))
    has_website = int(bool(record.get("website_url")))
    has_map = int(bool(record.get("source_google_map_url")))
    has_coordinates = int(record.get("lat") is not None and record.get("lng") is not None)
    return (is_plain_slug, has_website, has_map, has_coordinates)


def dedupe_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    duplicate_urls = 0
    for record in records:
        source_key = record.get("source_record_url") or record.get("source_merchant_id") or record.get("source_url")
        if source_key in by_url:
            duplicate_urls += 1
            continue
        by_url[source_key] = record

    if all(record.get("source_merchant_id") for record in by_url.values()):
        stats = {
            "raw_count": len(records),
            "duplicate_source_urls": duplicate_urls,
            "duplicate_fingerprints": 0,
            "removed_count": len(records) - len(by_url),
            "replaced_with_better": 0,
            "removed_by_country": {},
        }
        return list(by_url.values()), stats

    deduped: list[dict[str, Any]] = []
    seen_fingerprints: dict[tuple[str, ...], int] = {}
    duplicate_fingerprints = 0
    replaced_with_better = 0
    removed_by_country: dict[str, int] = {}

    for record in by_url.values():
        fingerprint = venue_fingerprint(record)
        existing_idx = seen_fingerprints.get(fingerprint)
        if existing_idx is None:
            seen_fingerprints[fingerprint] = len(deduped)
            deduped.append(record)
            continue

        duplicate_fingerprints += 1
        country = record.get("country") or "Unknown"
        removed_by_country[country] = removed_by_country.get(country, 0) + 1

        existing = deduped[existing_idx]
        if record_quality_score(record) > record_quality_score(existing):
            deduped[existing_idx] = record
            replaced_with_better += 1

    stats = {
        "raw_count": len(records),
        "duplicate_source_urls": duplicate_urls,
        "duplicate_fingerprints": duplicate_fingerprints,
        "removed_count": len(records) - len(deduped),
        "replaced_with_better": replaced_with_better,
        "removed_by_country": dict(sorted(removed_by_country.items(), key=lambda item: (-item[1], item[0]))),
    }
    return deduped, stats


def unique_record_id(record: dict[str, Any], include_region: bool = False) -> str:
    if record.get("source_merchant_id"):
        country_slug = normalized_ascii(record.get("country")).replace(" ", "-")
        name_slug = normalized_ascii(record.get("name")).replace(" ", "-")
        city_slug = normalized_ascii(record.get("city")).replace(" ", "-")
        if include_region and city_slug:
            return f"amex-global-{country_slug}-{name_slug}-{city_slug}"
        return f"amex-global-{country_slug}-{name_slug}"

    path = (record.get("source_url") or "").replace(BASE_URL, "").replace(SITEMAP_DOMAIN, "").strip("/")
    parts = path.split("/")
    country_slug = parts[0] if len(parts) >= 1 else ""
    region_slug = parts[1] if len(parts) >= 2 else ""
    restaurant_slug = parts[2] if len(parts) >= 3 else ""
    if include_region and region_slug:
        return f"amex-global-{country_slug}-{region_slug}-{restaurant_slug}"
    return f"amex-global-{country_slug}-{restaurant_slug}"


def assign_unique_record_ids(records: list[dict[str, Any]]) -> int:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["id"], []).append(record)

    reassigned = 0
    used_ids = {record["id"] for record in records}
    for record_id, group in groups.items():
        if len(group) <= 1:
            continue

        used_ids.discard(record_id)
        for record in group:
            candidate = unique_record_id(record, include_region=True)
            if not candidate or candidate in used_ids:
                path = (record.get("source_url") or "").replace(BASE_URL, "").replace(SITEMAP_DOMAIN, "").strip("/")
                stable_key = record.get("source_merchant_id") or path
                short_hash = hashlib.sha1(stable_key.encode()).hexdigest()[:8]
                candidate = f"{unique_record_id(record, include_region=True)}-{short_hash}"
            record["id"] = candidate
            used_ids.add(candidate)
            reassigned += 1
    return reassigned


def validate_record_coordinates(
    record: dict[str, Any],
    cache: dict[str, Any],
    google_ratings: dict[str, Any],
) -> None:
    lat = record.get("lat")
    lng = record.get("lng")
    source_geo_ok = within_country_bounds(record.get("country"), lat, lng)
    source_map_lat, source_map_lng = parse_google_map_coordinates(record.get("source_google_map_url"))
    source_map_ok = within_country_bounds(record.get("country"), source_map_lat, source_map_lng)
    source_map_place_id = parse_google_place_id(record.get("source_google_map_url"))
    google_candidate = google_rating_candidate(record, google_ratings)

    if (
        google_candidate
        and source_map_place_id
        and google_candidate.get("place_id")
        and source_map_place_id == google_candidate["place_id"]
        and not source_map_ok
    ):
        record["lat"] = google_candidate["lat"]
        record["lng"] = google_candidate["lng"]
        record["coordinate_source"] = "google_maps_ratings"
        record["coordinate_confidence"] = "google_place_verified"
        record["map_pin_note"] = (
            "The official source map points to the same Google place, so the pin uses the verified Google place "
            "coordinates."
        )
        return

    if source_map_ok:
        if google_candidate:
            same_place = (
                source_map_place_id
                and google_candidate.get("place_id")
                and source_map_place_id == google_candidate["place_id"]
            )
            map_gap = distance_km(
                float(source_map_lat),
                float(source_map_lng),
                google_candidate["lat"],
                google_candidate["lng"],
            )
            if same_place or map_gap <= GOOGLE_PLACE_ALIGNMENT_KM:
                record["lat"] = float(source_map_lat)
                record["lng"] = float(source_map_lng)
                record["coordinate_source"] = "source_google_map_url"
                record["coordinate_confidence"] = "google_place_verified"
                if source_geo_ok:
                    source_gap = distance_km(float(lat), float(lng), float(source_map_lat), float(source_map_lng))
                    if source_gap > SOURCE_MAP_ALIGNMENT_KM:
                        record["map_pin_note"] = (
                            "Raw source coordinates drifted from the official source map, so the pin now follows "
                            "the official map link confirmed by the Google place."
                        )
                    else:
                        record["map_pin_note"] = (
                            "Official source map and Google place agree on this location."
                        )
                else:
                    record["map_pin_note"] = (
                        "Source map and Google place agree on this location, so the pin uses the verified place."
                    )
                return

            if google_candidate["name_ok"] or google_candidate["address_ok"]:
                record["lat"] = None
                record["lng"] = None
                record["coordinate_source"] = None
                record["coordinate_confidence"] = "location_conflict"
                record["map_pin_note"] = (
                    "The official source map and the matched Google place disagree on the venue location, so the pin "
                    "is hidden until the place can be confirmed."
                )
                return

        record["lat"] = float(source_map_lat)
        record["lng"] = float(source_map_lng)
        record["coordinate_source"] = "source_google_map_url"
        record["coordinate_confidence"] = "source_map_verified"
        if source_geo_ok:
            source_gap = distance_km(float(lat), float(lng), float(source_map_lat), float(source_map_lng))
            if source_gap > SOURCE_MAP_ALIGNMENT_KM:
                record["map_pin_note"] = (
                    "Raw source coordinates were offset from the official source map, so the pin now follows the "
                    "official map link."
                )
            else:
                record["map_pin_note"] = "Pin matches the official source map link for this venue."
        else:
            record["map_pin_note"] = "Pin comes from the official source map link for this venue."
        return

    if source_geo_ok and google_candidate and (google_candidate["name_ok"] or google_candidate["address_ok"]):
        source_gap = distance_km(float(lat), float(lng), google_candidate["lat"], google_candidate["lng"])
        if source_gap <= GOOGLE_PLACE_ALIGNMENT_KM:
            record["coordinate_source"] = "google_maps_ratings"
            record["coordinate_confidence"] = "google_place_verified"
            record["map_pin_note"] = "Source coordinates align with the matched Google place."
            return

    if source_geo_ok:
        record["coordinate_source"] = "json_ld_geo"
        record["coordinate_confidence"] = "source"
        record["map_pin_note"] = None
        return

    if google_candidate and (google_candidate["name_ok"] or google_candidate["address_ok"]):
        record["lat"] = google_candidate["lat"]
        record["lng"] = google_candidate["lng"]
        record["coordinate_source"] = "google_maps_ratings"
        record["coordinate_confidence"] = "google_place_verified"
        if record.get("source_google_map_url"):
            record["map_pin_note"] = (
                "Published source coordinates were unusable, so the pin now follows the matched Google place for "
                "this venue."
            )
        else:
            record["map_pin_note"] = (
                "Source coordinates were invalid for this venue, so the pin now follows the matched Google place."
            )
        return

    fallback = validated_fallback_coordinates(record, cache)
    if fallback:
        validated_lat, validated_lng, source_label = fallback
        record["lat"] = validated_lat
        record["lng"] = validated_lng
        record["coordinate_source"] = source_label
        record["coordinate_confidence"] = "address_validated"
        record["map_pin_note"] = (
            "Source coordinates were invalid for this market, so the pin was corrected "
            "using a validated address or source map fallback."
        )
        return

    record["lat"] = None
    record["lng"] = None
    record["coordinate_source"] = None
    record["coordinate_confidence"] = "none"
    record["map_pin_note"] = (
        "The published source coordinates could not be validated yet, so the pin is hidden "
        "until the venue address can be confirmed."
    )


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

    # Build full address string — deduplicate consecutive identical segments
    # (some JSON-LD records repeat the region in both addressLocality and addressRegion)
    raw_parts = [p for p in [street, locality, state, postal] if p]
    address_parts: list[str] = []
    for part in raw_parts:
        if not address_parts or part != address_parts[-1]:
            address_parts.append(part)
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
    source_google_map_url = json_ld.get("hasMap") or None

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
        "source_google_map_url": source_google_map_url,
        "lat": lat,
        "lng": lng,
        "coordinate_source": "json_ld_geo" if (lat is not None and lng is not None) else None,
        "coordinate_confidence": "source" if (lat and lng) else "none",
        "map_pin_note": None,
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


def country_slug(country_name: str) -> str:
    return normalized_ascii(country_name).replace(" ", "-")


def record_slug(value: str) -> str:
    slug = normalized_ascii(value).replace(" ", "-")
    return slug or hashlib.sha1(value.encode()).hexdigest()[:8]


def translated_value(payload: dict[str, Any] | None, key: str, locale: str = "en") -> str:
    if not isinstance(payload, dict):
        return ""
    translations = payload.get("translations")
    if isinstance(translations, dict):
        localized = translations.get(locale)
        if isinstance(localized, dict) and localized.get(key) not in (None, ""):
            return compact_space(str(localized[key]))
    return compact_space(str(payload.get(key) or payload.get("title") or ""))


def official_country_name(country: dict[str, Any]) -> str:
    key = compact_space(country.get("key"))
    return ISO_COUNTRY_MAP.get(key, translated_value(country, "title") or key)


def official_country_candidates(countries_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    countries: list[dict[str, Any]] = []
    for region in countries_payload:
        for country in region.get("countries") or []:
            key = compact_space(country.get("key"))
            if key in SKIP_COUNTRY_CODES:
                continue
            if country.get("isActive") and country.get("isVisibleToOtherMarkets"):
                countries.append(country)
            elif key == ORIGIN_MARKET:
                countries.append(country)
    return sorted(countries, key=lambda item: official_country_name(item))


def official_api_url(path: str) -> str:
    return f"{API_BASE_URL}{path}"


def fetch_official_merchants(country_code: str) -> list[dict[str, Any]]:
    url = official_api_url(f"/api/country/{country_code}/merchants?origin={urllib.parse.quote(ORIGIN_MARKET)}")
    payload = http_json(url, retries=4)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected merchant payload for {country_code}")
    return payload


def official_merchant_rows(merchant: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    if merchant.get("isMerchantGroup") and isinstance(merchant.get("merchants"), list):
        rows = [(child, merchant) for child in merchant["merchants"] if child.get("showMerchant", True)]
        if rows:
            return rows
    return [(merchant, None)]


def parse_district(address: str) -> str | None:
    parts = [compact_space(part) for part in address.split(",") if compact_space(part)]
    for part in reversed(parts):
        if re.search(r"\b(?:dist\.?|district|ward|borough|arrondissement)\b", part, re.IGNORECASE):
            return part
    return None


def official_full_address(address: str, city: str, postcode: str, country: str) -> str:
    parts = [address, city, postcode, country]
    deduped: list[str] = []
    for part in parts:
        cleaned = compact_space(str(part or "")).strip(" ,")
        if cleaned and (not deduped or cleaned.lower() != deduped[-1].lower()):
            deduped.append(cleaned)
    return ", ".join(deduped)


def build_record_from_official_api(
    country: dict[str, Any],
    merchant: dict[str, Any],
    parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    country_code = compact_space(country.get("key"))
    country_name = official_country_name(country)
    city_obj = merchant.get("city") or {}
    cuisine_obj = merchant.get("cuisine") or {}
    business_data = merchant.get("businessData") or {}

    name = translated_value(merchant, "name")
    address = translated_value(merchant, "address")
    postcode = compact_space(str(translated_value(merchant, "postcode") or merchant.get("postcode") or ""))
    city = translated_value(city_obj, "title")
    cuisine = translated_value(cuisine_obj, "title")
    website = compact_space(business_data.get("website"))
    phone = compact_space(business_data.get("phone"))
    map_url = compact_space(merchant.get("googleMapsUrl"))
    lat, lng = parse_google_map_coordinates(map_url, resolve_short_urls=False)

    full_address = official_full_address(address, city, postcode, country_name)
    record_id = f"amex-global-{country_slug(country_name)}-{record_slug(name)}"
    source_record_url = official_api_url(
        f"/api/country/{urllib.parse.quote(country_code)}/merchants?origin={urllib.parse.quote(ORIGIN_MARKET)}"
    )

    search_parts = [
        name,
        address,
        city,
        parse_district(address),
        country_name,
        cuisine,
        phone,
        parent and translated_value(parent, "name"),
    ]

    return {
        "id": record_id,
        "source": "Amex Platinum Dining",
        "source_url": OFFICIAL_PAGE_URL,
        "source_record_url": f"{source_record_url}#{merchant.get('id')}",
        "source_merchant_id": merchant.get("id"),
        "source_country_code": country_code,
        "source_parent_merchant_id": parent.get("id") if parent else None,
        "source_parent_merchant_name": translated_value(parent, "name") if parent else None,
        "country": country_name,
        "region": city or None,
        "city": city or None,
        "district": parse_district(address),
        "name": name,
        "cuisines": [cuisine] if cuisine else [],
        "source_localized_address": full_address,
        "source_google_map_url": map_url or None,
        "lat": lat,
        "lng": lng,
        "coordinate_source": "source_google_map_url" if (lat is not None and lng is not None) else None,
        "coordinate_confidence": "source_map_verified" if (lat is not None and lng is not None) else "none",
        "map_pin_note": "Pin comes from the official Amex map link for this venue." if (lat is not None and lng is not None) else None,
        "website_url": website or None,
        "phone": phone or None,
        "external_signals": {},
        "search_text": " ".join(part.lower() for part in search_parts if part),
        "is_new": bool(business_data.get("isNew") or merchant.get("isNew")),
        "is_in_hotel": bool(business_data.get("isInHotel") or merchant.get("isInHotel")),
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


def fetch_official_records(limit: int = 0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    countries_payload = http_json(COUNTRIES_API_URL, retries=4)
    if not isinstance(countries_payload, list):
        raise RuntimeError("Unexpected countries payload from official Amex API")

    countries = official_country_candidates(countries_payload)
    records: list[dict[str, Any]] = []
    top_level_counts: dict[str, int] = {}
    expanded_counts: dict[str, int] = {}

    for country in countries:
        country_code = country["key"]
        country_name = official_country_name(country)
        merchants = fetch_official_merchants(country_code)
        top_level_counts[country_name] = len(merchants)
        for merchant in merchants:
            for row, parent in official_merchant_rows(merchant):
                records.append(build_record_from_official_api(country, row, parent))
                if limit and len(records) >= limit:
                    expanded_counts[country_name] = expanded_counts.get(country_name, 0) + 1
                    return records, {
                        "countries": [official_country_name(item) for item in countries],
                        "top_level_counts": top_level_counts,
                        "expanded_counts": expanded_counts,
                    }
                expanded_counts[country_name] = expanded_counts.get(country_name, 0) + 1
        time.sleep(0.1)

    return records, {
        "countries": [official_country_name(item) for item in countries],
        "top_level_counts": top_level_counts,
        "expanded_counts": expanded_counts,
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
        for r in sorted(added, key=lambda x: (x.get("country") or "", x.get("city") or "", x.get("name") or "")):
            print(f"  + {r['name']}  ({r['city']}, {r['country']})")

    if removed:
        print("\nREMOVED:")
        for r in sorted(removed, key=lambda x: (x.get("country") or "", x.get("city") or "", x.get("name") or "")):
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

    # ── 1. Fetch current restaurant data from the official Amex app API ──
    records, official_stats = fetch_official_records(limit=args.limit)
    failed: list[str] = []

    print(
        f"Official Amex API: {len(official_stats['countries'])} non-Japan countries, "
        f"{sum(official_stats['top_level_counts'].values())} top-level listings, "
        f"{len(records)} expanded restaurant records",
        file=sys.stderr,
    )

    if args.limit:
        print(f"(limited to {args.limit} expanded records for testing)", file=sys.stderr)

    records, dedupe_stats = dedupe_records(records)

    geocode_cache: dict[str, Any] = {}
    if GEOCODE_CACHE_PATH.exists():
        geocode_cache = json.loads(GEOCODE_CACHE_PATH.read_text())
    google_ratings: dict[str, Any] = {}
    if GOOGLE_RATINGS_PATH.exists():
        google_ratings = json.loads(GOOGLE_RATINGS_PATH.read_text())

    corrected = 0
    hidden = 0
    for record in records:
        if record.get("source_merchant_id"):
            continue
        before = (record.get("lat"), record.get("lng"), record.get("coordinate_confidence"))
        validate_record_coordinates(record, geocode_cache, google_ratings)
        after = (record.get("lat"), record.get("lng"), record.get("coordinate_confidence"))
        if before != after:
            if after[0] is None or after[1] is None:
                hidden += 1
            else:
                corrected += 1

    # ── 3. Apply manual overrides and compute stats ───────────────────
    fetched_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

    # ── Disambiguate IDs first (before applying overrides) ──
    from collections import Counter
    raw_duplicate_ids = count_duplicate_values([r["id"] for r in records])
    reassigned_ids = assign_unique_record_ids(records)
    remaining_duplicate_ids = count_duplicate_values([r["id"] for r in records])

    # ── Apply coordinate overrides (manually verified fixes that survive re-scrapes) ──
    if OVERRIDES_PATH.exists():
        overrides = json.loads(OVERRIDES_PATH.read_text())
        applied = 0
        for r in records:
            if r["id"] in overrides:
                fix = overrides[r["id"]]
                r["lat"] = fix["lat"]
                r["lng"] = fix["lng"]
                r["coordinate_source"] = "manual_override"
                r["coordinate_confidence"] = "manual_verified"
                r["map_pin_note"] = (
                    "Pin is manually verified and stored as a coordinate override for this venue."
                )
                applied += 1
        if applied:
            print(f"Applied {applied} coordinate override(s) from {OVERRIDES_PATH.name}")
    by_country = Counter(r["country"] for r in records)
    mapped = sum(1 for r in records if r.get("lat") is not None and r.get("lng") is not None)
    print(f"\nCoverage: {mapped}/{len(records)} records have coordinates")
    if corrected or hidden:
        print(f"Coordinate validation: {corrected} corrected, {hidden} hidden pending verification")
    if dedupe_stats["removed_count"]:
        print(
            "Deduplication: "
            f"removed {dedupe_stats['removed_count']} records "
            f"({dedupe_stats['duplicate_source_urls']} exact URL duplicates, "
            f"{dedupe_stats['duplicate_fingerprints']} duplicate venue fingerprints)"
        )
        if dedupe_stats["removed_by_country"]:
            top_countries = list(dedupe_stats["removed_by_country"].items())[:5]
            print("Top dedupe countries:")
            for country, count in top_countries:
                print(f"  {country}: {count}")
    if raw_duplicate_ids or reassigned_ids:
        print(
            "ID collisions: "
            f"{raw_duplicate_ids} duplicate base ids before write, "
            f"{reassigned_ids} records reassigned, "
            f"{remaining_duplicate_ids} duplicate ids remain"
        )
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

    OUTPUT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} records → {OUTPUT_PATH}")

    SNAPSHOT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")

    meta = {
        "fetched_at": fetched_at,
        "record_count": len(records),
        "mapped_count": mapped,
        "source_url": OFFICIAL_PAGE_URL,
        "api_url": API_BASE_URL,
        "origin_market": ORIGIN_MARKET,
        "countries": dict(sorted(by_country.items())),
        "official_top_level_counts": dict(sorted(official_stats["top_level_counts"].items())),
        "official_expanded_counts": dict(sorted(official_stats["expanded_counts"].items())),
        "failed_count": len(failed),
    }
    SOURCE_META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote metadata → {SOURCE_META_PATH}")
    print(f"\nRun again with --diff to detect changes on next scrape.")


if __name__ == "__main__":
    main()
