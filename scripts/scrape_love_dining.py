#!/usr/bin/env python3
"""
Scrape Amex Singapore Love Dining restaurants and hotel outlets.

Usage:
    python3 scripts/scrape_love_dining.py           # full scrape → data/love-dining.json
    python3 scripts/scrape_love_dining.py --dry-run  # scrape but don't write, print summary
    python3 scripts/scrape_love_dining.py --diff     # compare against existing file
    python3 scripts/scrape_love_dining.py --no-geocode  # skip geocoding pass
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

RESTAURANTS_URL = "https://www.americanexpress.com/sg/benefits/love-dining/love-restaurants.html"
HOTELS_URL = "https://www.americanexpress.com/sg/benefits/love-dining/love-dining-hotels.html"
RESTAURANTS_TNC_URL = "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Restaurants_TnCs.pdf"
HOTELS_TNC_URL = "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Hotels_TnC.pdf"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "love-dining.json"
META_PATH = Path(__file__).parent.parent / "data" / "love-dining-source.json"
GEOCODE_CACHE_PATH = Path(__file__).parent.parent / "data" / "love-dining-geocode-cache.json"

CONTEXT_OPTS: dict[str, Any] = {
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "viewport": {"width": 1280, "height": 900},
    "locale": "en-SG",
}

# Restaurants that are closed/leaving — keep in data but flag
CLOSING_NOTES: dict[str, str] = {
    "Jia He Grand Chinese Restaurant": "Not eligible from 26 April 2026",
    "Quenino": "Permanently closed from 1 May 2026",
}

PRESERVED_ENRICHMENT_FIELDS = ("lat", "lng")


def normalize_inline_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": CONTEXT_OPTS["user_agent"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def phone_count(phone: str | None) -> int:
    normalized = normalize_inline_text(phone)
    if not normalized:
        return 0
    return len([part for part in re.split(r"\s*/\s*", normalized) if part])


def repeated_name_in_notes(name: str | None, notes: str | None) -> bool:
    normalized_name = normalize_inline_text(name).lower()
    normalized_notes = normalize_inline_text(notes).lower()
    if not normalized_name or not normalized_notes:
        return False
    return normalized_notes.split(normalized_name).__len__() - 1 >= 2


def address_block_count(address: str | None) -> int:
    normalized = normalize_inline_text(address)
    if not normalized:
        return 0
    postal_matches = re.findall(r"\b\d{6}\b", normalized)
    street_matches = re.findall(
        r"\b\d{1,4}[A-Z]?\s+(?:[A-Za-z0-9'.&/-]+\s+){0,7}"
        r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Quay|Boulevard|Blvd|Turn|Way|"
        r"Crescent|Close|Lane|Ln|Park|Place|Walk|View|Hill|Court|Centre|Center|"
        r"Terrace|Link)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    return max(len(postal_matches), len(street_matches))


def annotate_location_metadata(record: dict) -> None:
    address = normalize_inline_text(record.get("address")).lower()
    has_branch_directory_address = "full list of locations" in address
    multi_location = (
        has_branch_directory_address
        or (
            phone_count(record.get("phone")) > 1
            and (
                repeated_name_in_notes(record.get("name"), record.get("notes"))
                or address_block_count(record.get("address")) > 1
            )
        )
    )
    if not multi_location:
        return

    record["multi_location"] = True
    record["location_pin_hidden"] = True
    record["map_pin_note"] = (
        "This Love Dining entry bundles multiple outlets into one source record, "
        "so the map pin is intentionally hidden until the branches are split cleanly."
    )


def _official_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def annotate_eligibility_metadata(record: dict) -> None:
    text = normalize_inline_text(
        f"{record.get('closing_note') or ''} {record.get('notes') or ''}"
    )
    valid_until = re.search(
        r"privileges will only be valid until (\d{1,2} [A-Za-z]+ 20\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if valid_until and (moment := _official_date(valid_until.group(1))):
        record["eligibility_status"] = "ineligible"
        record["eligibility_effective_from"] = (moment + timedelta(days=1)).date().isoformat()
        return

    change = re.search(
        r"(?:effective from|not eligible from|permanently closed from) "
        r"(\d{1,2} [A-Za-z]+ 20\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if change and (moment := _official_date(change.group(1))):
        record["eligibility_status"] = "ineligible"
        record["eligibility_effective_from"] = moment.date().isoformat()
        return

    resumed = re.search(
        r"(?:privileges (?:will )?resume|(?:will )?reopen) on (\d{1,2} [A-Za-z]+ 20\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if resumed and (moment := _official_date(resumed.group(1))):
        record["eligibility_status"] = "eligible"
        record["eligibility_effective_from"] = moment.date().isoformat()


def preserve_existing_enrichment(records: list[dict]) -> list[dict]:
    """Keep manual/geocoded enrichments when refreshing official listing fields."""
    if not OUTPUT_PATH.exists():
        return records

    existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    existing_by_id = {record["id"]: record for record in existing}
    existing_by_location: dict[tuple[str, str], list[dict]] = {}
    for record in existing:
        location_key = (
            normalize_inline_text(record.get("name")).casefold(),
            normalize_inline_text(record.get("address")).casefold(),
        )
        if all(location_key):
            existing_by_location.setdefault(location_key, []).append(record)
    for record in records:
        old = existing_by_id.get(record["id"])
        if old is None:
            location_key = (
                normalize_inline_text(record.get("name")).casefold(),
                normalize_inline_text(record.get("address")).casefold(),
            )
            candidates = existing_by_location.get(location_key, [])
            old = candidates[0] if len(candidates) == 1 else None
        if not old:
            continue
        for field in PRESERVED_ENRICHMENT_FIELDS:
            if record.get("location_pin_hidden") and field in ("lat", "lng"):
                continue
            old_value = old.get("lon") if field == "lng" and "lng" not in old else old.get(field)
            if old_value is not None and field not in record:
                record[field] = old_value
    return records


def official_record_projection(record: dict) -> dict:
    return {
        key: value
        for key, value in record.items()
        if key not in PRESERVED_ENRICHMENT_FIELDS and key not in {"lat", "lng", "lon"}
    }


def build_meta(
    records: list[dict],
    checked_at: str,
    *,
    mark_reviewed: bool = False,
    mark_records_reviewed: bool = False,
    mark_terms_reviewed: bool = False,
) -> dict:
    restaurants = [record for record in records if record.get("type") == "restaurant"]
    hotels = [record for record in records if record.get("type") == "hotel"]
    official_records = [official_record_projection(record) for record in records]
    digest_source = json.dumps(official_records, ensure_ascii=False, sort_keys=True).encode("utf-8")
    records_sha256 = hashlib.sha256(digest_source).hexdigest()
    terms_hashes = {
        "restaurants": sha256_hex(fetch_bytes(RESTAURANTS_TNC_URL)),
        "hotels": sha256_hex(fetch_bytes(HOTELS_TNC_URL)),
    }
    previous_meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    reviewed_terms_hashes = previous_meta.get("reviewed_terms_hashes") or terms_hashes
    reviewed_records_sha256 = previous_meta.get("reviewed_records_sha256") or records_sha256
    terms_reviewed_at = previous_meta.get("terms_reviewed_at") or checked_at
    records_reviewed_at = previous_meta.get("records_reviewed_at") or checked_at

    if mark_reviewed or mark_terms_reviewed:
        reviewed_terms_hashes = terms_hashes
        terms_reviewed_at = checked_at
    if mark_reviewed or mark_records_reviewed:
        reviewed_records_sha256 = records_sha256
        records_reviewed_at = checked_at

    major_change_reasons: list[str] = []
    changed_terms = [
        key for key, value in terms_hashes.items()
        if reviewed_terms_hashes.get(key) and reviewed_terms_hashes.get(key) != value
    ]
    if changed_terms:
        major_change_reasons.append(f"Love Dining T&C PDF changed: {', '.join(changed_terms)}")
    if reviewed_records_sha256 and reviewed_records_sha256 != records_sha256:
        major_change_reasons.append("Official Love Dining listing content changed")

    manual_review_required = bool(major_change_reasons)
    return {
        "dataset": "love_dining",
        "program": "American Express Love Dining Singapore",
        "last_checked_at": checked_at,
        "record_count": len(records),
        "restaurant_count": len(restaurants),
        "hotel_outlet_count": len(hotels),
        "records_sha256": records_sha256,
        "reviewed_records_sha256": reviewed_records_sha256,
        "records_reviewed_at": records_reviewed_at,
        "terms_hashes": terms_hashes,
        "reviewed_terms_hashes": reviewed_terms_hashes,
        "terms_reviewed_at": terms_reviewed_at,
        "manual_review_required": manual_review_required,
        "major_change_reasons": major_change_reasons,
        "official_pages": {
            "restaurants": RESTAURANTS_URL,
            "hotels": HOTELS_URL,
        },
        "terms": {
            "restaurants": RESTAURANTS_TNC_URL,
            "hotels": HOTELS_TNC_URL,
        },
        "source_notes": [
            "Restaurant cards use the official Amex Love Dining listing for outlet notes, address, phone, and source links.",
            "Promo rules use the official Love Dining restaurant and hotel T&C PDFs.",
            "Google ratings and AI summaries are enrichment fields and are not the source of truth for Amex benefit eligibility.",
        ],
    }


# ─── Playwright helpers ────────────────────────────────────────────────────────

def load_and_expand(page: Page, url: str) -> str:
    """Load a listing page, click all Details buttons, return full page text."""
    print(f"  Loading {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5_000)

    details_buttons = page.query_selector_all("text=Details")
    print(f"  Expanding {len(details_buttons)} sections...")
    for btn in details_buttons:
        try:
            btn.click()
            page.wait_for_timeout(150)
        except Exception:
            pass
    page.wait_for_timeout(2_000)
    return page.inner_text("body")


# ─── Parsing: Restaurants ──────────────────────────────────────────────────────

def parse_restaurants(text: str) -> list[dict]:
    """Parse the expanded restaurant listing page text into records."""
    # Find the start of the restaurant partners section
    start = text.find("Love Dining @ Restaurants Partners")
    if start >= 0:
        text = text[start:]
    # Trim footer
    end = text.find("Your Love Dining Benefits")
    if end >= 0:
        text = text[:end]

    records: list[dict] = []

    # Split on category headers we know
    # Categories: Asian, Contemporary, Western
    # Each restaurant block looks like:
    #   NAME\nDetails\n[optional note]\nCuisine: ...\nAddress:\n...\nFind on map\nTel: ...\nVisit Website\n[reservation note]\nTerms and Conditions
    current_cuisine_cat = ""
    cat_re = re.compile(r"^(Asian|Contemporary|Western)$", re.MULTILINE)

    # Work through line by line to identify restaurant blocks
    lines = [l.strip() for l in text.splitlines()]
    # Remove empty lines for easier processing
    non_empty = [l for l in lines if l]

    i = 0
    while i < len(non_empty):
        line = non_empty[i]

        # Track cuisine category header
        if cat_re.match(line):
            current_cuisine_cat = line
            i += 1
            continue

        # Detect restaurant name — preceded by a "Details" on the next non-empty line
        if i + 1 < len(non_empty) and non_empty[i + 1] == "Details":
            name = line
            i += 2  # skip name + "Details"

            cuisine = ""
            address_lines: list[str] = []
            phones: list[str] = []
            website = ""
            notes: list[str] = []
            hours: list[str] = []

            # Now consume lines until "Terms and Conditions" or next restaurant name
            while i < len(non_empty):
                l = non_empty[i]
                if l == "Terms and Conditions":
                    i += 1
                    break
                if l == "Find on map":
                    i += 1
                    continue
                if l == "Visit Website":
                    i += 1
                    continue
                if l.startswith("Cuisine:"):
                    cuisine = l.replace("Cuisine:", "").strip()
                    i += 1
                    continue
                if l == "Address:":
                    i += 1
                    # Collect address lines until next "Find on map" or known keyword
                    while i < len(non_empty):
                        al = non_empty[i]
                        if al in ("Find on map", "Tel:", "Visit Website", "Terms and Conditions", "Cuisine:", "Address:"):
                            break
                        if al.startswith("Tel:") or al.startswith("Opening Hours:"):
                            break
                        address_lines.append(al)
                        i += 1
                    continue
                if l.startswith("Tel:") or l.startswith("Tel "):
                    phones.append(l.split(":", 1)[1].strip())
                    i += 1
                    continue
                if l == "Opening Hours:":
                    i += 1
                    while i < len(non_empty):
                        hl = non_empty[i]
                        if hl in ("Address:", "Tel:", "Find on map", "Visit Website", "Terms and Conditions", "Cuisine:"):
                            break
                        hours.append(hl)
                        i += 1
                    continue
                # Treat everything else as a note/description
                if l and not l.startswith("*") and l not in ("Details",):
                    notes.append(l)
                i += 1

            address = normalize_inline_text(" ".join(address_lines))

            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            record: dict = {
                "id": f"love-{slug}",
                "name": name,
                "type": "restaurant",
                "cuisine_category": current_cuisine_cat,
                "cuisine": cuisine,
                "address": address,
                "city": "Singapore",
                "country": "Singapore",
                "phone": normalize_inline_text(" / ".join(phones)),
                "opening_hours": normalize_inline_text("; ".join(hours) if hours else ""),
                "notes": normalize_inline_text(" ".join(notes) if notes else ""),
                "source": "Amex Love Dining",
                "source_url": RESTAURANTS_URL,
                "terms_url": RESTAURANTS_TNC_URL,
            }
            if name in CLOSING_NOTES:
                record["closing_note"] = CLOSING_NOTES[name]

            records.append(record)
            continue

        i += 1

    return records


# ─── Parsing: Hotels ──────────────────────────────────────────────────────────

def parse_hotels(text: str) -> list[dict]:
    """Parse the expanded hotel listing page text into records."""
    start = text.find("Love Dining @ Hotels Partners")
    if start >= 0:
        text = text[start:]
    end = text.find("Love Dining @ Hotels")
    # Make sure we're not cutting too early
    if end >= 0 and end < 100:
        end = text.find("Love Dining @ Hotels", end + 10)
    # Trim footer
    footer = text.find("GET AN AMERICAN EXPRESS CARD")
    if footer >= 0:
        text = text[:footer]

    records: list[dict] = []
    lines = [l.strip() for l in text.splitlines()]
    non_empty = [l for l in lines if l]

    current_hotel = ""
    current_hotel_address = ""

    i = 0
    while i < len(non_empty):
        line = non_empty[i]

        # Hotel headings are followed immediately by the property's Singapore
        # postal address. This preserves the source label when Amex renames or
        # adds a hotel instead of leaking outlets into the previous hotel block.
        next_line = non_empty[i + 1] if i + 1 < len(non_empty) else ""
        if re.search(r"\bSingapore\s+\d{6}\b", normalize_inline_text(next_line)):
            current_hotel = line
            current_hotel_address = next_line
            i += 2
            continue

        # Detect outlet name — next line is "Details"
        if i + 1 < len(non_empty) and non_empty[i + 1] == "Details":
            if not current_hotel:
                raise ValueError(f"hotel outlet appears before a hotel heading: {line}")
            outlet_name = line
            i += 2  # skip outlet name + "Details"

            cuisine = ""
            address_lines: list[str] = []
            phones: list[str] = []
            hours: list[str] = []
            notes: list[str] = []

            while i < len(non_empty):
                l = non_empty[i]
                if l == "Terms and Conditions":
                    i += 1
                    break
                if l in ("Find on map", "Visit Website"):
                    i += 1
                    continue
                if l.startswith("Cuisine:"):
                    cuisine = l.replace("Cuisine:", "").strip()
                    i += 1
                    continue
                if l == "Opening Hours:":
                    i += 1
                    while i < len(non_empty):
                        hl = non_empty[i]
                        if hl in ("Address:", "Tel:", "Find on map", "Visit Website",
                                  "Terms and Conditions", "Cuisine:"):
                            break
                        hours.append(hl)
                        i += 1
                    continue
                if l == "Address:":
                    i += 1
                    while i < len(non_empty):
                        al = non_empty[i]
                        if al in ("Find on map", "Tel:", "Visit Website",
                                  "Terms and Conditions", "Cuisine:", "Address:", "Opening Hours:"):
                            break
                        if al.startswith("Tel:") or al.startswith("Opening Hours:"):
                            break
                        address_lines.append(al)
                        i += 1
                    continue
                if l.startswith("Tel:") or l.startswith("Tel "):
                    phones.append(l.split(":", 1)[1].strip())
                    i += 1
                    continue
                if l and l not in ("Details",):
                    notes.append(l)
                i += 1

            address = normalize_inline_text(" ".join(address_lines)) or normalize_inline_text(current_hotel_address)

            slug = re.sub(r"[^a-z0-9]+", "-", f"{current_hotel}-{outlet_name}".lower()).strip("-")
            record: dict = {
                "id": f"love-{slug}",
                "name": outlet_name,
                "hotel": current_hotel,
                "type": "hotel",
                "cuisine": cuisine,
                "address": address,
                "city": "Singapore",
                "country": "Singapore",
                "phone": normalize_inline_text(" / ".join(phones)),
                "opening_hours": normalize_inline_text("; ".join(hours) if hours else ""),
                "notes": normalize_inline_text(" ".join(notes) if notes else ""),
                "source": "Amex Love Dining",
                "source_url": HOTELS_URL,
                "terms_url": HOTELS_TNC_URL,
            }
            records.append(record)
            continue

        i += 1

    return records


# ─── Geocoding ────────────────────────────────────────────────────────────────

def _nominatim(query: str) -> tuple[float, float] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1&countrycodes=sg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "amex-dining-map/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


def geocode_address(address: str, cache: dict) -> tuple[float, float] | None:
    """Geocode a Singapore address using Nominatim. Returns (lat, lng) or None.

    Tries multiple strategies:
    1. Singapore postal code (most reliable)
    2. First address fragment before second location (for multi-location venues)
    3. Street number + street name
    4. Full address
    """
    if address in cache:
        return cache[address]

    # Strategy 1: extract postal code (6 digits after "Singapore")
    postal = re.search(r"Singapore\s+(\d{6})", address)
    if not postal:
        postal = re.search(r"\b(\d{6})\b", address)
    if postal:
        result = _nominatim(f"Singapore {postal.group(1)}")
        if result:
            cache[address] = list(result)
            return result
        time.sleep(1.1)

    # Strategy 2: take only the first address block (before second location)
    # Multi-location addresses have two addresses concatenated
    first_addr = re.split(r"(?<=\d{6})\s+\d+\s", address)[0].strip()
    if first_addr != address:
        result = _nominatim(f"{first_addr}, Singapore")
        if result:
            cache[address] = list(result)
            return result
        time.sleep(1.1)

    # Strategy 3: full address
    result = _nominatim(f"{address}, Singapore")
    if result:
        cache[address] = list(result)
        return result

    cache[address] = None
    return None


def geocode_all(records: list[dict], skip: bool = False) -> list[dict]:
    """Add lat/lng to every record. Uses a file cache to avoid re-fetching."""
    if skip:
        return records

    cache: dict = {}
    if GEOCODE_CACHE_PATH.exists():
        cache = json.loads(GEOCODE_CACHE_PATH.read_text())

    total = len(records)
    for i, rec in enumerate(records, 1):
        if rec.get("location_pin_hidden"):
            rec.pop("lat", None)
            rec.pop("lng", None)
            rec.pop("lon", None)
            print(f"  [{i}/{total}] {rec['name']} — multiple outlet bundle, skipping single-pin geocode")
            continue
        if rec.get("lat") and (rec.get("lng") or rec.get("lon")):
            if "lng" not in rec and rec.get("lon") is not None:
                rec["lng"] = rec.pop("lon")
            continue
        addr = rec.get("address", "")
        if not addr:
            print(f"  [{i}/{total}] {rec['name']} — no address, skipping geocode")
            continue

        result = geocode_address(addr, cache)
        if result:
            rec["lat"] = result[0]
            rec["lng"] = result[1]
            print(f"  [{i}/{total}] {rec['name']} → {result[0]:.4f}, {result[1]:.4f}")
        else:
            print(f"  [{i}/{total}] {rec['name']} — geocode failed for: {addr}")
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

    GEOCODE_CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
    return records


# ─── Diff ─────────────────────────────────────────────────────────────────────

def run_diff(new_records: list[dict]) -> None:
    if not OUTPUT_PATH.exists():
        print("No existing file to diff against.")
        return
    old = json.loads(OUTPUT_PATH.read_text())
    old_names = {r["name"] for r in old}
    new_names = {r["name"] for r in new_records}
    old_by_id = {r["id"]: r for r in old}
    new_by_id = {r["id"]: r for r in new_records}
    added = new_names - old_names
    removed = old_names - new_names
    changed_fields = ("notes", "closing_note", "opening_hours", "phone", "address", "cuisine", "terms_url", "source_url")
    changed: list[tuple[str, list[str]]] = []
    for record_id in sorted(set(old_by_id) & set(new_by_id)):
        fields = [
            field for field in changed_fields
            if normalize_inline_text(str(old_by_id[record_id].get(field, "")))
            != normalize_inline_text(str(new_by_id[record_id].get(field, "")))
        ]
        if fields:
            changed.append((new_by_id[record_id]["name"], fields))

    print(f"\nDiff: +{len(added)} added, -{len(removed)} removed, {len(changed)} changed, {len(new_names)} unique names")
    for n in sorted(added):
        print(f"  + {n}")
    for n in sorted(removed):
        print(f"  - {n}")
    for name, fields in changed[:25]:
        print(f"  ~ {name}: {', '.join(fields)}")
    if len(changed) > 25:
        print(f"  ... and {len(changed) - 25} more changed records")


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Amex Love Dining Singapore")
    p.add_argument("--dry-run", action="store_true", help="Scrape, print summary, don't write")
    p.add_argument("--diff", action="store_true", help="Show additions/removals vs existing file")
    p.add_argument("--no-geocode", action="store_true", help="Skip geocoding pass")
    p.add_argument("--mark-reviewed", action="store_true", help="Mark current official records and T&C PDFs as reviewed")
    p.add_argument(
        "--mark-records-reviewed",
        action="store_true",
        help="Mark only the current official listing records as reviewed",
    )
    p.add_argument(
        "--mark-terms-reviewed",
        action="store_true",
        help="Mark only the current restaurant and hotel T&C PDFs as reviewed",
    )
    return p.parse_args()


def main() -> None:
    from playwright.sync_api import sync_playwright

    args = parse_args()

    print("Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(**CONTEXT_OPTS)
        page = ctx.new_page()

        rest_text = load_and_expand(page, RESTAURANTS_URL)
        hotel_text = load_and_expand(page, HOTELS_URL)
        browser.close()

    print("\nParsing restaurants...")
    restaurants = parse_restaurants(rest_text)
    print(f"  → {len(restaurants)} restaurants")

    print("Parsing hotel outlets...")
    hotels = parse_hotels(hotel_text)
    print(f"  → {len(hotels)} hotel outlets")

    all_records = restaurants + hotels
    for record in all_records:
        annotate_location_metadata(record)
        annotate_eligibility_metadata(record)
    checked_at = now_utc_iso()
    print(f"\nTotal: {len(all_records)} venues")

    if args.dry_run:
        print("\nRestaurants:")
        for r in restaurants:
            print(f"  {r['name']} | {r['cuisine']} | {r['address']} | {r['phone']}")
        print("\nHotel outlets:")
        for r in hotels:
            print(f"  [{r['hotel']}] {r['name']} | {r['cuisine']} | {r['address']} | {r['phone']}")
        return

    if args.diff:
        run_diff(all_records)
        return

    all_records = preserve_existing_enrichment(all_records)

    print("\nGeocoding...")
    all_records = geocode_all(all_records, skip=args.no_geocode)

    geocoded = sum(1 for r in all_records if r.get("lat"))
    print(f"\nGeocoded: {geocoded}/{len(all_records)}")

    OUTPUT_PATH.write_text(json.dumps(all_records, indent=2, ensure_ascii=False) + "\n")
    META_PATH.write_text(
        json.dumps(
            build_meta(
                all_records,
                checked_at,
                mark_reviewed=args.mark_reviewed,
                mark_records_reviewed=args.mark_records_reviewed,
                mark_terms_reviewed=args.mark_terms_reviewed,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"Written → {OUTPUT_PATH}")
    print(f"Written → {META_PATH}")


if __name__ == "__main__":
    main()
