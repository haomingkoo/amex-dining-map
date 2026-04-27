#!/usr/bin/env python3
"""Refresh the public Amex Table for Two roster and availability snapshot.

The official Amex page currently publishes the participating merchant roster as
an image, not as structured HTML or JSON. This script verifies the public source
URLs and image hashes, then writes the curated roster with a review flag if the
source image changes. Slot availability is read from DiningCity's public
American Express Platinum Singapore project (`AMEXPlatSG`); bookings and voucher
redemption still require the Amex Experiences App.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
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
DININGCITY_API_BASE = "https://api.diningcity.asia/public"
DININGCITY_PROJECT = "AMEXPlatSG"
DININGCITY_PROJECT_TITLE = "AMEX Platinum SG"
MIN_TABLE_FOR_TWO_SEATS = 2
MAX_AVAILABILITY_TIMES = 12


VENUES = [
    {
        "id": "tft-15-stamford-restaurant",
        "name": "15 Stamford Restaurant",
        "category": "restaurant",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Chic Restaurant"],
        "booking_channel": "Amex Experiences App",
        "dining_city_id": "2055188",
        "dining_city_name": "15 Stamford Restaurant",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/15_stamford_by_alvin_leung",
        "address": "15 Stamford Road, Singapore 178906",
        "lat": 1.2935522,
        "lng": 103.8515954,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
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
    {
        "id": "tft-baes-cocktail-club",
        "name": "Bae's Cocktail Club",
        "category": "restaurant",
        "dining_city_id": "205194844",
        "dining_city_name": "Bae's Cocktail Club",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Baes_Cocktail_Club",
        "address": "21 Tanjong Pagar Road, #01-04/05, Singapore 088444",
        "lat": 1.2794614,
        "lng": 103.8440827,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-cultivate",
        "name": "Cultivate",
        "category": "restaurant",
        "dining_city_id": "205194002",
        "dining_city_name": "Cultivate Café",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Cultivate_Cafe",
        "address": "2 Cook Street, Maxwell Reserve, Singapore 078857",
        "lat": 1.2788723,
        "lng": 103.8443955,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name variant.",
    },
    {
        "id": "tft-highhouse",
        "name": "HighHouse",
        "category": "restaurant",
        "app_area": "Marina Bay/Boat Quay",
        "app_tags": ["Table for Two", "Chic Restaurant"],
        "dining_city_id": "205194016",
        "dining_city_name": "HighHouse",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/high_house",
        "address": "1 Raffles Place, Level 61-62, Singapore 048616",
        "lat": 1.2844024,
        "lng": 103.8509818,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-la-brasserie",
        "name": "La Brasserie",
        "category": "restaurant",
        "dining_city_id": "205173372",
        "dining_city_name": "La Brasserie",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/la_brasserie_aat3",
        "address": "80 Collyer Quay, The Fullerton Bay Hotel, Singapore 049326",
        "lat": 1.283223278918248,
        "lng": 103.8535571753726,
        "coordinate_confidence": "address_geocoded",
        "map_pin_source": "Singapore OneMap address geocode",
        "map_pin_note": "Pin is address-geocoded from the official Fullerton Bay Hotel address; confirm the exact entrance before visiting.",
        "venue_source_url": "https://www.fullertonhotels.com/fullerton-bay-hotel-singapore/dining/restaurants-and-bars/la-brasserie",
    },
    {
        "id": "tft-osteria-mozza",
        "name": "Osteria Mozza",
        "category": "restaurant",
        "dining_city_id": "205194420",
        "dining_city_name": "Osteria Mozza",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Osteria_Mozza",
        "address": "Hilton Singapore Orchard, Level 5, 333 Orchard Road, Singapore 238867",
        "lat": 1.302064505560855,
        "lng": 103.8363409534752,
        "coordinate_confidence": "address_geocoded",
        "map_pin_source": "Singapore OneMap address geocode",
        "map_pin_note": "Pin is address-geocoded from the official Hilton Singapore Orchard address; confirm the exact restaurant entrance before visiting.",
        "venue_source_url": "https://osteriamozza.com.sg/",
    },
    {
        "id": "tft-polo-bar-steakhouse",
        "name": "Polo Bar Steakhouse",
        "category": "restaurant",
        "dining_city_id": "205194006",
        "dining_city_name": "Polo Bar Steakhouse",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Polo_Bar_Steakhouse",
        "address": "2 Cook Street, Maxwell Reserve, Singapore 078857",
        "lat": 1.2788723,
        "lng": 103.8443955,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-rappu",
        "name": "Rappu",
        "category": "restaurant",
        "dining_city_id": "205194830",
        "dining_city_name": "RAPPU",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/RAPPU",
        "address": "52 Duxton Road, Singapore 089516",
        "lat": 1.278218928878857,
        "lng": 103.843345507949,
        "coordinate_confidence": "address_geocoded",
        "map_pin_source": "Singapore OneMap address geocode",
        "map_pin_note": "Pin is address-geocoded from RAPPU's published address; confirm the exact entrance before visiting.",
        "venue_source_url": "https://www.rappu.sg/",
    },
    {
        "id": "tft-sarai",
        "name": "Sarai",
        "category": "restaurant",
        "dining_city_id": "205178290",
        "dining_city_name": "Sarai",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Sarai",
        "address": "163 Tanglin Road, #03-122 Tanglin Mall, Singapore 247933",
        "lat": 1.3051081,
        "lng": 103.823845,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-tanoke",
        "name": "TANOKE",
        "category": "restaurant",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Chic Restaurant"],
        "dining_city_id": "205174962",
        "dining_city_name": "TANOKE",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/tanoke",
        "address": "7 Purvis Street, Level 2, Singapore 188586",
        "lat": 1.2967501,
        "lng": 103.8551743,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-the-feather-blade",
        "name": "The Feather Blade",
        "category": "restaurant",
        "dining_city_id": "205194812",
        "dining_city_name": "The Feather Blade",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/The_Feather_Blade",
        "address": "61 Tanjong Pagar Road, Singapore 088482",
        "lat": 1.2783375,
        "lng": 103.8439166,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-vineyard",
        "name": "Vineyard",
        "category": "restaurant",
        "dining_city_id": "2055283",
        "dining_city_name": "Vineyard @ Hort Park",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/vineyard_hort_park",
        "address": "33 Hyderabad Road, #02-02 HortPark, Singapore 119578",
        "lat": 1.2786197,
        "lng": 103.8015439,
        "coordinate_confidence": "love_dining_place_matched",
        "map_pin_source": "Existing Love Dining geocode for Vineyard at HortPark",
        "map_pin_note": "Pin reuses the existing source-backed Love Dining geocode for Vineyard at HortPark.",
        "venue_source_url": "https://www.vineyardhortpark.com.sg/contact-us-1",
    },
    {
        "id": "tft-vue",
        "name": "VUE",
        "category": "restaurant",
        "dining_city_id": "205194014",
        "dining_city_name": "VUE",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/vue",
        "address": "OUE Bayfront, 50 Collyer Quay, Rooftop Level 19, Singapore 049321",
        "lat": 1.2830822,
        "lng": 103.8529553,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-colony",
        "name": "Colony",
        "category": "buffet",
        "app_name": "Colony @ The Ritz-Carlton",
        "app_area": "Marina Bay/Boat Quay",
        "app_tags": ["Table for Two", "Buffet"],
        "dining_city_id": "205191500",
        "dining_city_name": "Colony",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/colony",
        "address": "The Ritz-Carlton, Millenia Singapore, 7 Raffles Avenue, Singapore 039799",
        "lat": 1.2909392,
        "lng": 103.8599895,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-peppermint",
        "name": "Peppermint",
        "category": "buffet",
        "dining_city_id": "205194942",
        "dining_city_name": "Peppermint",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Peppermint",
        "address": "PARKROYAL COLLECTION Marina Bay, Level 4, 6 Raffles Boulevard, Singapore 039594",
        "lat": 1.291573956548436,
        "lng": 103.8570269553721,
        "coordinate_confidence": "address_geocoded",
        "map_pin_source": "Singapore OneMap address geocode",
        "map_pin_note": "Pin is address-geocoded from PARKROYAL COLLECTION Marina Bay's published address; confirm the exact restaurant entrance before visiting.",
        "venue_source_url": "https://www.panpacific.com/en/hotels-and-resorts/pr-collection-marina-bay/dining/peppermint.html",
    },
    {
        "id": "tft-capitol-bistro-bar-patisserie",
        "name": "Capitol Bistro. Bar. Patisserie",
        "category": "cafe",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Cafe"],
        "dining_city_id": "205192162",
        "dining_city_name": "Capitol Bistro. Bar. Patisserie",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/capitol_bistro_bar_patisserie",
        "address": "13 Stamford Road, #01-86/87, Arcade @ The Capitol Kempinski, Singapore 178905",
        "lat": 1.293546,
        "lng": 103.8511091,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-kees",
        "name": "Kee's",
        "category": "cafe",
        "dining_city_id": "205194842",
        "dining_city_name": "Kee's",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Kees",
        "address": "21 Carpenter Street, Singapore 059984",
        "lat": 1.2885226,
        "lng": 103.8474019,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
    },
    {
        "id": "tft-the-plump-frenchman",
        "name": "The Plump Frenchman",
        "category": "cafe",
        "app_area": "City Hall/Bugis",
        "app_tags": ["Table for Two", "Cafe"],
        "dining_city_id": "205194944",
        "dining_city_name": "The Plump Frenchman",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/The_Plump_Frenchman",
        "address": "20 Tan Quee Lan Street, #01-20 Guoco Midtown II, Singapore 188107",
        "lat": 1.2985824,
        "lng": 103.8568306,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
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


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_json(path: str, params: dict | None = None, *, accept_version: bool = True) -> object:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{DININGCITY_API_BASE}{path}{query}"
    headers = {
        "User-Agent": "Mozilla/5.0 amex-dining-map table-for-two refresh",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-key": "cgecegcegcc",
        "lang": "en",
    }
    if accept_version:
        headers["accept-version"] = "application/json; version=2"
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


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
        "summary": "No Table for Two availability check has been captured for this venue yet.",
    }


def diningcity_source_url(dining_city_id: str) -> str:
    params = urllib.parse.urlencode({"project": DININGCITY_PROJECT})
    return f"{DININGCITY_API_BASE}/restaurants/{dining_city_id}/available_2018?{params}"


def diningcity_selected_date_source_url(dining_city_id: str, selected_date: str) -> str:
    params = urllib.parse.urlencode({"project": DININGCITY_PROJECT, "selected_date": selected_date})
    return f"{DININGCITY_API_BASE}/restaurants/{dining_city_id}/available_2018?{params}"


def has_project(dining_city_id: str) -> bool:
    projects = fetch_json(f"/restaurants/{dining_city_id}/projects/program_and_event")
    return isinstance(projects, list) and any(
        project.get("project") == DININGCITY_PROJECT
        for project in projects
        if isinstance(project, dict)
    )


def rows_from_payload(payload: object) -> list[dict]:
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def fetch_available_dates(dining_city_id: str) -> list[str]:
    payload = fetch_json(
        f"/restaurants/{dining_city_id}/dining_dates",
        {"project": DININGCITY_PROJECT},
        accept_version=False,
    )
    if not isinstance(payload, list):
        return []
    dates = {
        row.get("date")
        for row in payload
        if isinstance(row, dict) and row.get("available") is True and row.get("date")
    }
    return sorted(dates)


def fetch_selected_date_rows(dining_city_id: str, dates: list[str]) -> list[dict]:
    rows = []
    for selected_date in dates:
        payload = fetch_json(
            f"/restaurants/{dining_city_id}/available_2018",
            {"project": DININGCITY_PROJECT, "selected_date": selected_date},
            accept_version=False,
        )
        rows.extend(rows_from_payload(payload))
    return rows


def seat_values(slot: dict) -> set[int]:
    values = slot.get("seats", {}).get("available", [])
    if not isinstance(values, list):
        return set()
    normalized = set()
    for value in values:
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def slot_max_seats(slot: dict) -> int:
    values = seat_values(slot)
    if values:
        return max(values)
    try:
        return int(slot.get("seats", {}).get("total_available_seats") or 0)
    except (TypeError, ValueError):
        return 0


def slot_raw_available_seats(slot: dict) -> int:
    try:
        return int(slot.get("seats", {}).get("total_available_seats") or 0)
    except (TypeError, ValueError):
        return 0


def meal_sort_key(meal: str) -> tuple[int, str]:
    normalized = (meal or "").strip().lower()
    if normalized == "lunch":
        return (0, normalized)
    if normalized == "dinner":
        return (1, normalized)
    return (9, normalized)


def has_minimum_seats(slot: dict, minimum: int = MIN_TABLE_FOR_TWO_SEATS) -> bool:
    return slot_max_seats(slot) >= minimum


def build_meals(rows: list[dict]) -> tuple[list[dict], list[str], int]:
    grouped: dict[str, dict] = defaultdict(
        lambda: {"dates": set(), "times": set(), "slots": [], "slot_count": 0, "max_seats": 0}
    )
    visible_dates = set()
    available_slot_count = 0
    for row in rows:
        date = row.get("date")
        if date:
            visible_dates.add(date)
        for slot in row.get("times") or []:
            if not isinstance(slot, dict) or not has_minimum_seats(slot):
                continue
            meal = slot.get("meal_type_text") or slot.get("meal_type") or "Session"
            time = slot.get("time")
            max_seats = slot_max_seats(slot)
            bucket = grouped[meal]
            if date:
                bucket["dates"].add(date)
            if time:
                bucket["times"].add(time)
            bucket["slots"].append(
                {
                    "date": date,
                    "weekday": row.get("weekday") or "",
                    "time": time,
                    "meal": meal,
                    "max_seats": max_seats,
                    "raw_available_seats": slot_raw_available_seats(slot),
                }
            )
            bucket["slot_count"] += 1
            bucket["max_seats"] = max(bucket["max_seats"], max_seats)
            available_slot_count += 1

    meals = []
    for meal, bucket in sorted(grouped.items(), key=lambda item: meal_sort_key(item[0])):
        dates = sorted(bucket["dates"])
        times = sorted(bucket["times"])
        slots = sorted(bucket["slots"], key=lambda item: f"{item.get('date') or ''} {item.get('time') or ''}")
        meals.append(
            {
                "meal": meal,
                "status": "available",
                "seats": MIN_TABLE_FOR_TWO_SEATS,
                "max_seats": bucket["max_seats"],
                "dates": dates,
                "times": times[:MAX_AVAILABILITY_TIMES],
                "slots": slots,
                "slot_count": bucket["slot_count"],
            }
        )
    return meals, sorted(visible_dates), available_slot_count


def live_availability_for_venue(venue: dict, checked_at: str) -> tuple[dict | None, str | None]:
    dining_city_id = venue.get("dining_city_id")
    if not dining_city_id:
        return None, "missing_dining_city_id"
    try:
        if not has_project(dining_city_id):
            return None, "missing_amex_platinum_project"
        payload = fetch_json(
            f"/restaurants/{dining_city_id}/available_2018",
            {"project": DININGCITY_PROJECT},
        )
    except Exception as exc:  # noqa: BLE001 - keep one venue failure from killing roster refresh.
        return None, f"{type(exc).__name__}: {exc}"

    rows = rows_from_payload(payload)
    source_mode = "bulk_project"
    fallback_dates = []
    if not rows:
        try:
            fallback_dates = fetch_available_dates(dining_city_id)
            rows = fetch_selected_date_rows(dining_city_id, fallback_dates)
            if rows:
                source_mode = "selected_date_project"
        except Exception:
            rows = []
    meals, visible_dates, available_slot_count = build_meals(rows)
    source_url = diningcity_source_url(dining_city_id)
    source_note = (
        f"Availability is from DiningCity project {DININGCITY_PROJECT} "
        f"({DININGCITY_PROJECT_TITLE}). Book and redeem through the Amex Experiences App."
    )
    if source_mode == "selected_date_project":
        source_note = (
            f"Availability is from DiningCity project {DININGCITY_PROJECT} "
            f"({DININGCITY_PROJECT_TITLE}) using the same per-date booking flow as the DiningCity restaurant page. "
            "Book and redeem through the Amex Experiences App."
        )
        source_date = visible_dates[0] if visible_dates else (fallback_dates[0] if fallback_dates else "")
        if source_date:
            source_url = diningcity_selected_date_source_url(dining_city_id, source_date)
    if available_slot_count:
        available_dates = sorted({date for meal in meals for date in meal.get("dates", [])})
        meal_summary = ", ".join(
            f"{meal['meal']} {len(meal.get('dates', []))} dates"
            for meal in meals
        )
        summary = (
            f"{len(available_dates)} dates with Table for Two slots returned "
            f"by DiningCity {DININGCITY_PROJECT}"
            f"{f' ({meal_summary})' if meal_summary else ''}."
        )
        status = "live_available"
    else:
        summary = (
            f"No Table for Two slots were returned by DiningCity {DININGCITY_PROJECT} "
            "at this check."
        )
        status = "live_no_seats"

    return (
        {
            "status": status,
            "source": f"DiningCity public API project {DININGCITY_PROJECT}",
            "source_url": source_url,
            "source_mode": source_mode,
            "project": DININGCITY_PROJECT,
            "project_title": DININGCITY_PROJECT_TITLE,
            "captured_at": checked_at,
            "checked_at": checked_at,
            "confidence": "diningcity_amex_platinum_project",
            "visible_dates": visible_dates,
            "summary": summary,
            "meals": meals,
            "notes": [source_note],
        },
        None,
    )


def fetch_live_availability(venues: list[dict], checked_at: str) -> tuple[dict[str, dict], dict[str, str]]:
    availability_by_id = {}
    errors = {}
    for venue in venues:
        availability, error = live_availability_for_venue(venue, checked_at)
        if availability:
            availability_by_id[venue["id"]] = availability
        elif error:
            errors[venue["id"]] = error
    return availability_by_id, errors


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


def normalized_venues(
    existing_by_id: dict[str, dict] | None = None,
    live_availability_by_id: dict[str, dict] | None = None,
) -> list[dict]:
    existing_by_id = existing_by_id or {}
    live_availability_by_id = live_availability_by_id or {}
    records = []
    for venue in VENUES:
        curated_availability = venue.get("availability")
        existing_record = existing_by_id.get(venue["id"])
        live_availability = live_availability_by_id.get(venue["id"])
        if live_availability:
            availability = live_availability
        elif should_preserve_availability(existing_record, curated_availability):
            availability = existing_record["availability"]
        else:
            availability = curated_availability or default_availability()
        record = {
            "booking_channel": "Amex Experiences App",
            "slot_source_status": (
                "diningcity_amex_platinum_project"
                if availability.get("confidence") == "diningcity_amex_platinum_project"
                else "app_handoff_required"
            ),
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
    checked_at = iso_now()
    live_availability_by_id, availability_errors = fetch_live_availability(VENUES, checked_at)
    availability_last_checked_at = (
        checked_at
        if live_availability_by_id
        else (existing_payload or {}).get("availability_last_checked_at")
    )

    return {
        "dataset": "table_for_two",
        "program": "American Express Table for Two by Platinum",
        "country": "Singapore",
        "currency": "SGD",
        "last_verified_at": checked_at,
        "official_url": OFFICIAL_URL,
        "terms_url": TERMS_URL,
        "faq_url": FAQ_URL,
        "alert_signup_url": os.environ.get("TABLE_FOR_TWO_ALERT_SIGNUP_URL", "").strip()
        or (existing_payload or {}).get("alert_signup_url", ""),
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
        "availability_last_checked_at": availability_last_checked_at,
        "availability_source": {
            "type": "diningcity_public_api",
            "api_base": DININGCITY_API_BASE,
            "project": DININGCITY_PROJECT,
            "project_title": DININGCITY_PROJECT_TITLE,
            "checked_venues": len(live_availability_by_id),
            "error_count": len(availability_errors),
            "errors": availability_errors,
        },
        "refresh_policy": {
            "official_roster": "Daily is enough. The public source is an official image; the script hashes it and raises manual_review_required if it changes.",
            "terms_and_faq": "Daily is enough unless Amex announces a cycle change.",
            "captured_availability": "Dining availability is only useful when fresh. Treat cached DiningCity AMEXPlatSG checks as stale after 30 minutes.",
            "app_confirmed_availability": "Useful target cadence is every 5 to 10 minutes for selected restaurants and sessions. Bookings and voucher redemption still require the Amex Experiences App.",
            "github_public_refresh": "GitHub can refresh the official roster and DiningCity AMEXPlatSG availability without storing user/session-specific app data.",
        },
        "availability_model": {
            "live_available": "Slot availability returned by DiningCity's public AMEXPlatSG project endpoint.",
            "live_no_seats": "DiningCity's public AMEXPlatSG project endpoint returned no qualifying slots at check time; this can still be contradicted by the authenticated Amex app.",
            "captured_available": "Legacy/manual availability seen in an Amex Experiences App screenshot or local app check.",
            "captured_no_seats": "Legacy/manual no-seat result seen in a captured app screenshot or local app check.",
            "unknown": "Venue is in the official roster, but no availability source has been captured.",
        },
        "booking_channel": "Amex Experiences App",
        "source_notes": [
            "The public Amex page exposes the 2026 participating merchant roster as an image, not as a structured table.",
            f"DiningCity exposes a public American Express Platinum Singapore project ({DININGCITY_PROJECT}) used for Table for Two slot checks.",
            "Generic public DiningCity restaurant availability is not treated as Table for Two inventory; only the AMEXPlatSG project endpoint is used.",
            "Do not commit user/session-specific app handoff values from app URLs or screenshots.",
        ],
        "venues": normalized_venues(existing_by_id, live_availability_by_id),
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
