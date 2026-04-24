#!/usr/bin/env python3
"""Refresh the public Amex Table for Two roster snapshot.

The official Amex page currently publishes the participating merchant roster as
an image, not as structured HTML or JSON. This script verifies the public source
URLs and image hashes, then writes the curated roster with a review flag if the
source image changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OFFICIAL_URL = "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/"
TERMS_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/TableforTwo-Plat-TnCs.pdf"
FAQ_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining/TableforTwo_FAQ.pdf"
KNOWN_PARTICIPATING_SHA256 = "ab8ca3926779acf298933fd234153efeaaac66c37421677103ea3ece2215a8a5"
KNOWN_CYCLES_SHA256 = "fe025896cb9eded177e770fb23c00f162fac3e238a74ff1e348750d37b453a6c"


VENUES = [
    {
        "id": "tft-15-stamford-restaurant",
        "name": "15 Stamford Restaurant",
        "category": "restaurant",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Chic Restaurant"],
        "booking_channel": "Amex Experiences App",
        "dining_city_id": "2055188",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/15_stamford_by_alvin_leung",
        "slot_source_status": "app_handoff_required",
        "availability": {
            "status": "captured_available",
            "source": "Amex Experiences App screenshot provided by user",
            "captured_at": "2026-04-24T09:27:00+08:00",
            "confidence": "manual_screenshot",
            "date_label": "April 2026 app date screen; exact selected booking date should be reconfirmed inside the app",
            "visible_dates": ["2026-04-28", "2026-04-29", "2026-04-30"],
            "summary": "At least 2 Table for Two seats were visible for lunch at 12:00, 12:30, 13:00, and 13:30. Dinner slots were shown as no seats.",
            "meals": [
                {
                    "meal": "Lunch",
                    "status": "available",
                    "seats": 2,
                    "date_label": "Selected date not visible in screenshot",
                    "times": ["12:00", "12:30", "13:00", "13:30"],
                },
                {
                    "meal": "Dinner",
                    "status": "no_seats",
                    "date_label": "Selected date not visible in screenshot",
                    "times": ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30"],
                },
            ],
            "notes": [
                "This is a captured app view, not a live public API feed.",
                "Use the Amex Experiences App to reconfirm before planning around the slot.",
            ],
        },
        "sample_menu": {
            "source": "Amex Experiences App screenshot provided by user",
            "captured_at": "2026-04-24",
            "title": "Table for Two by Platinum — 3-course set menu",
            "courses": [
                {"course": "Starter", "choices": ["Pan-seared US Scallop", "Jerusalem Artichoke Soup"]},
                {"course": "Main", "choices": ["Seared Barramundi Fillet", "Dry Aged Hanger Steak"]},
                {"course": "Dessert", "choices": ["Cheese Cake Mousse"]},
            ],
            "additional_cover_note": (
                "Two sets are served under Table for Two. Additional covers beyond two pax "
                "are charged at S$128++ per pax for this menu."
            ),
        },
    },
    {"id": "tft-baes-cocktail-club", "name": "Bae's Cocktail Club", "category": "restaurant"},
    {"id": "tft-cultivate", "name": "Cultivate", "category": "restaurant"},
    {
        "id": "tft-highhouse",
        "name": "HighHouse",
        "category": "restaurant",
        "app_area": "Marina Bay/Boat Quay",
        "app_tags": ["Table for Two", "Chic Restaurant"],
    },
    {"id": "tft-la-brasserie", "name": "La Brasserie", "category": "restaurant"},
    {"id": "tft-osteria-mozza", "name": "Osteria Mozza", "category": "restaurant"},
    {"id": "tft-polo-bar-steakhouse", "name": "Polo Bar Steakhouse", "category": "restaurant"},
    {"id": "tft-rappu", "name": "Rappu", "category": "restaurant"},
    {"id": "tft-sarai", "name": "Sarai", "category": "restaurant"},
    {
        "id": "tft-tanoke",
        "name": "TANOKE",
        "category": "restaurant",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Chic Restaurant"],
    },
    {"id": "tft-the-feather-blade", "name": "The Feather Blade", "category": "restaurant"},
    {"id": "tft-vineyard", "name": "Vineyard", "category": "restaurant"},
    {"id": "tft-vue", "name": "VUE", "category": "restaurant"},
    {
        "id": "tft-colony",
        "name": "Colony",
        "category": "buffet",
        "app_name": "Colony @ The Ritz-Carlton",
        "app_area": "Marina Bay/Boat Quay",
        "app_tags": ["Table for Two", "Buffet"],
    },
    {"id": "tft-peppermint", "name": "Peppermint", "category": "buffet"},
    {
        "id": "tft-capitol-bistro-bar-patisserie",
        "name": "Capitol Bistro. Bar. Patisserie",
        "category": "cafe",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Cafe"],
    },
    {"id": "tft-kees", "name": "Kee's", "category": "cafe"},
    {
        "id": "tft-the-plump-frenchman",
        "name": "The Plump Frenchman",
        "category": "cafe",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Cafe"],
    },
]


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 amex-dining-map source verifier",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def absolute_url(path_or_url: str) -> str:
    return urllib.parse.urljoin(OFFICIAL_URL, path_or_url)


def extract_image_url(html: str, alt_text: str) -> str:
    pattern = re.compile(
        rf'<img[^>]+(?:alt="{re.escape(alt_text)}"|alt=\'{re.escape(alt_text)}\')[^>]+>',
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        raise RuntimeError(f"Could not find image with alt={alt_text!r}")
    tag = match.group(0)
    src_match = re.search(r'data-src=["\']([^"\']+)["\']', tag) or re.search(r'src=["\']([^"\']+)["\']', tag)
    if not src_match:
        raise RuntimeError(f"Could not find source URL for image with alt={alt_text!r}")
    return absolute_url(src_match.group(1))


def default_availability() -> dict:
    return {
        "status": "unknown",
        "source": "not_checked",
        "confidence": "not_checked",
        "summary": "No Table for Two app availability has been captured for this venue yet.",
    }


def should_preserve_availability(existing: dict | None, curated: dict | None) -> bool:
    if not existing:
        return False
    availability = existing.get("availability")
    if not isinstance(availability, dict):
        return False
    if availability.get("status") in {None, "", "unknown"}:
        return False
    if not curated:
        return True
    return availability.get("source") != curated.get("source") or availability.get("captured_at") != curated.get("captured_at")


def normalized_venues(existing_by_id: dict[str, dict] | None = None) -> list[dict]:
    existing_by_id = existing_by_id or {}
    records = []
    for venue in VENUES:
        curated_availability = venue.get("availability")
        existing_record = existing_by_id.get(venue["id"])
        availability = (
            existing_record["availability"]
            if should_preserve_availability(existing_record, curated_availability)
            else curated_availability or default_availability()
        )
        record = {
            "booking_channel": "Amex Experiences App",
            "slot_source_status": "app_handoff_required",
            "availability": availability,
            **venue,
        }
        record["availability"] = availability
        records.append(record)
    return records


def build_payload(existing_payload: dict | None = None) -> dict:
    existing_by_id = {
        record.get("id"): record
        for record in (existing_payload or {}).get("venues", [])
        if record.get("id")
    }
    html = fetch_bytes(OFFICIAL_URL).decode("utf-8", errors="replace")
    participating_url = extract_image_url(html, "Participating Merchants")
    cycles_url = extract_image_url(html, "Voucher Cycles 2026")
    participating_hash = hashlib.sha256(fetch_bytes(participating_url)).hexdigest()
    cycles_hash = hashlib.sha256(fetch_bytes(cycles_url)).hexdigest()
    manual_review_required = (
        participating_hash != KNOWN_PARTICIPATING_SHA256
        or cycles_hash != KNOWN_CYCLES_SHA256
    )

    return {
        "dataset": "table_for_two",
        "program": "American Express Table for Two by Platinum",
        "country": "Singapore",
        "currency": "SGD",
        "last_verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "official_url": OFFICIAL_URL,
        "terms_url": TERMS_URL,
        "faq_url": FAQ_URL,
        "participating_merchants_image_url": participating_url,
        "voucher_cycles_image_url": cycles_url,
        "source_images": {
            "participating_merchants_sha256": participating_hash,
            "voucher_cycles_sha256": cycles_hash,
        },
        "manual_review_required": manual_review_required,
        "voucher_cycles_2026": [
            "Jan - Feb",
            "Mar - Apr",
            "May - Jun",
            "Jul - Aug",
            "Sep - Oct",
            "Nov - Dec",
        ],
        "availability_last_checked_at": (existing_payload or {}).get("availability_last_checked_at", "2026-04-24T09:27:00+08:00"),
        "refresh_policy": {
            "official_roster": "Daily is enough. The public source is an official image; the script hashes it and raises manual_review_required if it changes.",
            "terms_and_faq": "Daily is enough unless Amex announces a cycle change.",
            "captured_availability": "Dining availability is only useful when fresh. Treat screenshot/app-captured availability as stale after 30 minutes.",
            "app_confirmed_availability": "Useful target cadence is every 5 to 10 minutes for selected restaurants and sessions. Keep user/session-specific app data out of public GitHub Actions.",
            "github_public_refresh": "GitHub can safely refresh the public roster daily, but that does not create live Table for Two availability because exact slots require app-context data.",
        },
        "availability_model": {
            "captured_available": "Availability seen in an Amex Experiences App screenshot or local app check.",
            "captured_no_seats": "No seats seen in a captured app screenshot or local app check.",
            "unknown": "Venue is in the official roster, but no app availability has been captured.",
        },
        "booking_channel": "Amex Experiences App",
        "source_notes": [
            "The public Amex page exposes the 2026 participating merchant roster as an image, not as a structured table.",
            "Live Table for Two slot inventory appears to require an Amex Experiences App handoff context. Public DiningCity availability is not the same allocation.",
            "Do not commit user/session-specific app handoff values from app URLs or screenshots.",
        ],
        "venues": normalized_venues(existing_by_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/table-for-two.json")
    args = parser.parse_args()

    output_path = Path(args.output)
    existing_payload = None
    if output_path.exists():
        existing_payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload = build_payload(existing_payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    count = len(payload["venues"])
    review = " manual review required" if payload.get("manual_review_required") else ""
    print(f"Wrote {count} Table for Two venues to {output_path}.{review}")
    return 2 if payload.get("manual_review_required") else 0


if __name__ == "__main__":
    sys.exit(main())
