#!/usr/bin/env python3
"""Sync the Japan dining dataset from Pocket Concierge GraphQL."""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
KML_DIR = DATA_DIR / "kml"
JSON_PATH = DATA_DIR / "japan-restaurants.json"
GEOJSON_PATH = DATA_DIR / "japan-restaurants.geojson"
CACHE_PATH = DATA_DIR / "geocode_cache.json"
DETAIL_CACHE_PATH = DATA_DIR / "venue_detail_cache.json"
QUALITY_SIGNALS_PATH = DATA_DIR / "restaurant-quality-signals.json"

USER_AGENT = "JapanDiningMapMVP/0.2 (+https://local.dev)"
GRAPHQL_URL = "https://pocket-concierge.jp/graphql"

SEARCH_PROPERTIES_QUERY = """
query SearchProperties {
  areas {
    id
    name
  }
}
""".strip()

SEARCH_VENUES_QUERY = """
query searchVenues($areaIds: [ID!], $pagination: PaginationInput) {
  venuesSearch(
    paginationInput: $pagination
    areaIds: $areaIds
  ) {
    collection {
      address {
        prefecture {
          id
          name
        }
        town {
          name
        }
      }
      area {
        id
        name
      }
      blurb
      cuisines {
        id
        name
      }
      id
      limitedScopeUrlHash
      name
      priceRanges {
        max
        min
        serviceType
      }
      realTimeBooking
    }
    metadata {
      currentPage
      limitValue
      totalCount
      totalPages
    }
  }
}
""".strip()

VENUE_DETAIL_QUERY = """
query PartialVenueWithCourses($id: ID!) {
  venue(id: $id) {
    id
    addressHidden
    googleMapUrl
    latitude
    longitude
    localizedAddress
    longDescription
    nearestStations
    phoneNumber
    recommendations {
      ageRange
      comment
      visitFrequency
      visitPurpose
      visitedAt
    }
    reservationTerms
    services
    websiteUrl
    transactionsAllowed
    frequentlyAskedQuestions {
      question
      answer
    }
    courses {
      fixedPrice
      fixedTitle
      costPerGuest
      id
      name
      serviceType
      summary
      supplementaryInformation
    }
  }
}
""".strip()

TARGET_AREA_ORDER = [
    "Tokyo",
    "Yokohama/Kawasaki",
    "Kamakura/Hayama/Shonan",
    "Greater Tokyo Area",
    "Kyoto/Osaka/Nara",
    "Chubu/Tokai/Karuizawa",
    "Kanazawa/Toyama/Hokuriku",
    "Hokkaido",
    "Tohoku",
    "Chugoku/Shikoku",
    "Kyushu/Okinawa",
]

CITY_COLORS = {
    "Tokyo": "gold",
    "Kyoto": "purple",
    "Osaka": "emerald",
}

LUNCH_PRICE_BANDS = [
    ("under-5k", "Under JPY 5k", "$", 0, 5_000),
    ("5k-10k", "JPY 5k-10k", "$$", 5_000, 10_000),
    ("10k-20k", "JPY 10k-20k", "$$$", 10_000, 20_000),
    ("20k-plus", "JPY 20k+", "$$$$", 20_000, None),
]

DINNER_PRICE_BANDS = [
    ("under-10k", "Under JPY 10k", "$$", 0, 10_000),
    ("10k-20k", "JPY 10k-20k", "$$$", 10_000, 20_000),
    ("20k-30k", "JPY 20k-30k", "$$$$", 20_000, 30_000),
    ("30k-plus", "JPY 30k+", "$$$$$", 30_000, None),
]

SIGNATURE_PATTERNS = [
    (r"\bkobe beef\b", "Kobe beef"),
    (r"\bblue lobster\b", "Blue lobster"),
    (r"\bedomae-style sushi\b|\bedo-style sushi\b|\bnigiri sushi\b", "Edomae sushi"),
    (r"\bsushi\b", "Sushi"),
    (r"\btempura\b", "Tempura"),
    (r"\bteppanyaki\b", "Teppanyaki"),
    (r"\byakitori\b|\bgrilled fresh chicken\b", "Yakitori / grilled chicken"),
    (r"\bsoba\b", "Soba"),
    (r"\bkappo\b", "Kappo"),
    (r"\bkaiseki\b", "Kaiseki"),
    (r"\bkyoto cuisine\b", "Kyoto cuisine"),
    (r"\bbasque cuisine\b", "Basque cuisine"),
    (r"\bfrench cuisine\b|\bparis bistro\b", "French cuisine"),
    (r"\bsteakhouse\b|\bsteak\b", "Steak"),
    (r"\bdeer\b|\bgame\b", "Game dishes"),
    (r"\bomakase\b", "Omakase"),
]

KNOWN_FOR_PATTERNS = [
    (r"\b1-star\b", "1-star reputation"),
    (r"\b2-star\b", "2-star reputation"),
    (r"\b3-star\b", "3-star reputation"),
    (r"\bhidden\b|\btucked away\b", "Hidden spot"),
    (r"\bback streets of gion\b", "Back streets of Gion"),
    (r"\bpanoramic views? of kyoto\b|\bevening view\b", "Notable views"),
    (r"\boverlooking the famous garden\b", "Garden views"),
    (r"\bspanish-style stone kiln oven\b", "Stone kiln cooking"),
    (r"\btraditional cooking techniques\b", "Traditional technique"),
    (r"\bjapanese terroir\b", "Japanese terroir"),
    (r"\bseasonal\b|\bfour seasons\b", "Seasonal cooking"),
    (r"\bhokkaido-born\b|\bhokkaido ingredients\b", "Hokkaido ingredients"),
    (r"\bprivate room\b", "Private room option"),
    (r"\bchef-selected\b|\bselected dishes\b", "Chef-selected dishes"),
    (r"\bworld gourmet guide\b", "World gourmet guide"),
]


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://pocket-concierge.jp",
            "Referer": "https://pocket-concierge.jp/",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def sanitize_signal(signal: dict | None) -> dict:
    if not isinstance(signal, dict):
        return {}
    allowed_keys = {
        "score_raw",
        "honest_stars",
        "rating",
        "review_count",
        "price_level",
        "url",
        "match_confidence",
        "last_checked_at",
        "notes",
        "native_name",
        "native_address",
        "google_query",
    }
    return {key: signal[key] for key in allowed_keys if key in signal and signal[key] not in (None, "")}


def merged_quality_signals(record_id: str, signals_by_id: dict) -> dict:
    source = signals_by_id.get(record_id)
    if not isinstance(source, dict):
        return {}
    merged: dict[str, dict] = {}
    for provider in ("tabelog", "google"):
        signal = sanitize_signal(source.get(provider))
        if signal:
            merged[provider] = signal
    return merged


def compact_space(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def google_maps_search_url(*parts: str | None) -> str | None:
    query = ", ".join(part.strip() for part in parts if part and part.strip())
    if not query:
        return None
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


def normalize_google_map_url(raw_url: str | None, *fallback_parts: str | None) -> str | None:
    fallback = google_maps_search_url(*fallback_parts)
    if not raw_url:
        return fallback

    parsed = urllib.parse.urlparse(raw_url)
    params = urllib.parse.parse_qs(parsed.query)
    is_embed = params.get("output", [None])[0] == "embed" or "/embed" in parsed.path
    if not is_embed:
        return raw_url

    if fallback:
        return fallback

    q = params.get("q", [None])[0]
    if q:
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(q)}"
    return raw_url


def strip_tags(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<br\s*/?>", " ", value)
    value = re.sub(r"<[^>]+>", "", value)
    return compact_space(html.unescape(value))


def titlecase_geo(value: str | None) -> str | None:
    cleaned = compact_space(value)
    if not cleaned:
        return None
    cleaned = cleaned.replace("-", " ")
    return " ".join(part[:1].upper() + part[1:] for part in cleaned.split())


def append_unique(values: list[str], item: str | None) -> None:
    if item and item not in values:
        values.append(item)


def classify_price_band(
    value: int | None, bands: list[tuple[str, str, str, int, int | None]]
) -> tuple[str | None, str | None, str | None]:
    if value is None:
        return None, None, None

    for key, label, tier, lower, upper in bands:
        if upper is None and value >= lower:
            return key, label, tier
        if lower <= value < upper:
            return key, label, tier
    return None, None, None


def fetch_search_properties() -> list[dict]:
    payload = {
        "operationName": "SearchProperties",
        "variables": {},
        "query": SEARCH_PROPERTIES_QUERY,
    }
    response = post_json(GRAPHQL_URL, payload)
    return response.get("data", {}).get("areas", [])


def select_target_areas(areas: list[dict]) -> list[dict]:
    by_name = {area["name"]: area for area in areas}
    missing = [name for name in TARGET_AREA_ORDER if name not in by_name]
    if missing:
        raise RuntimeError(f"Missing expected Pocket Concierge areas: {', '.join(missing)}")
    return [by_name[name] for name in TARGET_AREA_ORDER]


def search_venues(area_id: str, page: int, limit: int = 100) -> dict:
    payload = {
        "operationName": "searchVenues",
        "variables": {
            "areaIds": [area_id],
            "pagination": {"limit": limit, "page": page},
        },
        "query": SEARCH_VENUES_QUERY,
    }
    response = post_json(GRAPHQL_URL, payload)
    return response.get("data", {}).get("venuesSearch", {})


def iter_area_venues(area: dict) -> list[dict]:
    records: list[dict] = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        payload = search_venues(area["id"], page=page, limit=100)
        metadata = payload.get("metadata") or {}
        collection = payload.get("collection") or []
        total_pages = int(metadata.get("totalPages") or 1)
        records.extend(collection)
        page += 1
        time.sleep(0.1)

    return records


def venue_detail_query(venue_id: str) -> dict:
    payload = {
        "operationName": "PartialVenueWithCourses",
        "variables": {"id": venue_id},
        "query": VENUE_DETAIL_QUERY,
    }
    response = post_json(GRAPHQL_URL, payload)
    return response.get("data", {}).get("venue", {}) or {}


def parse_google_map_coordinates(url: str | None) -> tuple[float | None, float | None]:
    if not url:
        return None, None
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    q_value = query.get("q", [None])[0]
    if not q_value:
        return None, None
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", q_value)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


def infer_city(
    localized_address: str | None,
    prefecture: str | None,
    area_name: str | None,
    town_name: str | None,
) -> str:
    parts = [compact_space(part) for part in (localized_address or "").split(",") if compact_space(part)]

    if prefecture == "Tokyo" or "Tokyo" in parts:
        return "Tokyo"

    for index, part in enumerate(parts):
        lower = part.lower()
        if lower.endswith("-shi"):
            city = titlecase_geo(part[:-4])
            if city:
                return city
        if lower.endswith("-ku"):
            if index + 1 < len(parts) and parts[index + 1].lower().endswith("-shi"):
                city = titlecase_geo(parts[index + 1][:-4])
                if city:
                    return city
            if prefecture == "Tokyo":
                return "Tokyo"

    address_text = " ".join(parts).lower()
    for choice in ("Kyoto", "Osaka", "Nara"):
        if choice.lower() in address_text:
            return choice

    if area_name in {"Tokyo", "Greater Tokyo Area"}:
        return "Tokyo"
    if prefecture:
        return titlecase_geo(prefecture) or "Japan"
    return titlecase_geo(town_name) or titlecase_geo(area_name) or "Japan"


def infer_district(town_name: str | None, area_name: str | None, city: str) -> str | None:
    town = compact_space(town_name)
    if town and town.lower() != city.lower():
        return town
    if area_name and area_name not in TARGET_AREA_ORDER and area_name.lower() != city.lower():
        return area_name
    return None


def extract_child_policy_excerpt(text: str | None) -> str | None:
    cleaned = strip_tags(text)
    if not cleaned:
        return None
    match = re.search(r"children[^.]*\.", cleaned, flags=re.I)
    if match:
        return compact_space(match.group(0))
    match = re.search(r"child[^.]*\.", cleaned, flags=re.I)
    return compact_space(match.group(0)) if match else None


def normalize_child_policy(note: str | None, services: list[str] | None) -> str:
    service_text = " ".join(services or []).lower()
    if "child-friendly" in service_text:
        return "kid_friendly"
    if "children-over12-accepted" in service_text:
        return "older_children_only"

    source = compact_space(note).lower()
    if not source:
        return "unknown"

    age_match = re.search(r"(\d+)\s*\+?", source)
    if age_match:
        age = int(age_match.group(1))
        if age <= 6:
            return "kid_friendly"
        if age <= 12:
            return "older_children_only"
        return "teens_only"

    if "elementary school" in source:
        return "older_children_only"
    if "junior high" in source or "middle school" in source:
        return "teens_only"
    if "children are welcome" in source or "welcome" in source:
        return "kid_friendly"
    return "policy_available"


def build_source_url(venue_id: str) -> str:
    return f"https://pocket-concierge.jp/en/restaurants/{venue_id}/"


def service_price_range(price_ranges: list[dict], service_type: str) -> tuple[int | None, int | None]:
    for price_range in price_ranges or []:
        if price_range.get("serviceType") != service_type:
            continue
        return price_range.get("min"), price_range.get("max")
    return None, None


def build_search_text(record: dict) -> str:
    fields = [
        record.get("name"),
        record.get("city"),
        record.get("district"),
        record.get("region"),
        record.get("prefecture"),
        record.get("source_localized_address"),
        record.get("nearest_stations_text"),
        " ".join(record.get("cuisines", [])),
        record.get("summary_official"),
        record.get("child_policy_raw"),
        record.get("price_lunch_band_label"),
        record.get("price_lunch_band_tier"),
        record.get("price_dinner_band_label"),
        record.get("price_dinner_band_tier"),
        " ".join(record.get("known_for_tags", [])),
        " ".join(record.get("signature_dish_tags", [])),
        " ".join(record.get("service_tags", [])),
    ]
    return " ".join(field for field in fields if field).lower()


def derive_restaurant_enrichment(record: dict, source_text: str) -> None:
    source = source_text.lower()
    known_for: list[str] = []
    signature_dishes: list[str] = []

    for pattern, label in KNOWN_FOR_PATTERNS:
        if re.search(pattern, source):
            append_unique(known_for, label)

    for pattern, label in SIGNATURE_PATTERNS:
        if re.search(pattern, source):
            append_unique(signature_dishes, label)

    if record.get("district") == "Gion":
        append_unique(known_for, "Gion")

    record["known_for_tags"] = known_for
    record["signature_dish_tags"] = signature_dishes
    record["restaurant_enrichment_source"] = (
        "Pocket Concierge blurb, venue description, and course metadata"
        if known_for or signature_dishes
        else None
    )


def build_record_from_search_result(venue: dict, area_name: str) -> dict:
    venue_id = str(venue["id"])
    address = venue.get("address") or {}
    prefecture = (address.get("prefecture") or {}).get("name")
    town_name = (address.get("town") or {}).get("name")
    lunch_min, lunch_max = service_price_range(venue.get("priceRanges") or [], "LUNCH")
    dinner_min, dinner_max = service_price_range(venue.get("priceRanges") or [], "DINNER")
    lunch_band_key, lunch_band_label, lunch_band_tier = classify_price_band(lunch_min, LUNCH_PRICE_BANDS)
    dinner_band_key, dinner_band_label, dinner_band_tier = classify_price_band(
        dinner_min, DINNER_PRICE_BANDS
    )

    initial_city = "Tokyo" if prefecture == "Tokyo" else (titlecase_geo(prefecture) or "Japan")
    district = infer_district(town_name, area_name, initial_city)

    return {
        "id": f"pocket-{venue_id}",
        "source": "Pocket Concierge",
        "source_url": build_source_url(venue_id),
        "source_search_area_ids": [venue.get("area", {}).get("id") or area_name],
        "source_search_areas": [area_name],
        "source_limited_scope_url_hash": venue.get("limitedScopeUrlHash"),
        "country": "Japan",
        "region": area_name,
        "area_title": area_name,
        "prefecture": prefecture,
        "city": initial_city,
        "district": district,
        "source_search_town": town_name,
        "name": venue.get("name"),
        "cuisines": [item.get("name") for item in venue.get("cuisines") or [] if item.get("name")],
        "reservation_type": "Real-time booking" if venue.get("realTimeBooking") else "Request booking",
        "price_lunch_min_jpy": lunch_min,
        "price_lunch_max_jpy": lunch_max,
        "price_dinner_min_jpy": dinner_min,
        "price_dinner_max_jpy": dinner_max,
        "price_lunch_band_key": lunch_band_key,
        "price_lunch_band_label": lunch_band_label,
        "price_lunch_band_tier": lunch_band_tier,
        "price_dinner_band_key": dinner_band_key,
        "price_dinner_band_label": dinner_band_label,
        "price_dinner_band_tier": dinner_band_tier,
        "summary_official": compact_space(venue.get("blurb")),
        "known_for_tags": [],
        "signature_dish_tags": [],
        "restaurant_enrichment_source": None,
        "child_policy_raw": None,
        "child_policy_norm": "unknown",
        "english_menu": False,
        "source_address_hidden": None,
        "source_localized_address": None,
        "source_google_map_url": None,
        "nearest_stations": [],
        "nearest_stations_text": None,
        "service_tags": [],
        "website_url": None,
        "phone_number": None,
        "recommendation_count": 0,
        "course_count": 0,
        "external_signals": {},
        "lat": None,
        "lng": None,
        "coordinate_source": None,
        "coordinate_confidence": "unknown",
        "search_text": "",
        "last_verified_at": datetime.now(UTC).isoformat(),
        "map_pin_note": "Approximate location based on public geocoding unless replaced by stronger source matching.",
        "city_color": CITY_COLORS.get(initial_city, "slate"),
    }


def merge_record(existing: dict, incoming: dict) -> None:
    for area_id in incoming["source_search_area_ids"]:
        if area_id not in existing["source_search_area_ids"]:
            existing["source_search_area_ids"].append(area_id)
    for area_name in incoming["source_search_areas"]:
        if area_name not in existing["source_search_areas"]:
            existing["source_search_areas"].append(area_name)


def geocode_query(query: str) -> dict | None:
    params = urllib.parse.urlencode({"format": "jsonv2", "limit": 1, "q": query})
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
    queries = []
    if record.get("source_localized_address"):
        queries.append(record["source_localized_address"] + ", Japan")
    if record.get("district"):
        queries.append(f"{record['name']}, {record['district']}, {record['city']}, Japan")
    queries.append(f"{record['name']}, {record['city']}, Japan")

    for index, query in enumerate(queries):
        if query in cache:
            result = cache[query]
        else:
            result = geocode_query(query)
            cache[query] = result
            save_json(CACHE_PATH, cache)
            time.sleep(1.1)

        if not result:
            continue

        record["lat"] = float(result["lat"])
        record["lng"] = float(result["lon"])
        record["coordinate_source"] = "nominatim_address_query" if index == 0 else "nominatim_name_query"
        record["coordinate_confidence"] = "approximate"
        return


def enrich_from_source(record: dict, cache: dict) -> None:
    venue_id = record["id"].replace("pocket-", "", 1)
    if venue_id in cache:
        venue = cache[venue_id]
    else:
        venue = venue_detail_query(venue_id)
        cache[venue_id] = venue
        save_json(DETAIL_CACHE_PATH, cache)
        time.sleep(0.15)

    if not venue:
        derive_restaurant_enrichment(
            record,
            " ".join(part for part in [record.get("summary_official"), " ".join(record.get("cuisines", []))] if part),
        )
        return

    localized_address = compact_space(venue.get("localizedAddress"))
    record["source_address_hidden"] = bool(venue.get("addressHidden"))
    record["source_google_map_url"] = normalize_google_map_url(
        venue.get("googleMapUrl"),
        record.get("name"),
        localized_address,
        record.get("prefecture"),
        "Japan",
    )
    record["nearest_stations"] = venue.get("nearestStations") or []
    record["nearest_stations_text"] = " ".join(record["nearest_stations"]) or None
    record["website_url"] = venue.get("websiteUrl")
    record["phone_number"] = venue.get("phoneNumber")
    record["recommendation_count"] = len(venue.get("recommendations") or [])
    record["course_count"] = len(venue.get("courses") or [])
    record["service_tags"] = list(venue.get("services") or [])
    record["english_menu"] = any(
        token in {"english-menu", "english-speaking-staff"} for token in record["service_tags"]
    )
    record["child_policy_raw"] = extract_child_policy_excerpt(venue.get("reservationTerms"))
    record["child_policy_norm"] = normalize_child_policy(record["child_policy_raw"], record["service_tags"])

    if localized_address and not record["source_address_hidden"]:
        record["source_localized_address"] = localized_address

    record["city"] = infer_city(
        localized_address,
        record.get("prefecture"),
        record.get("region"),
        record.get("source_search_town"),
    )
    record["district"] = infer_district(
        record.get("source_search_town"),
        record.get("region"),
        record["city"],
    )
    record["city_color"] = CITY_COLORS.get(record["city"], "slate")

    lat = venue.get("latitude")
    lng = venue.get("longitude")
    if lat is None or lng is None:
        lat, lng = parse_google_map_coordinates(venue.get("googleMapUrl"))
        if lat is not None and lng is not None:
            record["lat"] = lat
            record["lng"] = lng
            record["coordinate_source"] = "pocket_concierge_google_map_url"
            record["coordinate_confidence"] = "source"
            record["map_pin_note"] = "Source venue coordinates from Pocket Concierge public map data."
    else:
        record["lat"] = float(lat)
        record["lng"] = float(lng)
        record["coordinate_source"] = "pocket_concierge_graphql"
        record["coordinate_confidence"] = "source"
        record["map_pin_note"] = "Source venue coordinates from Pocket Concierge."

    course_text = " ".join(
        compact_space(
            " ".join(
                part
                for part in [
                    course.get("name"),
                    course.get("summary"),
                    course.get("supplementaryInformation"),
                ]
                if part
            )
        )
        for course in venue.get("courses") or []
    )
    source_text = " ".join(
        part
        for part in [
            record.get("summary_official"),
            compact_space(venue.get("longDescription")),
            course_text,
            " ".join(record.get("cuisines", [])),
        ]
        if part
    )
    derive_restaurant_enrichment(record, source_text)


def to_geojson(records: list[dict]) -> dict:
    features = []
    for record in records:
        if record.get("lat") is None or record.get("lng") is None:
            continue
        feature = {
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
        features.append(feature)
    return {"type": "FeatureCollection", "features": features}


def kml_description(record: dict) -> str:
    lines = [
        f"<strong>{html.escape(record['name'])}</strong>",
        html.escape(
            f"{record['city']} / {record.get('district') or record.get('region') or record.get('prefecture')}"
        ),
    ]
    if record.get("source_localized_address"):
        lines.append(html.escape("Address: " + record["source_localized_address"]))
    if record.get("nearest_stations"):
        lines.append(html.escape("Nearest: " + "; ".join(record["nearest_stations"])))
    if record.get("cuisines"):
        lines.append(html.escape("Cuisine: " + ", ".join(record["cuisines"])))
    if record.get("reservation_type"):
        lines.append(html.escape("Reservation: " + record["reservation_type"]))
    if record.get("price_dinner_min_jpy"):
        dinner_band = " ".join(
            part
            for part in [record.get("price_dinner_band_tier"), record.get("price_dinner_band_label")]
            if part
        )
        if dinner_band:
            lines.append(html.escape("Dinner range: " + dinner_band))
    if record.get("price_lunch_min_jpy"):
        lunch_band = " ".join(
            part
            for part in [record.get("price_lunch_band_tier"), record.get("price_lunch_band_label")]
            if part
        )
        if lunch_band:
            lines.append(html.escape("Lunch range: " + lunch_band))
    if record.get("child_policy_raw"):
        lines.append(html.escape("Child policy: " + record["child_policy_raw"]))
    if record.get("summary_official"):
        lines.append(html.escape("Summary: " + record["summary_official"]))
    if record.get("known_for_tags"):
        lines.append(html.escape("Known for: " + ", ".join(record["known_for_tags"])))
    if record.get("signature_dish_tags"):
        lines.append(html.escape("Signature cues: " + ", ".join(record["signature_dish_tags"])))
    if record.get("source_url"):
        lines.append(
            f'<a href="{html.escape(record["source_url"], quote=True)}" target="_blank" rel="noopener">Pocket Concierge</a>'
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


def write_kml_outputs(records: list[dict]) -> None:
    KML_DIR.mkdir(parents=True, exist_ok=True)
    groups = {
        "japan-all.kml": ("Japan Dining Map - All", records),
        "tokyo.kml": ("Japan Dining Map - Tokyo", [r for r in records if r["city"] == "Tokyo"]),
        "kyoto.kml": ("Japan Dining Map - Kyoto", [r for r in records if r["city"] == "Kyoto"]),
        "osaka.kml": ("Japan Dining Map - Osaka", [r for r in records if r["city"] == "Osaka"]),
    }
    for filename, (title, group_records) in groups.items():
        (KML_DIR / filename).write_text(build_kml(group_records, title))


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    geocode_cache = load_json(CACHE_PATH, {})
    detail_cache = load_json(DETAIL_CACHE_PATH, {})
    quality_signals = load_json(QUALITY_SIGNALS_PATH, {})

    areas = select_target_areas(fetch_search_properties())
    deduped: dict[str, dict] = {}

    for area in areas:
        search_results = iter_area_venues(area)
        print(f"Fetched {len(search_results)} search hits from area {area['name']}.")
        for venue in search_results:
            record = build_record_from_search_result(venue, area["name"])
            existing = deduped.get(record["id"])
            if existing:
                merge_record(existing, record)
                continue
            deduped[record["id"]] = record

    normalized = sorted(
        deduped.values(),
        key=lambda item: (item["city"], item.get("district") or "", item["name"]),
    )

    for index, record in enumerate(normalized, start=1):
        enrich_from_source(record, detail_cache)
        record["external_signals"] = merged_quality_signals(record["id"], quality_signals)
        if record.get("lat") is None or record.get("lng") is None:
            geocode_record(record, geocode_cache)
        record["search_text"] = build_search_text(record)
        if index % 50 == 0:
            print(f"Enriched {index}/{len(normalized)} venues...")

    save_json(JSON_PATH, normalized)
    save_json(GEOJSON_PATH, to_geojson(normalized))
    write_kml_outputs(normalized)

    mapped = sum(1 for record in normalized if record.get("lat") is not None)
    cities = sorted({record["city"] for record in normalized})
    print(f"Synced {len(normalized)} restaurants; mapped {mapped}; cities {len(cities)}.")


if __name__ == "__main__":
    main()
