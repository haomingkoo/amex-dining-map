#!/usr/bin/env python3
"""Sync the Plat Stay dataset from the official Amex short-link PDF."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
import time
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

CANONICAL_SOURCE_URL = "https://go.amex/platstay"
USER_AGENT = "AmexBenefitsExplorer/0.1 (+https://kooexperience.com/amex-dining-map/)"
DEFAULT_BLACKOUT_YEAR = 2026

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


def fetch_pdf(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(), response.geturl()


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


def split_property_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()
    start_index = next((i for i, line in enumerate(lines) if "The Fullerton" in line), None)
    end_index = next((i for i, line in enumerate(lines) if line.startswith("Terms and Conditions")), None)
    if start_index is None or end_index is None or end_index <= start_index:
        raise RuntimeError("Could not isolate the Plat Stay property table from the PDF text.")

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
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload[0] if payload else None


def geocode_record(record: dict, cache: dict) -> None:
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
        return


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
    finally:
        pdf_path.unlink(missing_ok=True)

    records: list[dict] = []
    for block in split_property_blocks(text):
        parsed = parse_block(block)
        if not parsed.name or not parsed.address:
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

    deduped = {record["id"]: record for record in records}
    return sorted(deduped.values(), key=lambda item: ((item.get("country") or ""), item["name"]))


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

    geocode_cache = load_json(GEOCODE_CACHE_PATH, {})
    for record in records:
        geocode_record(record, geocode_cache)
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
