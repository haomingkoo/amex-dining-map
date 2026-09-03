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
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import tft_document_reviews, tft_roster_reviews
except ModuleNotFoundError:
    import tft_document_reviews
    import tft_roster_reviews


OFFICIAL_URL = "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/"
TERMS_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/TableforTwo-Plat-TnCs.pdf"
FAQ_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining/TableforTwo_FAQ.pdf"
KNOWN_PARTICIPATING_SHA256 = "5a2c3eb79ad86ee737b8aa125bcdfffa3195954ccfcfd4ced5d86aa649398ec5"
KNOWN_CYCLES_SHA256 = "58fe005ae32d9a294f0064677bf96c7c8bcc035a108a6ab9318e201672326696"
KNOWN_TERMS_SHA256 = "7ba815581e6c0cb0c50775e6db642f81b040a65ff5568a70f6aeb4ed4cc0a7ec"
KNOWN_FAQ_SHA256 = "cbd8a1604459abd632a8e409ee603f9652a5907e60bb72a517c919cbb4aaeb93"
DININGCITY_API_BASE = "https://api.diningcity.asia/public"
DININGCITY_PROJECT = "AMEXPlatSG"
DININGCITY_PROJECT_TITLE = "AMEX Platinum SG"
MIN_TABLE_FOR_TWO_SEATS = 2
MAX_AVAILABILITY_TIMES = 12
AVAILABILITY_WORKERS = 6
DININGCITY_REQUEST_RETRIES = 2
DININGCITY_REQUEST_TIMEOUT_SECONDS = 12
DININGCITY_PROJECT_PAGE_SIZE = 100
AUTO_MEMBERSHIP_CONFIRMATIONS = 2
SINGAPORE_LAT_RANGE = (1.15, 1.50)
SINGAPORE_LNG_RANGE = (103.60, 104.10)


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
        "id": "tft-kaya-at-the-standard",
        "name": "Kaya at The Standard",
        "category": "restaurant",
        "dining_city_id": "205192104",
        "dining_city_name": "Kaya at The Standard",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/kaya_at_the_standard",
        "address": "The Standard, Singapore, 2nd Floor, 12 Orange Grove Road, Singapore 258353",
        "lat": 1.3101799,
        "lng": 103.8261714,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
        "venue_source_url": "https://www.kayaatthestandard.com/",
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
        "id": "tft-one-ninety",
        "name": "One-Ninety",
        "category": "restaurant",
        "dining_city_id": "205174978",
        "dining_city_name": "One-Ninety Restaurant",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/one-ninety_restaurant",
        "address": "Four Seasons Hotel Singapore, Lobby Level, 190 Orchard Boulevard, Singapore 248646",
        "lat": 1.3051922,
        "lng": 103.8284188,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
        "venue_source_url": "https://www.fourseasons.com/singapore/dining/restaurants/one_ninety/",
    },
    {
        "id": "tft-latido",
        "name": "Latido",
        "category": "restaurant",
        "dining_city_id": "205195352",
        "dining_city_name": "Latido",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Latido",
        "address": "40 Tras Street, Singapore 078979",
        "lat": 1.278353910844276,
        "lng": 103.8442552602603,
        "coordinate_confidence": "address_geocoded",
        "map_pin_source": "Singapore OneMap address geocode",
        "map_pin_note": "DiningCity currently publishes an empty address and 0,0 coordinates for this venue; pin is address-geocoded from the published Latido address.",
        "venue_source_url": "https://guide.michelin.com/sg/en/singapore-region/singapore/restaurant/latido",
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
        "id": "tft-estate",
        "name": "Estate",
        "category": "buffet",
        "dining_city_id": "205195358",
        "dining_city_name": "Estate",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Estate",
        "address": "Hilton Singapore Orchard, Level 5, 333 Orchard Road, Singapore 238867",
        "lat": 1.3021167,
        "lng": 103.8360388,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name.",
        "venue_source_url": "https://www.hilton.com/en/hotels/sinorhi-hilton-singapore-orchard/dining/estate/",
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
        "id": "tft-ginger",
        "name": "Ginger",
        "category": "buffet",
        "dining_city_id": "205195398",
        "dining_city_name": "Ginger at Park Royal",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Ginger_at_Park_Royal",
        "address": "PARKROYAL on Beach Road, 7500 Beach Road, Singapore 199591",
        "lat": 1.2995382,
        "lng": 103.8593887,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant search",
        "map_pin_note": "Pin is from DiningCity public restaurant search and matches the venue name variant.",
        "venue_source_url": "https://www.panpacific.com/en/hotels-and-resorts/pr-beach-road/eat/ginger.html",
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
        "operational_status": "permanently_closed",
        "operational_status_effective_at": "2026-08-10",
        "operational_status_source": "Amex Love Dining",
        "operational_status_source_url": "https://www.americanexpress.com/sg/benefits/love-dining/love-dining-hotels.html",
        "operational_status_note": "The official Amex Love Dining page says this venue is permanently closed from 10 August 2026.",
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
    {
        "id": "tft-forage",
        "name": "Forage",
        "category": "restaurant",
        "dining_city_id": "205193590",
        "dining_city_name": "Forage",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/foragebanyantree",
        "address": "60 Mandai Lake Road, Singapore 729979",
        "lat": 1.4067736,
        "lng": 103.7901586,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    {
        "id": "tft-sarnies",
        "name": "Sarnies",
        "category": "cafe",
        "dining_city_id": "205195658",
        "dining_city_name": "Sarnies",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/Sarnies",
        "address": "136 Telok Ayer Street, Singapore 068601",
        "lat": 1.2816613,
        "lng": 103.8479413,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    {
        "id": "tft-grand-cru-wine-bar",
        "name": "Grand Cru Wine Bar",
        "category": "restaurant",
        "dining_city_id": "205195660",
        "dining_city_name": "Grand Cru Wine Bar",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/VivinoWineShop",
        "address": "252 North Bridge Road, #01-44B Raffles City Shopping Centre, Singapore 179103",
        "lat": 1.2931055,
        "lng": 103.8512667,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    {
        "id": "tft-brewerkz-east-coast-park",
        "name": "Brewerkz East Coast Park",
        "category": "restaurant",
        "dining_city_id": "205196412",
        "dining_city_name": "Brewerkz East Coast Park",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/brewerkz_eastcoast",
        "address": "920 East Coast Parkway, #01-20/24, Singapore 449875",
        "lat": 1.2995599,
        "lng": 103.9067864,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    {
        "id": "tft-brewerkz-riverside-point",
        "name": "Brewerkz Riverside Point",
        "category": "restaurant",
        "dining_city_id": "205196414",
        "dining_city_name": "Brewerkz Riverside Point",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/brewerkz_riversidepoint",
        "address": "30 Merchant Road, #01-07 Riverside Point, Singapore 058282",
        "lat": 1.28927,
        "lng": 103.8442246,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    {
        "id": "tft-oso-ristorante",
        "name": "OSO Ristorante",
        "category": "restaurant",
        "dining_city_id": "2056126",
        "dining_city_name": "OSO Ristorante",
        "dining_city_public_url": "https://www.diningcity.sg/singapore/oso_ristorante",
        "address": "100 Peck Seah Street, Level 27 Oasia Hotel Downtown, Singapore 079333",
        "lat": 1.2758528,
        "lng": 103.8443611,
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity public restaurant detail",
        "map_pin_note": "Pin is from the current DiningCity booking-project venue profile.",
        "roster_basis": "diningcity_booking_project_confirmed",
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
    retry_statuses = {429, 500, 502, 503, 504}
    for attempt in range(DININGCITY_REQUEST_RETRIES + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=DININGCITY_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in retry_statuses or attempt == DININGCITY_REQUEST_RETRIES:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == DININGCITY_REQUEST_RETRIES:
                raise
        time.sleep(2 ** attempt)

    raise RuntimeError(f"DiningCity request failed without an error: {url}")


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


def diningcity_profile_source_url(dining_city_id: str) -> str:
    return f"{DININGCITY_API_BASE}/restaurants/{dining_city_id}?project={DININGCITY_PROJECT}"


def has_project(dining_city_id: str) -> bool:
    projects = fetch_json(f"/restaurants/{dining_city_id}/projects/program_and_event")
    return isinstance(projects, list) and any(
        project.get("project") == DININGCITY_PROJECT
        for project in projects
        if isinstance(project, dict)
    )


def _booking_project_record(row: object) -> dict:
    if not isinstance(row, dict):
        raise ValueError("booking project row is not an object")
    restaurant = row.get("restaurant")
    if not isinstance(restaurant, dict):
        raise ValueError("booking project row has no restaurant object")
    restaurant_id = restaurant.get("id") or row.get("restaurant_id")
    name = str(restaurant.get("name") or "").strip()
    if not restaurant_id or not name:
        raise ValueError("booking project row has no restaurant ID or name")
    record = {
        "id": str(restaurant_id),
        "name": name,
        "status": str(row.get("status") or "unknown"),
        "availability_project": str(
            row.get("availability_project") or DININGCITY_PROJECT
        ),
        "source_url": str(
            restaurant.get("website_detail_url")
            or f"https://www.diningcity.sg/singapore/{restaurant.get('dirname') or ''}"
        ).rstrip("/"),
        "address": str(restaurant.get("address") or "").strip(),
        "lat": restaurant.get("lat"),
        "lng": restaurant.get("lng"),
    }
    return record


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _membership_record_sha256(record: dict) -> str:
    stable = {
        key: record.get(key)
        for key in (
            "id",
            "name",
            "status",
            "availability_project",
            "source_url",
            "address",
            "lat",
            "lng",
        )
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _same_membership_identity(left: dict, right: dict) -> bool:
    return all(
        str(left.get(key) or "") == str(right.get(key) or "")
        for key in ("id", "name", "status", "availability_project")
    )


def _eligible_membership_record(record: dict) -> bool:
    return (
        record.get("status") in (None, "", "online")
        and record.get("availability_project") in (None, "", DININGCITY_PROJECT)
    )


def _membership_streaks(
    records: list[dict], reviewed_roster: list[dict], previous: dict, checked_at: str
) -> list[dict]:
    current = {
        record["id"]: record for record in records if _eligible_membership_record(record)
    }
    previous_streaks = {
        str(item.get("id")): item
        for item in previous.get("membership_streaks") or []
        if isinstance(item, dict) and item.get("id")
    }
    previous_records = {
        str(item.get("id")): item
        for item in previous.get("observed_venues") or []
        if isinstance(item, dict) and item.get("id")
    }
    tracked_ids = {
        str(record.get("dining_city_id"))
        for record in reviewed_roster
        if record.get("dining_city_id")
    }
    tracked_ids.update(previous_streaks)
    tracked_ids.update(current)
    streaks = []
    for diningcity_id in sorted(tracked_ids):
        observed = current.get(diningcity_id)
        prior = previous_streaks.get(diningcity_id) or {}
        if observed is not None:
            signature = _membership_record_sha256(observed)
            prior_signature = prior.get("record_sha256")
            prior_present = int(prior.get("consecutive_present") or 0)
            if not prior_present and diningcity_id in previous_records:
                prior_record = previous_records[diningcity_id]
                if _membership_record_sha256(prior_record) == signature or (
                    not prior_record.get("address")
                    and _same_membership_identity(prior_record, observed)
                ):
                    prior_present = 1
                    prior_signature = signature
            consecutive_present = prior_present + 1 if prior_signature == signature else 1
            streaks.append(
                {
                    "id": diningcity_id,
                    "name": observed["name"],
                    "record_sha256": signature,
                    "state": "present",
                    "consecutive_present": consecutive_present,
                    "consecutive_absent": 0,
                    "first_seen_at": prior.get("first_seen_at") or checked_at,
                    "last_seen_at": checked_at,
                }
            )
            continue
        prior_absent = int(prior.get("consecutive_absent") or 0)
        if (
            not prior_absent
            and previous.get("observation_status") == "success"
            and diningcity_id not in previous_records
        ):
            prior_absent = 1
        name = prior.get("name") or next(
            (
                str(record.get("name") or diningcity_id)
                for record in reviewed_roster
                if str(record.get("dining_city_id") or "") == diningcity_id
            ),
            diningcity_id,
        )
        streaks.append(
            {
                "id": diningcity_id,
                "name": name,
                "record_sha256": prior.get("record_sha256"),
                "state": "absent",
                "consecutive_present": 0,
                "consecutive_absent": prior_absent + 1,
                "first_seen_at": prior.get("first_seen_at"),
                "last_seen_at": prior.get("last_seen_at"),
            }
        )
    return streaks


def _auto_candidate_reasons(
    record: dict, published_roster: list[dict]
) -> list[str]:
    reasons = []
    if record.get("status") != "online":
        reasons.append("not_online")
    if record.get("availability_project") != DININGCITY_PROJECT:
        reasons.append("wrong_availability_project")
    if not record.get("address"):
        reasons.append("missing_address")
    try:
        lat = float(record.get("lat"))
        lng = float(record.get("lng"))
    except (TypeError, ValueError):
        reasons.append("missing_coordinates")
    else:
        if not (SINGAPORE_LAT_RANGE[0] <= lat <= SINGAPORE_LAT_RANGE[1]) or not (
            SINGAPORE_LNG_RANGE[0] <= lng <= SINGAPORE_LNG_RANGE[1]
        ):
            reasons.append("coordinates_outside_singapore")
    parsed = urllib.parse.urlparse(str(record.get("source_url") or ""))
    if parsed.scheme != "https" or parsed.hostname not in {
        "diningcity.sg",
        "www.diningcity.sg",
    }:
        reasons.append("untrusted_source_url")
    diningcity_id = str(record.get("id") or "")
    normalized_name = _normalized_name(record.get("name"))
    for published in published_roster:
        if str(published.get("dining_city_id") or "") == diningcity_id:
            reasons.append("duplicate_diningcity_id")
        elif _normalized_name(published.get("name")) == normalized_name:
            reasons.append("duplicate_normalized_name")
    return sorted(set(reasons))


def _venue_id_for_membership_record(record: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalized_name(record.get("name"))).strip("-")
    return f"tft-{slug or record['id']}"


def _empty_menu_state() -> dict:
    return {
        "status": "no_pdf_found",
        "url": None,
        "filename": None,
        "card": None,
        "label": None,
        "checked_at": None,
        "first_seen_at": None,
        "last_seen_at": None,
        "sha256": None,
        "bytes": None,
        "aem_created": None,
        "changed_at": None,
    }


def _auto_venue_from_membership(record: dict, streak: dict, checked_at: str) -> dict:
    return {
        "id": _venue_id_for_membership_record(record),
        "name": record["name"],
        "category": "restaurant",
        "booking_channel": "Amex Experiences App",
        "dining_city_id": record["id"],
        "dining_city_name": record["name"],
        "dining_city_public_url": record["source_url"],
        "address": record["address"],
        "lat": float(record["lat"]),
        "lng": float(record["lng"]),
        "coordinate_confidence": "diningcity_place_matched",
        "map_pin_source": "DiningCity AMEXPlatSG booking-project membership",
        "map_pin_note": "Pin is from the current DiningCity AMEXPlatSG booking-project record.",
        "menu_pdfs": {},
        "menu_pdf": _empty_menu_state(),
        "roster_basis": "diningcity_booking_project_confirmed",
        "roster_evidence": {
            "source": "DiningCity AMEXPlatSG booking-project membership",
            "source_url": record["source_url"],
            "first_seen_at": streak.get("first_seen_at") or checked_at,
            "confirmed_at": checked_at,
            "confirmation_count": int(streak.get("consecutive_present") or 0),
            "record_sha256": streak.get("record_sha256"),
        },
    }


def _validate_published_roster(records: list[dict]) -> None:
    venue_ids = [str(venue.get("id") or "") for venue in records]
    diningcity_ids = [str(venue.get("dining_city_id") or "") for venue in records]
    normalized_names = [_normalized_name(venue.get("name")) for venue in records]
    if "" in venue_ids or len(venue_ids) != len(set(venue_ids)):
        raise ValueError("published Table for Two roster has missing or duplicate venue IDs")
    if "" in diningcity_ids or len(diningcity_ids) != len(set(diningcity_ids)):
        raise ValueError("published Table for Two roster has missing or duplicate DiningCity IDs")
    if "" in normalized_names or len(normalized_names) != len(set(normalized_names)):
        raise ValueError("published Table for Two roster has missing or duplicate normalized names")


def fetch_booking_project_membership(
    reviewed_roster: list[dict],
    checked_at: str,
    existing_payload: dict | None = None,
) -> dict:
    previous = dict((existing_payload or {}).get("booking_project_source") or {})
    source_url = f"{DININGCITY_API_BASE}/projects/{DININGCITY_PROJECT}/restaurants"
    try:
        payload = fetch_json(
            f"/projects/{DININGCITY_PROJECT}/restaurants",
            {"per_page": DININGCITY_PROJECT_PAGE_SIZE},
        )
        if not isinstance(payload, list):
            raise ValueError("booking project membership is not a list")
        records = [_booking_project_record(row) for row in payload]
        records.sort(key=lambda record: (record["name"].casefold(), record["id"]))
        observed_ids = [record["id"] for record in records]
        if not records or len(observed_ids) != len(set(observed_ids)):
            raise ValueError("booking project membership is empty or has duplicate IDs")
    except Exception as exc:  # noqa: BLE001 - retain the last good membership evidence.
        return {
            **previous,
            "type": "diningcity_booking_project_membership",
            "source_url": source_url,
            "project": DININGCITY_PROJECT,
            "last_attempt_at": checked_at,
            "observation_status": "error",
            "observation_error": type(exc).__name__,
        }

    reviewed = {
        str(record.get("dining_city_id")): str(record.get("name") or "Unknown")
        for record in reviewed_roster
        if record.get("dining_city_id")
    }
    observed = {record["id"]: record for record in records}
    added = [observed[key] for key in sorted(set(observed) - set(reviewed))]
    missing = [
        {"id": key, "name": reviewed[key]}
        for key in sorted(set(reviewed) - set(observed))
    ]
    fingerprint_payload = [
        {
            key: record[key]
            for key in ("id", "name", "status", "availability_project")
        }
        for record in records
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    streaks = _membership_streaks(records, reviewed_roster, previous, checked_at)
    return {
        "type": "diningcity_booking_project_membership",
        "source_url": source_url,
        "project": DININGCITY_PROJECT,
        "checked_at": checked_at,
        "last_attempt_at": checked_at,
        "observation_status": "success",
        "observed_count": len(records),
        "observed_membership_sha256": fingerprint,
        "observed_venues": records,
        "membership_streaks": streaks,
        "added_vs_reviewed_roster": [record["name"] for record in added],
        "missing_vs_reviewed_roster": [record["name"] for record in missing],
        "review_required": bool(added or missing),
        "evidence_note": (
            "Booking-project membership is an early signal from DiningCity, not "
            "the reviewed Amex participating-merchant roster."
        ),
    }


def current_published_roster(
    reviewed_roster: list[dict],
    booking_project_source: dict,
    existing_payload: dict | None = None,
) -> tuple[list[dict], dict]:
    """Conservatively merge source-backed booking-project additions.

    Official-image records are never removed here. Booking-project-only records
    require repeated complete observations both to appear and to disappear.
    """
    raw_observed = [
        record
        for record in booking_project_source.get("observed_venues") or []
        if isinstance(record, dict) and record.get("id")
    ]
    raw_observed_ids = [str(record["id"]) for record in raw_observed]
    if len(raw_observed_ids) != len(set(raw_observed_ids)):
        raise ValueError("booking project membership has duplicate DiningCity IDs")
    existing_supplement_records = [
        record
        for record in (existing_payload or {}).get("venues") or []
        if isinstance(record, dict)
        and record.get("roster_basis") == "diningcity_booking_project_confirmed"
    ]
    supplement_ids = [str(record.get("id") or "") for record in existing_supplement_records]
    supplement_diningcity_ids = [
        str(record.get("dining_city_id") or "") for record in existing_supplement_records
    ]
    if len(supplement_ids) != len(set(supplement_ids)) or len(
        supplement_diningcity_ids
    ) != len(set(supplement_diningcity_ids)):
        raise ValueError("existing booking-project supplements contain duplicate identities")
    if booking_project_source.get("observation_status") != "success":
        retained = [dict(record) for record in reviewed_roster]
        official_ids = {str(record.get("id") or "") for record in retained}
        official_diningcity_ids = {
            str(record.get("dining_city_id") or "") for record in retained
        }
        existing_supplements = [
            tft_roster_reviews.stable_venue(record)
            for record in existing_supplement_records
            if str(record.get("id") or "") not in official_ids
            and str(record.get("dining_city_id") or "") not in official_diningcity_ids
        ]
        retained.extend(existing_supplements)
        _validate_published_roster(retained)
        return retained, {
            **booking_project_source,
            "maintenance_summary": {
                "outcome": "retained_after_source_error",
                "published_count": len(existing_supplements),
                "pending_addition_count": 0,
                "pending_removal_count": 0,
                "review_count": 0,
            },
        }
    observed = {str(record["id"]): record for record in raw_observed}
    existing_diningcity_ids = {
        str(record.get("dining_city_id"))
        for record in reviewed_roster
        if record.get("dining_city_id")
    }
    streaks = {
        str(item.get("id")): item
        for item in booking_project_source.get("membership_streaks") or []
        if isinstance(item, dict) and item.get("id")
    }
    existing_supplements = {
        str(record.get("dining_city_id")): tft_roster_reviews.stable_venue(record)
        for record in existing_supplement_records
        if record.get("dining_city_id")
    }
    configured_supplements = {
        str(venue.get("dining_city_id")): dict(venue)
        for venue in VENUES
        if venue.get("roster_basis") == "diningcity_booking_project_confirmed"
    }
    supplement_pool = {**configured_supplements, **existing_supplements}
    previous_observed = {
        str(record.get("id")): record
        for record in (
            ((existing_payload or {}).get("booking_project_source") or {}).get(
                "observed_venues"
            )
            or []
        )
        if isinstance(record, dict) and record.get("id")
    }
    additions = []
    pending_additions = []
    pending_removals = []
    confirmed_removals = []
    review_items = []
    eligible_observed = {
        diningcity_id: record
        for diningcity_id, record in observed.items()
        if _eligible_membership_record(record)
    }
    candidate_ids = sorted(
        set(observed) - existing_diningcity_ids - set(existing_supplements)
    )
    for diningcity_id in candidate_ids:
        record = observed[diningcity_id]
        streak = streaks.get(diningcity_id) or {}
        configured = configured_supplements.get(diningcity_id)
        validation_record = dict(record)
        if configured:
            for field in ("address", "lat", "lng"):
                validation_record[field] = configured.get(field)
        reasons = _auto_candidate_reasons(
            validation_record, [*reviewed_roster, *additions]
        )
        if configured and _normalized_name(configured.get("name")) != _normalized_name(
            record.get("name")
        ):
            reasons.append("configured_name_changed")
        candidate_id = _venue_id_for_membership_record(record)
        if any(venue.get("id") == candidate_id for venue in [*reviewed_roster, *additions]):
            reasons.append("duplicate_venue_id")
        if reasons:
            review_items.append({"id": diningcity_id, "name": record["name"], "reasons": sorted(set(reasons))})
        elif int(streak.get("consecutive_present") or 0) >= AUTO_MEMBERSHIP_CONFIRMATIONS:
            if configured:
                configured = dict(configured)
                configured["roster_evidence"] = {
                    "source": "DiningCity AMEXPlatSG booking-project membership",
                    "source_url": record["source_url"],
                    "first_seen_at": streak.get("first_seen_at"),
                    "confirmed_at": booking_project_source["checked_at"],
                    "confirmation_count": int(streak.get("consecutive_present") or 0),
                    "record_sha256": streak.get("record_sha256"),
                }
                additions.append(configured)
            else:
                additions.append(
                    _auto_venue_from_membership(
                        record, streak, booking_project_source["checked_at"]
                    )
                )
        else:
            pending_additions.append({"id": diningcity_id, "name": record["name"]})

    for diningcity_id, venue in sorted(supplement_pool.items()):
        if diningcity_id in existing_diningcity_ids:
            continue
        if diningcity_id not in existing_supplements:
            continue
        if diningcity_id in eligible_observed:
            record = eligible_observed[diningcity_id]
            evidence_hash = (venue.get("roster_evidence") or {}).get("record_sha256")
            prior_record = previous_observed.get(diningcity_id)
            if not evidence_hash and prior_record:
                prior_hash = _membership_record_sha256(prior_record)
                if prior_hash != _membership_record_sha256(record):
                    review_items.append(
                        {
                            "id": diningcity_id,
                            "name": record["name"],
                            "reasons": ["legacy_source_record_changed"],
                        }
                    )
                else:
                    venue = dict(venue)
                    venue["roster_evidence"] = {
                        **(venue.get("roster_evidence") or {}),
                        "source": "DiningCity AMEXPlatSG booking-project membership",
                        "source_url": record["source_url"],
                        "record_sha256": prior_hash,
                    }
                    evidence_hash = prior_hash
            if evidence_hash and evidence_hash != _membership_record_sha256(record):
                review_items.append(
                    {
                        "id": diningcity_id,
                        "name": record["name"],
                        "reasons": ["published_source_record_changed"],
                    }
                )
            elif _normalized_name(venue.get("name")) != _normalized_name(
                record.get("name")
            ):
                review_items.append(
                    {
                        "id": diningcity_id,
                        "name": record["name"],
                        "reasons": ["published_name_changed"],
                    }
                )
            additions.append(venue)
            continue
        streak = streaks.get(diningcity_id) or {}
        if int(streak.get("consecutive_absent") or 0) >= AUTO_MEMBERSHIP_CONFIRMATIONS:
            confirmed_removals.append({"id": diningcity_id, "name": venue["name"]})
        else:
            additions.append(venue)
            pending_removals.append({"id": diningcity_id, "name": venue["name"]})
    combined = [*reviewed_roster, *additions]

    _validate_published_roster(combined)

    unconfirmed = [item["name"] for item in review_items]
    annotated_source = {
        **booking_project_source,
        "published_booking_project_additions": [
            {"id": venue["dining_city_id"], "name": venue["name"]}
            for venue in additions
        ],
        "unconfirmed_added_vs_reviewed_roster": unconfirmed,
        "pending_booking_project_additions": pending_additions,
        "pending_booking_project_removals": pending_removals,
        "confirmed_booking_project_removals": confirmed_removals,
        "booking_project_review_items": review_items,
        **({"identity_mismatch_count": len(review_items)} if review_items else {}),
        "review_required": bool(
            unconfirmed
            or booking_project_source.get("missing_vs_reviewed_roster")
        ),
        "evidence_note": (
            "Current venues combine the retained reviewed Amex image roster with "
            "DiningCity AMEXPlatSG booking-project additions confirmed across "
            f"{AUTO_MEMBERSHIP_CONFIRMATIONS} successful observations."
        ),
        "maintenance_summary": {
            "outcome": "success",
            "observed_count": booking_project_source.get("observed_count", 0),
            "published_count": len(additions),
            "pending_addition_count": len(pending_additions),
            "pending_removal_count": len(pending_removals),
            "confirmed_removal_count": len(confirmed_removals),
            "review_count": len(review_items),
        },
    }
    return combined, annotated_source


def booking_project_membership_statuses(source: dict | None) -> tuple[str, set[str]]:
    source = source or {}
    if source.get("observation_status") != "success":
        return "unknown", set()
    observed = source.get("observed_venues")
    if not isinstance(observed, list):
        return "unknown", set()
    return "success", {
        str(record.get("id"))
        for record in observed
        if isinstance(record, dict)
        and record.get("id")
        and _eligible_membership_record(record)
    }


def booking_project_status_for_venue(
    venue: dict, source: dict | None, existing_record: dict | None = None
) -> str:
    membership_status, active_ids = booking_project_membership_statuses(source)
    previous_status = (existing_record or {}).get("booking_project_status")
    if membership_status != "success":
        return previous_status or "unknown"
    diningcity_id = str(venue.get("dining_city_id") or "")
    streak = next(
        (
            item
            for item in (source or {}).get("membership_streaks") or []
            if isinstance(item, dict) and str(item.get("id") or "") == diningcity_id
        ),
        {},
    )
    if diningcity_id in active_ids:
        if (
            previous_status == "not_listed"
            and int(streak.get("consecutive_present") or 0)
            < AUTO_MEMBERSHIP_CONFIRMATIONS
        ):
            return "not_listed"
        return "active"
    if previous_status == "active" and int(streak.get("consecutive_absent") or 0) < AUTO_MEMBERSHIP_CONFIRMATIONS:
        return "active"
    return "not_listed" if diningcity_id else "unknown"


def booking_project_not_listed_availability(venue: dict, source: dict) -> dict:
    checked_at = source.get("checked_at") or source.get("last_attempt_at") or iso_now()
    return {
        "status": "not_currently_in_project",
        "source": f"DiningCity booking project {DININGCITY_PROJECT}",
        "source_url": source.get("source_url"),
        "project": DININGCITY_PROJECT,
        "project_title": DININGCITY_PROJECT_TITLE,
        "captured_at": checked_at,
        "checked_at": checked_at,
        "confidence": "diningcity_project_membership_missing",
        "visible_dates": [],
        "summary": (
            f"{venue.get('name') or 'This venue'} is not currently listed in the "
            f"DiningCity {DININGCITY_PROJECT} booking project."
        ),
        "meals": [],
        "notes": [
            "This is a booking-project membership signal. The retained Amex roster record remains historical evidence until the official roster changes."
        ],
    }


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
        except Exception as exc:  # noqa: BLE001 - preserve the last good cache when fallback fails.
            return None, f"fallback_{type(exc).__name__}: {exc}"
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
    workers = min(AVAILABILITY_WORKERS, len(venues)) or 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(live_availability_for_venue, venue, checked_at): venue
            for venue in venues
        }
        for future in as_completed(futures):
            venue = futures[future]
            try:
                availability, error = future.result()
            except Exception as exc:  # noqa: BLE001 - keep one venue failure from killing the refresh.
                availability, error = None, f"{type(exc).__name__}: {exc}"
            if availability:
                availability_by_id[venue["id"]] = availability
            elif error:
                errors[venue["id"]] = error
    return availability_by_id, errors


def compact_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\n{3,}", "\n\n", value.strip())


def normalize_diningcity_profile(venue: dict, payload: object, checked_at: str) -> dict | None:
    if not isinstance(payload, dict):
        return None
    basic_info = payload.get("basic_info") if isinstance(payload.get("basic_info"), dict) else {}
    cuisines = [
        item.get("name")
        for item in (payload.get("cuisines") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    landmarks = [
        item.get("name")
        for item in (payload.get("landmarks") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    description = compact_text(
        basic_info.get("description")
        or payload.get("description")
        or payload.get("remark")
    )
    dining_city_id = venue.get("dining_city_id")
    profile = {
        "source": "DiningCity public restaurant detail API",
        "source_url": diningcity_profile_source_url(dining_city_id),
        "captured_at": checked_at,
        "description": description,
        "cover_url": payload.get("cover") or payload.get("wide_picture") or "",
        "cuisines": cuisines,
        "landmarks": landmarks,
        "location": (payload.get("location") or {}).get("name") if isinstance(payload.get("location"), dict) else "",
        "avg_price": payload.get("format_avg_price") or "",
        "opening_hour": compact_text(payload.get("localized_opening_hour") or payload.get("opening_hour")),
        "website_detail_url": payload.get("website_detail_url") or venue.get("dining_city_public_url") or "",
    }
    return {key: value for key, value in profile.items() if value not in ("", [], None)}


def fetch_diningcity_profiles(venues: list[dict], checked_at: str) -> tuple[dict[str, dict], dict[str, str]]:
    profiles_by_id = {}
    errors = {}
    for venue in venues:
        dining_city_id = venue.get("dining_city_id")
        if not dining_city_id:
            continue
        try:
            payload = fetch_json(
                f"/restaurants/{dining_city_id}",
                {"project": DININGCITY_PROJECT},
            )
            profile = normalize_diningcity_profile(venue, payload, checked_at)
            if profile:
                profiles_by_id[venue["id"]] = profile
        except Exception as exc:  # noqa: BLE001 - venue profiles are enrichment only.
            errors[venue["id"]] = f"{type(exc).__name__}: {exc}"
    return profiles_by_id, errors


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
    live_profiles_by_id: dict[str, dict] | None = None,
    roster: list[dict] | None = None,
    booking_project_source: dict | None = None,
) -> list[dict]:
    existing_by_id = existing_by_id or {}
    live_availability_by_id = live_availability_by_id or {}
    live_profiles_by_id = live_profiles_by_id or {}
    records = []
    for venue in roster or VENUES:
        curated_availability = venue.get("availability")
        existing_record = existing_by_id.get(venue["id"])
        live_availability = live_availability_by_id.get(venue["id"])
        live_profile = live_profiles_by_id.get(venue["id"])
        booking_project_status = booking_project_status_for_venue(
            venue, booking_project_source, existing_record
        )
        if booking_project_status == "not_listed":
            availability = booking_project_not_listed_availability(
                venue, booking_project_source or {}
            )
        elif live_availability:
            availability = live_availability
        elif should_preserve_availability(existing_record, curated_availability):
            availability = existing_record["availability"]
        else:
            availability = curated_availability or default_availability()
        record = {
            **venue,
            "booking_channel": "Amex Experiences App",
            "booking_project_status": booking_project_status,
            "booking_project_checked_at": (booking_project_source or {}).get(
                "checked_at"
            ),
            "slot_source_status": (
                "not_currently_in_project"
                if booking_project_status == "not_listed"
                else
                "diningcity_amex_platinum_project"
                if availability.get("confidence") == "diningcity_amex_platinum_project"
                else "app_handoff_required"
            ),
            "availability": availability,
        }
        record["availability"] = availability
        if live_profile:
            record["dining_city_profile"] = live_profile
        elif isinstance(existing_record, dict) and isinstance(existing_record.get("dining_city_profile"), dict):
            record["dining_city_profile"] = existing_record["dining_city_profile"]
        if isinstance(existing_record, dict):
            for key in ("menu_pdfs", "menu_pdf"):
                if key in existing_record:
                    record[key] = existing_record[key]
        record.setdefault("menu_pdfs", {})
        record.setdefault("menu_pdf", _empty_menu_state())
        records.append(record)
    return records


def build_payload(
    existing_payload: dict | None = None,
    document_pdf_root: Path = tft_document_reviews.PDF_ROOT,
) -> dict:
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
    terms_bytes = fetch_bytes(TERMS_URL)
    faq_bytes = fetch_bytes(FAQ_URL)
    terms_hash, _ = tft_document_reviews.retain_observed_pdf(
        "tft-terms", terms_bytes, document_pdf_root
    )
    faq_hash, _ = tft_document_reviews.retain_observed_pdf(
        "tft-faq", faq_bytes, document_pdf_root
    )
    checked_at = iso_now()
    roster, roster_source = tft_roster_reviews.review_state(
        participating_hash, participating_url, checked_at, existing_payload
    )
    observed_documents = {
        "terms_sha256": terms_hash,
        "faq_sha256": faq_hash,
    }
    document_reviews = tft_document_reviews.refresh_states(
        observed_documents, existing_payload, checked_at
    )
    manual_review_required = (
        roster_source["review_required"]
        or cycles_hash != KNOWN_CYCLES_SHA256
        or any(state["review_required"] for state in document_reviews.values())
    )
    booking_project_source = fetch_booking_project_membership(
        roster, checked_at, existing_payload
    )
    roster, booking_project_source = current_published_roster(
        roster, booking_project_source, existing_payload
    )
    membership_status, active_diningcity_ids = booking_project_membership_statuses(
        booking_project_source
    )
    availability_roster = (
        [
            venue
            for venue in roster
            if str(venue.get("dining_city_id") or "") in active_diningcity_ids
        ]
        if membership_status == "success"
        else roster
    )
    live_availability_by_id, availability_errors = fetch_live_availability(
        availability_roster, checked_at
    )
    live_profiles_by_id, profile_errors = fetch_diningcity_profiles(roster, checked_at)
    availability_last_checked_at = (
        checked_at
        if live_availability_by_id
        else (existing_payload or {}).get("availability_last_checked_at")
    )

    payload = {
        "dataset": "table_for_two",
        "program": "American Express Table for Two by Platinum",
        "country": "Singapore",
        "currency": "SGD",
        "last_verified_at": checked_at,
        "official_url": OFFICIAL_URL,
        "terms_url": TERMS_URL,
        "faq_url": FAQ_URL,
        "participating_merchants_image_url": participating_url,
        "voucher_cycles_image_url": cycles_url,
        "source_images": {
            "participating_merchants_sha256": participating_hash,
            "voucher_cycles_sha256": cycles_hash,
        },
        "source_documents": observed_documents,
        "document_reviews": document_reviews,
        "manual_review_required": manual_review_required,
        "roster_source": roster_source,
        "booking_project_source": booking_project_source,
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
        "venue_profile_source": {
            "type": "diningcity_public_detail_api",
            "api_base": DININGCITY_API_BASE,
            "project": DININGCITY_PROJECT,
            "checked_venues": len(live_profiles_by_id),
            "error_count": len(profile_errors),
            "errors": profile_errors,
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
        "venues": normalized_venues(
            existing_by_id,
            live_availability_by_id,
            live_profiles_by_id,
            roster,
            booking_project_source,
        ),
    }
    # The roster refresh does not own menu review state. Dropping it would strand the
    # published menus without their approved decision receipts.
    if "menu_source" in (existing_payload or {}):
        payload["menu_source"] = existing_payload["menu_source"]
    return payload


def refresh_availability_payload(existing_payload: dict, *, include_profiles: bool = False) -> dict:
    venues = [
        record for record in existing_payload.get("venues", [])
        if isinstance(record, dict) and record.get("id")
    ]
    if not venues:
        raise RuntimeError("Cannot refresh Table for Two availability without existing venue records.")

    checked_at = iso_now()
    existing_by_id = {record["id"]: record for record in venues}
    curated_by_id = {venue["id"]: venue for venue in VENUES}
    reviewed_roster = [
        record
        for record in venues
        if record.get("roster_basis") != "diningcity_booking_project_confirmed"
    ]
    booking_project_source = fetch_booking_project_membership(
        reviewed_roster, checked_at, existing_payload
    )
    venues, booking_project_source = current_published_roster(
        reviewed_roster, booking_project_source, existing_payload
    )
    membership_status, active_diningcity_ids = booking_project_membership_statuses(
        booking_project_source
    )
    availability_venues = (
        [
            venue
            for venue in venues
            if str(venue.get("dining_city_id") or "") in active_diningcity_ids
        ]
        if membership_status == "success"
        else venues
    )
    live_availability_by_id, availability_errors = fetch_live_availability(
        availability_venues, checked_at
    )
    live_profiles_by_id: dict[str, dict] = {}
    profile_errors: dict[str, str] = {}
    if include_profiles:
        live_profiles_by_id, profile_errors = fetch_diningcity_profiles(venues, checked_at)
    records = []
    for venue in venues:
        venue_id = venue["id"]
        existing_record = existing_by_id.get(venue_id) or {}
        curated = curated_by_id.get(venue_id) or {}
        operational_fields = {
            key: (curated if key in curated else existing_record)[key]
            for key in (
                "operational_status",
                "operational_status_effective_at",
                "operational_status_source",
                "operational_status_source_url",
                "operational_status_note",
            )
            if key in curated or key in existing_record
        }
        booking_project_status = booking_project_status_for_venue(
            venue, booking_project_source, existing_record
        )
        availability = (
            booking_project_not_listed_availability(venue, booking_project_source)
            if booking_project_status == "not_listed"
            else live_availability_by_id.get(venue_id)
            or venue.get("availability")
            or default_availability()
        )
        record = {
            **venue,
            **operational_fields,
            "booking_project_status": booking_project_status,
            "booking_project_checked_at": booking_project_source.get("checked_at"),
            "slot_source_status": (
                "not_currently_in_project"
                if booking_project_status == "not_listed"
                else
                "diningcity_amex_platinum_project"
                if availability.get("confidence") == "diningcity_amex_platinum_project"
                else "app_handoff_required"
            ),
            "availability": availability,
        }
        if venue_id in live_profiles_by_id:
            record["dining_city_profile"] = live_profiles_by_id[venue_id]
        elif isinstance(existing_record.get("dining_city_profile"), dict):
            record["dining_city_profile"] = existing_record["dining_city_profile"]
        for key in ("menu_pdfs", "menu_pdf"):
            if key in existing_record:
                record[key] = existing_record[key]
        record.setdefault("menu_pdfs", {})
        record.setdefault("menu_pdf", _empty_menu_state())
        records.append(record)

    payload = {
        **existing_payload,
        "availability_last_checked_at": checked_at if live_availability_by_id else existing_payload.get("availability_last_checked_at"),
        "availability_source": {
            "type": "diningcity_public_api",
            "api_base": DININGCITY_API_BASE,
            "project": DININGCITY_PROJECT,
            "project_title": DININGCITY_PROJECT_TITLE,
            "checked_venues": len(live_availability_by_id),
            "error_count": len(availability_errors),
            "errors": availability_errors,
        },
        "booking_project_source": booking_project_source,
        "venues": records,
    }
    if include_profiles:
        payload["venue_profile_source"] = {
            "type": "diningcity_public_detail_api",
            "api_base": DININGCITY_API_BASE,
            "project": DININGCITY_PROJECT,
            "checked_venues": len(live_profiles_by_id),
            "error_count": len(profile_errors),
            "errors": profile_errors,
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/table-for-two.json")
    parser.add_argument(
        "--document-pdf-root",
        type=Path,
        default=tft_document_reviews.PDF_ROOT,
        help="Content-addressed archive for exact observed official PDF bytes.",
    )
    parser.add_argument(
        "--availability-only",
        action="store_true",
        help=(
            "Refresh only DiningCity AMEXPlatSG availability data from the "
            "existing roster. This intentionally skips Amex official source image, "
            "T&C, FAQ hash, and DiningCity profile checks so scheduled email alerts "
            "are not blocked by manual source review."
        ),
    )
    parser.add_argument(
        "--fail-on-manual-review",
        action="store_true",
        help=(
            "Exit 2 when source hashes require review. By default the script writes "
            "manual_review_required to the payload and exits 0 so workflows can build "
            "and open the source-alert issue."
        ),
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    existing_payload = None
    if output_path.exists():
        existing_payload = json.loads(output_path.read_text(encoding="utf-8"))
    if args.availability_only:
        if existing_payload is None:
            raise RuntimeError(f"{output_path} does not exist; availability-only refresh needs an existing roster.")
        payload = refresh_availability_payload(existing_payload)
    else:
        payload = build_payload(existing_payload, args.document_pdf_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    count = len(payload["venues"])
    if args.availability_only:
        summary = payload.get("booking_project_source", {}).get(
            "maintenance_summary", {}
        )
        print(
            "TFT_MAINTENANCE "
            + json.dumps(
                {
                    "outcome": summary.get("outcome", "unknown"),
                    "observed_count": summary.get("observed_count", 0),
                    "published_count": summary.get("published_count", 0),
                    "pending_addition_count": summary.get("pending_addition_count", 0),
                    "pending_removal_count": summary.get("pending_removal_count", 0),
                    "confirmed_removal_count": summary.get("confirmed_removal_count", 0),
                    "review_count": summary.get("review_count", 0),
                    "venue_count": count,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        print(f"Refreshed Table for Two availability for {count} venues in {output_path}.")
        return 0
    review = " manual review required" if payload.get("manual_review_required") else ""
    print(f"Wrote {count} Table for Two venues to {output_path}.{review}")
    return 2 if args.fail_on_manual_review and payload.get("manual_review_required") else 0


if __name__ == "__main__":
    sys.exit(main())
