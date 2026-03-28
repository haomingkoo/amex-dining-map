#!/usr/bin/env python3
"""Sync the Japan MVP dataset from public Pocket Concierge area pages."""

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

USER_AGENT = "JapanDiningMapMVP/0.1 (+https://local.dev)"
GRAPHQL_URL = "https://pocket-concierge.jp/graphql"
VENUE_QUERY = """
query InitialVenuePage($id: ID!) {
  venue(id: $id) {
    id
    name
    localizedAddress
    latitude
    longitude
    googleMapUrl
    addressHidden
    nearestStations
  }
}
""".strip()

AREA_SEEDS = [
    {
        "slug": "azabu",
        "city": "Tokyo",
        "label": "Azabu",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_azabu/index.html?extlink=va-jp-ICS-GMS_LP_en_Azabu",
    },
    {
        "slug": "ginza",
        "city": "Tokyo",
        "label": "Ginza",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_ginza/index.html?extlink=va-jp-ICS-GMS_LP_en_Ginza",
    },
    {
        "slug": "ebisu",
        "city": "Tokyo",
        "label": "Ebisu",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_ebisu/index.html?extlink=va-jp-ICS-GMS_LP_en_Ebisu",
    },
    {
        "slug": "omotesando",
        "city": "Tokyo",
        "label": "Omotesando",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_omotesando/index.html?extlink=va-jp-ICS-GMS_LP_en_Omotesando",
    },
    {
        "slug": "kagurazaka",
        "city": "Tokyo",
        "label": "Kagurazaka",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_kagurazaka/index.html?extlink=va-jp-ICS-GMS_LP_en_Kagurazaka",
    },
    {
        "slug": "osaka",
        "city": "Osaka",
        "label": "Osaka",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_osaka/index.html?extlink=va-jp-ICS-GMS_LP_en_Osaka",
    },
    {
        "slug": "kodaiji-kiyomizu",
        "city": "Kyoto",
        "label": "Kodaiji / Kiyomizu",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_kodaiji_kiyomizu/index.html?extlink=va-jp-ICS-GMS_LP_en_Kodaiji_Kiyomizu",
    },
    {
        "slug": "gion",
        "city": "Kyoto",
        "label": "Gion",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_gion/index.html?extlink=va-jp-ICS-GMS_LP_en_Gion",
    },
    {
        "slug": "higashiyama",
        "city": "Kyoto",
        "label": "Higashiyama",
        "url": "https://pocket-concierge.jp/lp/amex/gms/pocket_higashiyama/index.html?extlink=va-jp-ICS-GMS_LP_en_Higashiyama",
    },
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


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


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


def strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def match_first(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return None
    return strip_tags(match.group(1))


def parse_budget(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    numbers = [int(n.replace(",", "")) for n in re.findall(r"¥\s*([\d,]+)", text)]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def parse_location(location_text: str | None, fallback_city: str) -> tuple[str, str | None]:
    if not location_text:
        return fallback_city, None
    parts = [part.strip() for part in location_text.replace("\xa0", " ").split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return fallback_city, parts[0] if parts else None


def normalize_child_policy(notice: str | None, child_icon: str | None) -> str:
    source = " ".join(part for part in [notice, child_icon] if part).lower()
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


def restaurant_id_from_url(url: str | None, fallback_slug: str) -> str:
    if not url:
        return fallback_slug
    match = re.search(r"/restaurants/(\d+)", url)
    return match.group(1) if match else fallback_slug


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def build_search_text(record: dict) -> str:
    fields = [
        record.get("name"),
        record.get("city"),
        record.get("district"),
        record.get("area_title"),
        record.get("source_localized_address"),
        record.get("nearest_stations_text"),
        " ".join(record.get("cuisines", [])),
        record.get("summary_official"),
        record.get("child_policy_raw"),
        record.get("price_lunch_band_label"),
        record.get("price_lunch_band_tier"),
        record.get("price_dinner_band_label"),
        record.get("price_dinner_band_tier"),
    ]
    return " ".join(field for field in fields if field).lower()


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


def source_venue_id(record: dict) -> str | None:
    source_url = record.get("source_url")
    if not source_url:
        return None
    match = re.search(r"/restaurants/(\d+)", source_url)
    return match.group(1) if match else None


def venue_detail_query(venue_id: str) -> dict:
    payload = {
        "operationName": "InitialVenuePage",
        "variables": {"id": venue_id},
        "query": VENUE_QUERY,
    }
    response = post_json(GRAPHQL_URL, payload)
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if not isinstance(data, dict):
        return {}
    venue = data.get("venue")
    return venue if isinstance(venue, dict) else {}


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


def enrich_from_source(record: dict, cache: dict) -> None:
    venue_id = source_venue_id(record)
    if not venue_id:
        return

    if venue_id in cache:
        venue = cache[venue_id]
    else:
        venue = venue_detail_query(venue_id)
        cache[venue_id] = venue
        save_json(DETAIL_CACHE_PATH, cache)
        time.sleep(0.2)

    if not venue:
        return

    record["source_address_hidden"] = bool(venue.get("addressHidden"))
    record["source_google_map_url"] = venue.get("googleMapUrl")
    nearest = venue.get("nearestStations") or []
    record["nearest_stations"] = nearest
    record["nearest_stations_text"] = " ".join(nearest)

    if not record["source_address_hidden"]:
        record["source_localized_address"] = venue.get("localizedAddress")
    else:
        record["source_localized_address"] = None

    lat = venue.get("latitude")
    lng = venue.get("longitude")
    if lat is None or lng is None:
        lat, lng = parse_google_map_coordinates(venue.get("googleMapUrl"))
        if lat is not None and lng is not None:
            record["lat"] = lat
            record["lng"] = lng
            record["coordinate_source"] = "pocket_concierge_google_map_url"
            record["coordinate_confidence"] = "source"
            record["map_pin_note"] = (
                "Source venue coordinates from Pocket Concierge public map data."
            )
            return

    if lat is not None and lng is not None:
        record["lat"] = float(lat)
        record["lng"] = float(lng)
        record["coordinate_source"] = "pocket_concierge_graphql"
        record["coordinate_confidence"] = "source"
        record["map_pin_note"] = "Source venue coordinates from Pocket Concierge."
        return


def extract_restaurant_blocks(section_html: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r'<div class="sec-restaurants__item"', section_html)]
    if not starts:
        return []

    blocks: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(section_html)
        blocks.append(section_html[start:end])
    return blocks


def parse_area_page(area: dict) -> list[dict]:
    page_html = fetch_text(area["url"])
    section_match = re.search(
        r'<div id="restaurants".*?(?=<div id="other-destinations"|</main>)',
        page_html,
        flags=re.S,
    )
    if not section_match:
        raise RuntimeError(f"Could not find restaurants section for {area['slug']}")

    section_html = section_match.group(0)
    restaurants: list[dict] = []
    for block in extract_restaurant_blocks(section_html):
        name = match_first(block, r'<div class="sec-restaurants__name">(.*?)</div>')
        if not name:
            continue

        location_text = match_first(block, r'<div class="sec-restaurants__location">(.*?)</div>')
        city, district = parse_location(location_text, area["city"])
        genre = match_first(block, r'<div class="sec-restaurants__genre">(.*?)</div>')
        reservation_type = match_first(block, r'<div class="sec-restaurants__reservation-type">(.*?)</div>')
        summary = match_first(block, r'<div class="sec-restaurants__summary">(.*?)</div>')
        notice = match_first(block, r'<div class="sec-restaurants__notice">(.*?)</div>')
        lunch_text = match_first(block, r'<span class="sec-restaurants__budget-lunch">(.*?)</span>')
        dinner_text = match_first(block, r'<span class="sec-restaurants__budget-dinner">(.*?)</span>')
        child_icon = match_first(block, r'sec-restaurants__icon--child">(.*?)</span>')
        english_menu = bool(re.search(r'sec-restaurants__icon--menu">English menu', block))
        detail_url = match_first(block, r'<a href="(https://pocket-concierge\.jp/en/restaurants/[^"]+)"')
        lunch_min, lunch_max = parse_budget(lunch_text)
        dinner_min, dinner_max = parse_budget(dinner_text)

        fallback_slug = slugify(name)
        record = {
            "id": f"pocket-{area['slug']}-{restaurant_id_from_url(detail_url, fallback_slug)}",
            "source": "Pocket Concierge",
            "source_url": detail_url,
            "source_area_page": area["url"],
            "source_area_slug": area["slug"],
            "country": "Japan",
            "city": city,
            "district": district,
            "area_title": area["label"],
            "name": name,
            "cuisines": [genre] if genre else [],
            "reservation_type": reservation_type,
            "price_lunch_min_jpy": lunch_min,
            "price_lunch_max_jpy": lunch_max,
            "price_dinner_min_jpy": dinner_min,
            "price_dinner_max_jpy": dinner_max,
            "price_lunch_band_key": None,
            "price_lunch_band_label": None,
            "price_lunch_band_tier": None,
            "price_dinner_band_key": None,
            "price_dinner_band_label": None,
            "price_dinner_band_tier": None,
            "summary_official": summary,
            "child_policy_raw": notice or child_icon,
            "child_icon_label": child_icon,
            "child_policy_norm": normalize_child_policy(notice, child_icon),
            "english_menu": english_menu,
            "michelin_status": None,
            "michelin_source": None,
            "source_address_hidden": None,
            "source_localized_address": None,
            "source_google_map_url": None,
            "nearest_stations": [],
            "nearest_stations_text": None,
            "lat": None,
            "lng": None,
            "coordinate_source": None,
            "coordinate_confidence": "unknown",
            "search_text": "",
            "last_verified_at": datetime.now(UTC).isoformat(),
            "map_pin_note": "Approximate location based on public geocoding unless replaced by stronger source matching.",
            "city_color": CITY_COLORS.get(city, "slate"),
        }
        lunch_band_key, lunch_band_label, lunch_band_tier = classify_price_band(lunch_min, LUNCH_PRICE_BANDS)
        dinner_band_key, dinner_band_label, dinner_band_tier = classify_price_band(
            dinner_min, DINNER_PRICE_BANDS
        )
        record["price_lunch_band_key"] = lunch_band_key
        record["price_lunch_band_label"] = lunch_band_label
        record["price_lunch_band_tier"] = lunch_band_tier
        record["price_dinner_band_key"] = dinner_band_key
        record["price_dinner_band_label"] = dinner_band_label
        record["price_dinner_band_tier"] = dinner_band_tier
        record["search_text"] = build_search_text(record)
        restaurants.append(record)

    return restaurants


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
    if record.get("district"):
        queries.append(f"{record['name']}, {record['district']}, {record['city']}, Japan")
    queries.append(f"{record['name']}, {record['city']}, Japan")
    if record.get("district"):
        queries.append(f"{record['district']}, {record['city']}, Japan")

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
        record["coordinate_source"] = "nominatim_name_query" if index < 2 else "nominatim_area_fallback"
        record["coordinate_confidence"] = "approximate"
        return


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
        html.escape(f"{record['city']} / {record.get('district') or record['area_title']}"),
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
        lines.append(
            html.escape(
                "Dinner: JPY "
                f"{record['price_dinner_min_jpy']:,}"
                + (
                    f" - {record['price_dinner_max_jpy']:,}"
                    if record.get("price_dinner_max_jpy")
                    else ""
                )
            )
        )
    if record.get("price_lunch_min_jpy"):
        lunch_band = " ".join(
            part
            for part in [record.get("price_lunch_band_tier"), record.get("price_lunch_band_label")]
            if part
        )
        if lunch_band:
            lines.append(html.escape("Lunch range: " + lunch_band))
        lines.append(
            html.escape(
                "Lunch: JPY "
                f"{record['price_lunch_min_jpy']:,}"
                + (
                    f" - {record['price_lunch_max_jpy']:,}"
                    if record.get("price_lunch_max_jpy")
                    else ""
                )
            )
        )
    if record.get("child_policy_raw"):
        lines.append(html.escape("Child policy: " + record["child_policy_raw"]))
    if record.get("summary_official"):
        lines.append(html.escape("Summary: " + record["summary_official"]))
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

    records: list[dict] = []
    for area in AREA_SEEDS:
        records.extend(parse_area_page(area))

    deduped = {}
    for record in records:
        deduped[record["id"]] = record
    normalized = sorted(
        deduped.values(),
        key=lambda item: (item["city"], item.get("district") or "", item["name"]),
    )

    for record in normalized:
        enrich_from_source(record, detail_cache)
        if record.get("lat") is None or record.get("lng") is None:
            geocode_record(record, geocode_cache)
        record["search_text"] = build_search_text(record)

    save_json(JSON_PATH, normalized)
    save_json(GEOJSON_PATH, to_geojson(normalized))
    write_kml_outputs(normalized)

    mapped = sum(1 for record in normalized if record.get("lat") is not None)
    print(f"Synced {len(normalized)} restaurants; mapped {mapped}.")


if __name__ == "__main__":
    main()
