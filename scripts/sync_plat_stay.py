#!/usr/bin/env python3
"""Sync the Plat Stay dataset from the official Amex short-link PDF."""

from __future__ import annotations

import difflib
import hashlib
import html
import http.client
import json
import math
import os
import re
import socket
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
KML_DIR = DATA_DIR / "kml"
JSON_PATH = DATA_DIR / "plat-stays.json"
GEOJSON_PATH = DATA_DIR / "plat-stays.geojson"
KML_PATH = KML_DIR / "plat-stays-all.kml"
SOURCE_META_PATH = DATA_DIR / "plat-stay-source.json"
GEOCODE_CACHE_PATH = DATA_DIR / "plat_stay_geocode_cache.json"
GEOAPIFY_CACHE_PATH = DATA_DIR / "plat_stay_geoapify_cache.json"
TOMTOM_CACHE_PATH = DATA_DIR / "plat_stay_tomtom_cache.json"
MANUAL_OVERRIDE_PATH = DATA_DIR / "plat_stay_manual_overrides.json"
GOOGLE_RATINGS_PATH = DATA_DIR / "google-maps-ratings.json"

CANONICAL_SOURCE_URL = "https://go.amex/platstay"
USER_AGENT = "AmexBenefitsExplorer/0.1 (+https://kooexperience.com/amex-dining-map/)"
DEFAULT_BLACKOUT_YEAR = 2026
GEOAPIFY_API_KEY = os.environ.get("GEOAPIFY_API_KEY")
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY")
PDF_FETCH_TIMEOUTS = (30, 60, 90)
MIN_PDF_BYTES = 1024

COUNTRY_ALIASES = {
    "singapore": "Singapore",
    "malaysia": "Malaysia",
    "indonesia": "Indonesia",
    "thailand": "Thailand",
    "vietnam": "Vietnam",
    "maldives": "Maldives",
    "mexico": "Mexico",
    "méxico": "Mexico",
    "united arab emirates": "United Arab Emirates",
    "qatar": "Qatar",
    "qater": "Qatar",
    "greece": "Greece",
    "republic of korea": "South Korea",
    "korea-republic of": "South Korea",
    "japan": "Japan",
    "p. r. china": "China",
    "prc": "China",
    "china": "China",
    "bahrain": "Bahrain",
    "australia": "Australia",
    "germany": "Germany",
    "turkey": "Turkey",
}

COUNTRY_PRIORITY = sorted(COUNTRY_ALIASES, key=len, reverse=True)
COUNTRY_CODES = {
    "Australia": "au",
    "Bahrain": "bh",
    "China": "cn",
    "Germany": "de",
    "Greece": "gr",
    "Indonesia": "id",
    "Japan": "jp",
    "Malaysia": "my",
    "Maldives": "mv",
    "Mexico": "mx",
    "Qatar": "qa",
    "Singapore": "sg",
    "South Korea": "kr",
    "Thailand": "th",
    "Turkey": "tr",
    "United Arab Emirates": "ae",
    "Vietnam": "vn",
}

COUNTRY_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "Australia": (-44.5, -10.0, 112.0, 154.0),
    "Bahrain": (25.4, 26.4, 50.3, 50.9),
    "China": (18.0, 54.0, 73.0, 135.0),
    "Germany": (47.0, 56.0, 5.0, 16.0),
    "Greece": (34.0, 42.0, 19.0, 30.0),
    "Indonesia": (-11.5, 6.5, 95.0, 141.5),
    "Japan": (24.0, 46.5, 123.0, 146.5),
    "Malaysia": (0.5, 7.5, 99.0, 120.0),
    "Maldives": (-1.0, 8.0, 72.0, 74.5),
    "Mexico": (14.0, 33.0, -119.0, -86.0),
    "Qatar": (24.4, 26.3, 50.6, 51.8),
    "Singapore": (1.1, 1.5, 103.5, 104.1),
    "South Korea": (33.0, 39.7, 124.0, 132.0),
    "Thailand": (5.0, 21.0, 97.0, 106.0),
    "Turkey": (35.0, 43.0, 25.0, 45.0),
    "United Arab Emirates": (22.5, 26.5, 51.0, 56.5),
    "Vietnam": (8.0, 24.0, 102.0, 110.5),
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

GOOGLE_PLACE_ALIGNMENT_KM = 1.5
GOOGLE_NAME_ONLY_ALIGNMENT_KM = 25.0


@dataclass
class ParsedBlock:
    name: str
    address: str
    eligible_room_type: str
    blackout_raw: str
    blackout_items: list[str]
    reservation_raw: str
    reservation_phone: str | None
    reservation_email: str | None
    reservation_mode: str


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def previous_resolved_source_url() -> str | None:
    try:
        previous_meta = load_json(SOURCE_META_PATH, {})
    except (OSError, json.JSONDecodeError):
        return None
    resolved_url = previous_meta.get("resolved_url")
    if isinstance(resolved_url, str) and resolved_url.startswith("https://"):
        return resolved_url
    return None


def validate_pdf_bytes(body: bytes, source_url: str) -> None:
    if len(body) < MIN_PDF_BYTES:
        raise RuntimeError(f"Short PDF response from {source_url}: {len(body)} bytes")
    if not body.startswith(b"%PDF-"):
        prefix = body[:32].decode("utf-8", errors="replace").replace("\n", "\\n")
        raise RuntimeError(f"Non-PDF response from {source_url}: starts with {prefix!r}")


def fetch_pdf_once(url: str, timeout: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        resolved_url = response.geturl()
    validate_pdf_bytes(body, resolved_url)
    return body, resolved_url


def fetch_pdf(url: str) -> tuple[bytes, str]:
    candidate_urls = [url]
    resolved_url = previous_resolved_source_url()
    if resolved_url and resolved_url not in candidate_urls:
        candidate_urls.append(resolved_url)

    errors: list[str] = []
    for attempt, timeout in enumerate(PDF_FETCH_TIMEOUTS, start=1):
        for candidate_url in candidate_urls:
            try:
                return fetch_pdf_once(candidate_url, timeout)
            except (
                TimeoutError,
                socket.timeout,
                OSError,
                urllib.error.URLError,
                http.client.HTTPException,
                RuntimeError,
            ) as exc:
                message = (
                    f"{candidate_url} attempt {attempt}/{len(PDF_FETCH_TIMEOUTS)} "
                    f"timed out/failed after {timeout}s: {exc}"
                )
                errors.append(message)
                print(f"WARNING: {message}", flush=True)
        if attempt < len(PDF_FETCH_TIMEOUTS):
            time.sleep(attempt * 3)

    raise RuntimeError("Failed to fetch Plat Stay PDF after retries:\n" + "\n".join(errors))


def pdf_page_count(pdf_path: Path) -> int | None:
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    match = re.search(r"^Pages:\s+(\d+)$", result.stdout, flags=re.M)
    return int(match.group(1)) if match else None


def pdf_to_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def extract_pdf_contact_links(pdf_path: Path) -> tuple[list[str], str | None]:
    result = subprocess.run(
        ["pdftohtml", "-stdout", "-i", "-noframes", str(pdf_path)],
        capture_output=True,
        check=True,
    )
    html_text = result.stdout.decode("utf-8", errors="replace")
    hrefs = re.findall(r'href="([^"]+)"', html_text)

    collapsed: list[str] = []
    for href in hrefs:
        if not collapsed or collapsed[-1] != href:
            collapsed.append(href)

    mailto_links = [href for href in collapsed if href.startswith("mailto:")]
    booking_url = next(
        (href for href in collapsed if "reservations.frasershospitality.com" in href),
        None,
    )
    return mailto_links, booking_url


def is_hotel_header_line(line: str) -> bool:
    """Return True if this line starts a new hotel entry.

    A hotel header has a name in the name column AND a street address
    (1–4 digit house number + word, e.g. "30 Beach Road") in the address column.
    Continuation lines have city/postal values (5+ digit postal codes like
    "11100 Teluk" or "Singapore 189763") in the address column — excluded
    by the 1–4 digit constraint.
    """
    segs = line_segments(line)
    has_name = any(start < 16 for start, _ in segs)
    address_texts = [text for start, text in segs if 16 <= start < 40]
    # Match house numbers (1-4 digits) but NOT postal codes (5+ digits)
    has_street = any(re.match(r"\d{1,4}\s+[A-Za-z]", text) for text in address_texts)
    return has_name and has_street


def split_property_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()

    # Find the table header row — "Participating ... Eligible Room Type"
    header_index = next(
        (i for i, line in enumerate(lines)
         if "Participating" in line and "Eligible Room Type" in line),
        None,
    )
    # Fallback to old hardcoded anchor if header not found
    if header_index is None:
        header_index = next((i for i, line in enumerate(lines) if "The Fullerton" in line), None)

    end_index = next((i for i, line in enumerate(lines) if line.startswith("Terms and Conditions")), None)
    if header_index is None or end_index is None or end_index <= header_index:
        raise RuntimeError("Could not isolate the Plat Stay property table from the PDF text.")

    # Skip the 2-line header block and any trailing blank lines before data begins
    start_index = header_index + 2
    while start_index < end_index and not lines[start_index].strip():
        start_index += 1

    table_lines = lines[start_index:end_index]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in table_lines:
        if re.fullmatch(r"\s*\d+\s*", line):
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        # When a new hotel header line appears inside an existing block (no blank separator),
        # flush the current block and start a new one.
        if current and is_hotel_header_line(line):
            blocks.append(current)
            current = []
        current.append(line.rstrip())

    if current:
        blocks.append(current)
    return blocks


def line_segments(line: str) -> list[tuple[int, str]]:
    return [
        (match.start(), match.group(0).strip())
        for match in re.finditer(r"\S(?:.*?\S)?(?= {3,}|$)", line)
    ]


def segment_bucket(start: int) -> str:
    if start < 16:
        return "name"
    if start < 40:
        return "address"
    if start < 64:
        return "room"
    if start < 92:
        return "blackout"
    return "reservation"


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def within_country_bounds(country: str | None, lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    bounds = COUNTRY_BOUNDS.get(country or "")
    if not bounds:
        return True
    min_lat, max_lat, min_lng, max_lng = bounds
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_google_map_coordinates(url: str | None) -> tuple[float | None, float | None]:
    if not url:
        return None, None

    candidates = [url]
    parsed = urllib.parse.urlparse(url)
    should_resolve = "goo.gl" in parsed.netloc or "maps.app.goo.gl" in parsed.netloc
    if should_resolve:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=5) as response:
                redirected = response.geturl()
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
        for key in ("q", "query"):
            value = query.get(key, [None])[0]
            if not value:
                continue
            match = re.match(
                r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$",
                urllib.parse.unquote(value),
            )
            if match:
                return float(match.group(1)), float(match.group(2))

    return None, None


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
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean_whitespace(text)


def normalize_match_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def contains_normalized_text(haystack: str | None, needle: str | None) -> bool:
    haystack_normalized = normalize_match_text(haystack)
    needle_normalized = normalize_match_text(needle)
    if not haystack_normalized or not needle_normalized:
        return False
    return needle_normalized in haystack_normalized


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


def collapse_multiline(parts: list[str]) -> str:
    return clean_whitespace(" ".join(part for part in parts if part))


def collapse_blackout_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    for raw_line in lines:
        line = clean_whitespace(raw_line)
        if not line:
            continue
        if line.startswith("•") or not items:
            items.append(line)
        else:
            items[-1] = clean_whitespace(f"{items[-1]} {line}")
    return items


def normalize_reservation(lines: list[str]) -> tuple[str, str | None, str | None, str]:
    line_parts = [clean_whitespace(line) for line in lines if clean_whitespace(line)]
    if not line_parts:
        return "", None, None, "unknown"

    phone = next((part for part in line_parts if part.startswith("+")), None)
    email_candidates = [part for part in line_parts if "@" in part or part.endswith(".com")]
    email = "".join(email_candidates) if email_candidates else None

    if any("reserve your room" in part.lower() for part in line_parts):
        mode = "booking_link_prompt"
        raw = clean_whitespace(" ".join(line_parts))
        return raw, phone, None, mode

    if email:
        raw_parts = [phone] if phone else []
        raw_parts.append(email)
        return " | ".join(part for part in raw_parts if part), phone, email, "email_or_phone"

    if phone:
        return phone, phone, None, "phone"

    raw = clean_whitespace(" ".join(line_parts))
    return raw, None, None, "unknown"


def parse_block(block_lines: list[str]) -> ParsedBlock:
    buckets = {
        "name": [],
        "address": [],
        "room": [],
        "blackout": [],
        "reservation": [],
    }

    for line in block_lines:
        per_line = {key: [] for key in buckets}
        for start, text in line_segments(line):
            per_line[segment_bucket(start)].append(text)
        for key, values in per_line.items():
            if values:
                buckets[key].append(clean_whitespace(" ".join(values)))

    blackout_items = collapse_blackout_items(buckets["blackout"])
    blackout_raw = " | ".join(blackout_items)
    reservation_raw, reservation_phone, reservation_email, reservation_mode = normalize_reservation(
        buckets["reservation"]
    )

    return ParsedBlock(
        name=collapse_multiline(buckets["name"]),
        address=collapse_multiline(buckets["address"]),
        eligible_room_type=collapse_multiline(buckets["room"]),
        blackout_raw=blackout_raw,
        blackout_items=blackout_items,
        reservation_raw=reservation_raw,
        reservation_phone=reservation_phone,
        reservation_email=reservation_email,
        reservation_mode=reservation_mode,
    )


def infer_country(address: str, name: str) -> str | None:
    haystack = clean_whitespace(f"{address} {name}").lower()
    for alias in COUNTRY_PRIORITY:
        if alias in haystack:
            return COUNTRY_ALIASES[alias]
    return None


def normalize_blackout_item(item: str) -> tuple[str, bool]:
    normalized = (
        item.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("•", "")
        .strip()
    )
    tentative = "(tentative)" in normalized.lower()
    normalized = re.sub(r"\s*\((tentative)\)\s*", "", normalized, flags=re.I)
    normalized = clean_whitespace(normalized)
    return normalized, tentative


def iso_date(year: int, month_name: str, day: int) -> str:
    month = MONTHS[month_name.lower()]
    return date(year, month, day).isoformat()


def parse_blackout_item(item: str) -> tuple[dict | None, str | None]:
    normalized, tentative = normalize_blackout_item(item)
    if not normalized:
        return None, None

    match = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", normalized)
    if match:
        start_day, end_day, month_name, year = match.groups()
        return (
            {
                "start": iso_date(int(year), month_name, int(start_day)),
                "end": iso_date(int(year), month_name, int(end_day)),
                "label": normalized,
                "tentative": tentative,
            },
            None,
        )

    match = re.fullmatch(
        r"(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
        normalized,
    )
    if match:
        start_day, start_month, end_day, end_month, year = match.groups()
        year = int(year) if year else DEFAULT_BLACKOUT_YEAR
        return (
            {
                "start": iso_date(year, start_month, int(start_day)),
                "end": iso_date(year, end_month, int(end_day)),
                "label": normalized,
                "tentative": tentative,
            },
            None,
        )

    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", normalized)
    if match:
        day, month_name, year = match.groups()
        value = iso_date(int(year), month_name, int(day))
        return (
            {
                "start": value,
                "end": value,
                "label": normalized,
                "tentative": tentative,
            },
            None,
        )

    return None, normalized


def blackout_structures(items: list[str]) -> tuple[list[dict], list[str]]:
    exact_ranges: list[dict] = []
    notes: list[str] = []
    for item in items:
        exact, note = parse_blackout_item(item)
        if exact:
            exact_ranges.append(exact)
        elif note:
            notes.append(note)
    return exact_ranges, notes


def normalize_address_for_query(value: str) -> str:
    normalized = value
    replacements = {
        "P. R. China": "China",
        "PRC": "China",
        "Korea-Republic Of": "South Korea",
        "México": "Mexico",
        "Qater": "Qatar",
        "Chendu": "Chengdu",
        ".,": ",",
        " .": " ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.replace(", ,", ",")
    return normalized.strip(" ,")


def normalize_name_for_query(value: str) -> str:
    normalized = value.replace("/", " ").replace(",", " ")
    normalized = re.sub(r"\bQater\b", "Qatar", normalized, flags=re.I)
    normalized = re.sub(r"\bAustralia\b|\bBahrain\b|\bChina\b|\bGermany\b|\bIndonesia\b|\bJapan\b|\bKorea\b|\bMalaysia\b|\bThailand\b|\bTurkey\b|\bVietnam\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def infer_city_from_address(address: str, country: str | None) -> str | None:
    normalized = normalize_address_for_query(address)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    cleaned: list[str] = []
    for part in parts:
        part_lower = part.lower()
        if country and country.lower() in part_lower:
            continue
        if re.fullmatch(r"\d{4,6}", part):
            continue
        if re.fullmatch(r"\d{4,6}\s+[A-Za-z\s]+", part):
            continue
        cleaned.append(part)

    for part in reversed(cleaned):
        part_lower = part.lower()
        if any(token in part_lower for token in ["province", "district", "ward", "county", "state", "atoll", "commune"]):
            continue
        if len(part) <= 2:
            continue
        return re.sub(r"\bCity\b", "", part, flags=re.I).strip()
    return None


def query_street_parts(address: str) -> list[str]:
    normalized = normalize_address_for_query(address)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    return parts[:2]


def result_matches_query(result: dict, query: str) -> bool:
    display_name = (result.get("display_name") or "").lower()
    number_match = re.search(r"\b(\d+[A-Za-z-]*)\b", query)
    if number_match and number_match.group(1).lower() not in display_name:
        return False
    return True


def geocode_query(query: str) -> dict | None:
    params = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "q": query,
        }
    )
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload[0] if payload else None
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 30 * (2 ** attempt)
                print(f"  Nominatim 429 — waiting {wait}s before retry {attempt + 1}/3...")
                time.sleep(wait)
            else:
                raise
    print(f"  Nominatim giving up after retries for: {query!r}")
    return None


def country_code_for_name(country: str | None) -> str | None:
    if not country:
        return None
    return COUNTRY_CODES.get(country)


def split_address_components(address: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in normalize_address_for_query(address).split(",") if part.strip()]
    if not parts:
        return None, None

    first = parts[0]
    second = parts[1] if len(parts) > 1 else None

    no_match = re.fullmatch(r"(?i)no\.?\s*(\d+[A-Za-z/-]*)", first)
    if no_match:
        return no_match.group(1), second

    prefix_match = re.match(r"(?P<number>\d+[A-Za-z/-]*)\s+(?P<street>.+)", first)
    if prefix_match:
        return prefix_match.group("number"), prefix_match.group("street")

    suffix_match = re.match(r"(?P<street>.+?)\s+#?(?P<number>\d+[A-Za-z/-]*)$", first)
    if suffix_match:
        return suffix_match.group("number"), suffix_match.group("street")

    return None, first


def geoapify_search(params: dict[str, str], cache_key: str, cache: dict) -> list[dict]:
    if not GEOAPIFY_API_KEY:
        return []
    if cache_key in cache:
        return cache[cache_key] or []

    final_params = {
        **params,
        "format": "json",
        "limit": "3",
        "apiKey": GEOAPIFY_API_KEY,
    }
    url = f"https://api.geoapify.com/v1/geocode/search?{urllib.parse.urlencode(final_params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        cache[cache_key] = []
        save_json(GEOAPIFY_CACHE_PATH, cache)
        return []

    results = payload.get("results") or []
    cache[cache_key] = results
    save_json(GEOAPIFY_CACHE_PATH, cache)
    time.sleep(0.25)
    return results


def geoapify_candidates(record: dict, cache: dict) -> list[tuple[str, dict]]:
    country_code = country_code_for_name(record.get("country"))
    address = normalize_address_for_query(record["address"])
    name = normalize_name_for_query(record["name"])
    city = infer_city_from_address(address, record.get("country"))
    housenumber, street = split_address_components(address)
    candidates: list[tuple[str, dict]] = []

    filter_value = f"countrycode:{country_code}" if country_code else None

    freeform_params = {"text": clean_whitespace(f"{name}, {address}, {record.get('country') or ''}")}
    if filter_value:
        freeform_params["filter"] = filter_value
    for hit in geoapify_search(freeform_params, f"freeform::{freeform_params['text']}::{filter_value}", cache):
        candidates.append(("geoapify_freeform", hit))

    amenity_params = {"text": freeform_params["text"], "type": "amenity"}
    if filter_value:
        amenity_params["filter"] = filter_value
    for hit in geoapify_search(amenity_params, f"amenity::{amenity_params['text']}::{filter_value}", cache):
        candidates.append(("geoapify_amenity", hit))

    structured_params = {
        "name": name,
        "country": record.get("country") or "",
        "type": "amenity",
    }
    if street:
        structured_params["street"] = street
    if housenumber:
        structured_params["housenumber"] = housenumber
    if city:
        structured_params["city"] = city
    if filter_value:
        structured_params["filter"] = filter_value
    if structured_params.get("name") and (street or city):
        cache_key = "::".join(
            [
                "structured",
                structured_params.get("name", ""),
                structured_params.get("housenumber", ""),
                structured_params.get("street", ""),
                structured_params.get("city", ""),
                structured_params.get("country", ""),
                structured_params.get("filter", ""),
            ]
        )
        for hit in geoapify_search(structured_params, cache_key, cache):
            candidates.append(("geoapify_structured", hit))

    return candidates


def geoapify_name_match(record: dict, hit: dict) -> bool:
    record_name = normalize_match_text(normalize_name_for_query(record["name"]))
    hit_name = normalize_match_text(hit.get("name"))
    if not record_name or not hit_name:
        return False
    return record_name == hit_name or record_name in hit_name or hit_name in record_name


def geoapify_address_match(record: dict, hit: dict) -> bool:
    address_norm = normalize_match_text(record["address"])
    street_norm = normalize_match_text(hit.get("street"))
    housenumber_norm = normalize_match_text(hit.get("housenumber"))
    if not street_norm or street_norm not in address_norm:
        return False
    if housenumber_norm and housenumber_norm not in address_norm:
        return False
    if (hit.get("rank") or {}).get("confidence_city_level", 0) < 0.9:
        return False
    return True


def apply_geoapify_hit(record: dict, label: str, hit: dict, confidence: str, note: str) -> None:
    record["lat"] = hit.get("lat")
    record["lng"] = hit.get("lon")
    record["coordinate_source"] = label
    record["coordinate_confidence"] = confidence
    record["city"] = hit.get("city") or record.get("city")
    record["country"] = hit.get("country") or record.get("country")
    record["map_pin_note"] = note


def tomtom_search(query: str, country_code: str | None, cache: dict) -> list[dict]:
    if not TOMTOM_API_KEY:
        return []

    cache_key = f"{query}::{country_code or ''}"
    if cache_key in cache:
        return cache[cache_key] or []

    params = {
        "key": TOMTOM_API_KEY,
        "limit": "5",
        "idxSet": "POI",
        "language": "en-GB",
    }
    if country_code:
        params["countrySet"] = country_code

    url = f"https://api.tomtom.com/search/2/search/{urllib.parse.quote(query)}.json?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        cache[cache_key] = []
        save_json(TOMTOM_CACHE_PATH, cache)
        return []

    results = payload.get("results") or []
    cache[cache_key] = results
    save_json(TOMTOM_CACHE_PATH, cache)
    time.sleep(0.25)
    return results


def tomtom_name_match(record: dict, result: dict) -> bool:
    poi = result.get("poi") or {}
    name = normalize_match_text(poi.get("name"))
    record_name = normalize_match_text(normalize_name_for_query(record["name"]))
    if not name or not record_name:
        return False
    return name == record_name or name in record_name or record_name in name


def tomtom_hotel_categories(result: dict) -> bool:
    poi = result.get("poi") or {}
    categories = [value.lower() for value in (poi.get("categories") or [])]
    return any(category in {"hotel", "hotel/motel", "motel", "resort", "guest house"} for category in categories)


def tomtom_address_match(record: dict, result: dict) -> bool:
    address = normalize_match_text((result.get("address") or {}).get("freeformAddress"))
    record_address = normalize_match_text(record["address"])
    if not address or not record_address:
        return False
    return address in record_address or record_address in address


def refine_with_tomtom(record: dict, cache: dict) -> None:
    if not TOMTOM_API_KEY:
        return

    country_code = country_code_for_name(record.get("country"))
    query = clean_whitespace(
        f"{normalize_name_for_query(record['name'])}, {infer_city_from_address(record['address'], record.get('country')) or ''}, {record.get('country') or ''}"
    )
    for result in tomtom_search(query, country_code, cache):
        if not tomtom_hotel_categories(result):
            continue
        if not tomtom_name_match(record, result):
            continue

        position = result.get("position") or {}
        if position.get("lat") is None or position.get("lon") is None:
            continue

        record["lat"] = float(position["lat"])
        record["lng"] = float(position["lon"])
        record["coordinate_source"] = "tomtom_poi_match"
        record["coordinate_confidence"] = "poi_matched"
        record["city"] = (
            (result.get("address") or {}).get("municipality")
            or (result.get("address") or {}).get("countrySecondarySubdivision")
            or record.get("city")
        )
        record["map_pin_note"] = "Pin is based on an exact hotel-name POI match from TomTom. Verify the official property address before booking or arrival."
        if tomtom_address_match(record, result):
            record["coordinate_confidence"] = "poi_address_matched"
            record["map_pin_note"] = "Pin is based on a matched hotel POI and matching address from TomTom. Verify booking terms with the official Plat Stay source before reserving."
        return


def apply_manual_override(record: dict, overrides: dict[str, dict]) -> None:
    override = overrides.get(record["id"])
    if not override:
        return

    expected_name = override.get("expected_name")
    if expected_name and not contains_normalized_text(record["name"], expected_name):
        return

    expected_address_fragment = override.get("expected_address_fragment")
    if expected_address_fragment and not contains_normalized_text(record["address"], expected_address_fragment):
        return

    lat = override.get("lat")
    lng = override.get("lng")
    if lat is None or lng is None:
        return

    record["lat"] = float(lat)
    record["lng"] = float(lng)
    record["coordinate_source"] = "manual_override"
    record["coordinate_confidence"] = "manual_verified"
    record["verification_source_label"] = override.get("source_label")
    record["verification_source_url"] = override.get("source_url")
    record["verification_date"] = override.get("verified_at")
    record["verification_notes"] = override.get("notes")
    record["map_pin_note"] = (
        "Pin is manually verified and stored as an override for this property. "
        "Confirm booking terms with the official Plat Stay source before reserving."
    )
    if override.get("city"):
        record["city"] = override.get("city")
    if override.get("country"):
        record["country"] = override.get("country")


def refine_with_geoapify(record: dict, cache: dict) -> None:
    if not GEOAPIFY_API_KEY:
        return

    for label, hit in geoapify_candidates(record, cache):
        result_type = hit.get("result_type")
        if result_type == "amenity" and geoapify_name_match(record, hit):
            apply_geoapify_hit(
                record,
                label,
                hit,
                "poi_matched",
                "Pin is based on an exact hotel-name match from Geoapify. Verify booking terms with the official Plat Stay source before reserving.",
            )
            return
        if result_type in {"building", "amenity"} and geoapify_address_match(record, hit):
            apply_geoapify_hit(
                record,
                label,
                hit,
                "address_matched",
                "Pin is based on a matched street address from Geoapify. Verify the official property address before booking or arrival.",
            )
            return


def geocode_record(record: dict, cache: dict) -> None:
    if record.get("lat") is not None and record.get("lng") is not None:
        return

    normalized_address = normalize_address_for_query(record["address"])
    normalized_name = normalize_name_for_query(record["name"])
    country = record.get("country")
    city = infer_city_from_address(normalized_address, country)
    street_parts = query_street_parts(normalized_address)
    queries = [
        clean_whitespace(f"{normalized_name}, {country or ''}"),
        clean_whitespace(f"{street_parts[0]}, {city or ''}, {country or ''}") if street_parts else "",
        clean_whitespace(f"{street_parts[1]}, {city or ''}, {country or ''}") if len(street_parts) > 1 else "",
        clean_whitespace(
            f"{normalized_address}, {country}" if country and country.lower() not in normalized_address.lower() else normalized_address
        ),
        clean_whitespace(f"{normalized_name}, {normalized_address}"),
    ]

    for index, query in enumerate(query for query in queries if query):
        if query in cache:
            result = cache[query]
        else:
            result = geocode_query(query)
            cache[query] = result
            save_json(GEOCODE_CACHE_PATH, cache)
            time.sleep(1.1)

        if not result or not result_matches_query(result, query):
            continue

        record["lat"] = float(result["lat"])
        record["lng"] = float(result["lon"])
        record["coordinate_source"] = "nominatim_property_query" if index == 0 else "nominatim_address_query"
        record["coordinate_confidence"] = "approximate"
        geocoded_address = result.get("address") or {}
        record["country"] = (
            geocoded_address.get("country")
            or geocoded_address.get("country_code", "").upper()
            or record.get("country")
        )
        record["city"] = (
            geocoded_address.get("city")
            or geocoded_address.get("town")
            or geocoded_address.get("municipality")
            or geocoded_address.get("state_district")
            or geocoded_address.get("county")
            or record.get("city")
        )
        record["map_pin_note"] = "Pin is approximate and based on public geocoding. Confirm the official property address before booking or arrival."
        if record.get("breakfast_included") is None and record.get("country"):
            record["breakfast_included"] = record["country"] != "Singapore"
        if record.get("country") == "Singapore":
            record["breakfast_note"] = "Room only. Breakfast is not included for Singapore properties."
        elif record.get("country"):
            record["breakfast_note"] = "Breakfast for 2 is available at overseas properties only."
        break

    if record.get("coordinate_confidence") in {"manual_verified", "poi_matched", "poi_address_matched"}:
        return


def google_rating_candidate(record: dict, google_ratings: dict[str, dict]) -> dict | None:
    rating = google_ratings.get(record["id"])
    if not isinstance(rating, dict):
        return None

    google_name = clean_whitespace(rating.get("google_name") or "")
    if not google_name or google_name.lower() == "results":
        return None

    lat, lng = parse_google_map_coordinates(rating.get("maps_url"))
    if not within_country_bounds(record.get("country"), lat, lng):
        return None

    google_address = clean_whitespace(rating.get("google_address") or "")
    return {
        "lat": float(lat),
        "lng": float(lng),
        "google_name": google_name,
        "google_address": google_address,
        "name_ok": names_match(normalize_name_for_query(record["name"]), google_name),
        "address_ok": addresses_match(normalize_address_for_query(record["address"]), google_address),
    }


def validate_record_coordinates(record: dict, google_ratings: dict[str, dict]) -> None:
    if record.get("coordinate_confidence") == "manual_verified":
        return

    lat = record.get("lat")
    lng = record.get("lng")
    current_ok = within_country_bounds(record.get("country"), lat, lng)
    current_confidence = record.get("coordinate_confidence")
    strong_current_match = current_confidence in {"poi_address_matched", "address_matched"}

    google_candidate = google_rating_candidate(record, google_ratings)
    gap = None
    if google_candidate and current_ok:
        gap = distance_km(float(lat), float(lng), google_candidate["lat"], google_candidate["lng"])

    if google_candidate and google_candidate["address_ok"]:
        if strong_current_match and gap is not None and gap > GOOGLE_PLACE_ALIGNMENT_KM:
            record["lat"] = None
            record["lng"] = None
            record["coordinate_source"] = None
            record["coordinate_confidence"] = "location_conflict"
            record["map_pin_note"] = (
                "Independent hotel location matches disagree on this property, so the pin is hidden until the "
                "address can be manually confirmed."
            )
            return

        record["lat"] = google_candidate["lat"]
        record["lng"] = google_candidate["lng"]
        record["coordinate_source"] = "google_maps_ratings"
        record["coordinate_confidence"] = "google_place_verified"
        if gap is None:
            record["map_pin_note"] = "Pin follows the matched Google place for this hotel."
        elif current_confidence == "approximate" and gap > GOOGLE_PLACE_ALIGNMENT_KM:
            record["map_pin_note"] = (
                "Approximate geocoding drifted from the matched Google place, so the pin now follows the verified "
                "hotel location."
            )
        elif strong_current_match:
            record["map_pin_note"] = "The hotel address match and Google place agree on this location."
        else:
            record["map_pin_note"] = "Google place matches the hotel listing and address for this property."
        return

    if google_candidate and google_candidate["name_ok"] and gap is not None and gap <= GOOGLE_PLACE_ALIGNMENT_KM:
        record["coordinate_source"] = "google_maps_ratings"
        record["coordinate_confidence"] = "google_place_verified"
        record["map_pin_note"] = "Google place agrees with the mapped hotel location."
        return

    if (
        google_candidate
        and google_candidate["name_ok"]
        and current_ok
        and gap is not None
        and gap <= GOOGLE_NAME_ONLY_ALIGNMENT_KM
    ):
        record["lat"] = google_candidate["lat"]
        record["lng"] = google_candidate["lng"]
        record["coordinate_source"] = "google_maps_ratings"
        record["coordinate_confidence"] = "google_place_verified"
        if current_confidence == "approximate" and gap > GOOGLE_PLACE_ALIGNMENT_KM:
            record["map_pin_note"] = (
                "Approximate geocoding drifted from the matched Google hotel place, so the pin now follows the "
                "Google place returned for the source-address query."
            )
        else:
            record["map_pin_note"] = "Google place matches the hotel name for the source-address query."
        return

    if current_ok:
        return

    record["lat"] = None
    record["lng"] = None
    record["coordinate_source"] = None
    record["coordinate_confidence"] = "none"
    record["map_pin_note"] = (
        "The hotel location could not be verified from the official source address yet, so the pin is hidden until "
        "it can be confirmed."
    )


def build_search_text(record: dict) -> str:
    fields = [
        record.get("name"),
        record.get("country"),
        record.get("city"),
        record.get("address"),
        record.get("eligible_room_type"),
        record.get("blackout_raw"),
        record.get("reservation_raw"),
        record.get("availability_mode"),
        record.get("breakfast_note"),
    ]
    return " ".join(field for field in fields if field).lower()


def geojson(records: list[dict]) -> dict:
    features = []
    for record in records:
        if record.get("lat") is None or record.get("lng") is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [record["lng"], record["lat"]],
                },
                "properties": {
                    key: value
                    for key, value in record.items()
                    if key not in {"lat", "lng"}
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def kml_description(record: dict) -> str:
    lines = [
        f"<strong>{html.escape(record['name'])}</strong>",
        html.escape(f"{record.get('city') or 'City unknown'} / {record.get('country') or 'Country unknown'}"),
        html.escape("Address: " + record["address"]),
        html.escape("Eligible room: " + record["eligible_room_type"]),
    ]
    if record.get("blackout_raw"):
        lines.append(html.escape("Blackout notes: " + record["blackout_raw"]))
    if record.get("reservation_raw"):
        lines.append(html.escape("Reservation: " + record["reservation_raw"]))
    if record.get("breakfast_note"):
        lines.append(html.escape("Breakfast: " + record["breakfast_note"]))
    if record.get("source_url"):
        lines.append(
            f'<a href="{html.escape(record["source_url"], quote=True)}" target="_blank" rel="noopener">Official Plat Stay source</a>'
        )
    lines.append(html.escape(record["map_pin_note"]))
    return "<br/>".join(lines)


def build_kml(records: list[dict], name: str) -> str:
    placemarks = []
    for record in records:
        if record.get("lat") is None or record.get("lng") is None:
            continue
        placemarks.append(
            "\n".join(
                [
                    "    <Placemark>",
                    f"      <name>{html.escape(record['name'])}</name>",
                    f"      <description><![CDATA[{kml_description(record)}]]></description>",
                    "      <Point>",
                    f"        <coordinates>{record['lng']},{record['lat']},0</coordinates>",
                    "      </Point>",
                    "    </Placemark>",
                ]
            )
        )
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            "  <Document>",
            f"    <name>{html.escape(name)}</name>",
            *placemarks,
            "  </Document>",
            "</kml>",
            "",
        ]
    )


def build_records(pdf_bytes: bytes, resolved_url: str, fetched_at: str, page_count: int | None) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(pdf_bytes)
        pdf_path = Path(handle.name)

    try:
        text = pdf_to_text(pdf_path)
        mailto_links, booking_url = extract_pdf_contact_links(pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)

    # Keywords that identify repeated column header rows (not real hotels)
    _HEADER_NAMES = {"participating properties", "participating", "eligible room type"}

    records: list[dict] = []
    for block in split_property_blocks(text):
        parsed = parse_block(block)
        if not parsed.name or not parsed.address:
            continue
        # Skip repeated column headers that appear at the top of each PDF page
        if parsed.name.lower().strip() in _HEADER_NAMES:
            continue

        exact_blackouts, blackout_notes = blackout_structures(parsed.blackout_items)
        country = infer_country(parsed.address, parsed.name)
        breakfast_included = country != "Singapore" if country else None
        if country == "Singapore":
            breakfast_note = "Room only. Breakfast is not included for Singapore properties."
        else:
            breakfast_note = "Breakfast for 2 is available at overseas properties only."

        availability_mode = "listed_blackout_dates" if exact_blackouts else "subject_to_availability"
        if parsed.blackout_items and all(item.lower().startswith("subject to availability") for item in parsed.blackout_items):
            availability_mode = "subject_to_availability"
        if any("opening q2" in note.lower() for note in blackout_notes):
            availability_mode = "opening_window_note"

        record = {
            "id": f"plat-stay-{slugify(parsed.name)}",
            "dataset": "plat_stay",
            "source": "American Express Plat Stay",
            "source_url": CANONICAL_SOURCE_URL,
            "source_document_url": resolved_url,
            "name": parsed.name,
            "country": country,
            "city": None,
            "address": parsed.address,
            "eligible_room_type": parsed.eligible_room_type,
            "breakfast_included": breakfast_included,
            "breakfast_note": breakfast_note,
            "blackout_raw": parsed.blackout_raw,
            "blackout_items": parsed.blackout_items,
            "blackout_exact_ranges": exact_blackouts,
            "blackout_notes": blackout_notes,
            "availability_mode": availability_mode,
            "reservation_raw": parsed.reservation_raw,
            "reservation_phone": parsed.reservation_phone,
            "reservation_email": parsed.reservation_email,
            "reservation_mode": parsed.reservation_mode,
            "reservation_primary_url": None,
            "reservation_primary_label": None,
            "reservation_secondary_url": None,
            "reservation_secondary_label": None,
            "lat": None,
            "lng": None,
            "coordinate_source": None,
            "coordinate_confidence": "unknown",
            "map_pin_note": "Pin is not plotted yet. Confirm the official property address before booking or arrival.",
            "source_hash_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "source_page_count": page_count,
            "last_synced_at": fetched_at,
            "search_text": "",
        }
        record["search_text"] = build_search_text(record)
        records.append(record)

    deduped = {}
    for record in records:
        deduped.setdefault(record["id"], record)

    ordered_records = list(deduped.values())
    attach_reservation_links(ordered_records, mailto_links, booking_url)
    return sorted(ordered_records, key=lambda item: ((item.get("country") or ""), item["name"]))


def attach_reservation_links(records: list[dict], mailto_links: list[str], booking_url: str | None) -> None:
    mailto_index = 0
    for record in records:
        is_fraser_family = re.match(r"^(Fraser|Capri|Modena)\b", record["name"]) is not None
        if record["reservation_mode"] == "booking_link_prompt":
            if booking_url:
                record["reservation_primary_url"] = booking_url
                record["reservation_primary_label"] = "Open booking portal"
            continue

        if mailto_index < len(mailto_links):
            mailto_link = mailto_links[mailto_index]
            mailto_index += 1
            email = mailto_link.removeprefix("mailto:")
            record["reservation_email"] = email
            if record.get("reservation_phone"):
                record["reservation_raw"] = f"{record['reservation_phone']} | {email}"
            else:
                record["reservation_raw"] = email

        if record.get("reservation_email"):
            record["reservation_primary_url"] = f"mailto:{record['reservation_email']}"
            record["reservation_primary_label"] = "Email reservations"
        if record.get("reservation_phone"):
            target = f"tel:{re.sub(r'[^\d+]+', '', record['reservation_phone'])}"
            if record.get("reservation_primary_url"):
                record["reservation_secondary_url"] = target
                record["reservation_secondary_label"] = "Call reservations"
            else:
                record["reservation_primary_url"] = target
                record["reservation_primary_label"] = "Call reservations"

        if not record.get("reservation_primary_url") and booking_url and is_fraser_family:
            record["reservation_raw"] = record.get("reservation_raw") or "Reserve your room here"
            record["reservation_primary_url"] = booking_url
            record["reservation_primary_label"] = "Open booking portal"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KML_DIR.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(UTC).isoformat()
    pdf_bytes, resolved_url = fetch_pdf(CANONICAL_SOURCE_URL)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(pdf_bytes)
        pdf_path = Path(handle.name)

    try:
        page_count = pdf_page_count(pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)

    records = build_records(pdf_bytes, resolved_url, fetched_at, page_count)

    manual_overrides = load_json(MANUAL_OVERRIDE_PATH, {})
    for record in records:
        apply_manual_override(record, manual_overrides)

    geocode_cache = load_json(GEOCODE_CACHE_PATH, {})
    geoapify_cache = load_json(GEOAPIFY_CACHE_PATH, {})
    tomtom_cache = load_json(TOMTOM_CACHE_PATH, {})
    google_ratings = load_json(GOOGLE_RATINGS_PATH, {})
    for record in records:
        geocode_record(record, geocode_cache)
        if record.get("coordinate_confidence") not in {"manual_verified"}:
            refine_with_geoapify(record, geoapify_cache)
        if record.get("coordinate_confidence") not in {"manual_verified", "poi_address_matched"}:
            refine_with_tomtom(record, tomtom_cache)
        validate_record_coordinates(record, google_ratings)
        record["search_text"] = build_search_text(record)

    save_json(JSON_PATH, records)
    save_json(GEOJSON_PATH, geojson(records))
    KML_PATH.write_text(build_kml(records, "Plat Stay - All Properties"))
    save_json(
        SOURCE_META_PATH,
        {
            "source_name": "Amex Plat Stay",
            "canonical_url": CANONICAL_SOURCE_URL,
            "resolved_url": resolved_url,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "fetched_at": fetched_at,
            "page_count": page_count,
            "record_count": len(records),
        },
    )

    mapped = sum(1 for record in records if record.get("lat") is not None and record.get("lng") is not None)
    print(f"Synced {len(records)} Plat Stay properties; mapped {mapped}.")


if __name__ == "__main__":
    main()
