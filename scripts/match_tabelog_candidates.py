#!/usr/bin/env python3
"""Generate Tabelog candidate matches for Japan dining venues.

This does not publish ratings directly. It fetches Tabelog search pages,
extracts plausible candidates, scores them, and writes the ranked results to
data/tabelog-match-candidates.json for review or later auto-accept logic.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESTAURANTS_PATH = DATA_DIR / "japan-restaurants.json"
OUTPUT_PATH = DATA_DIR / "tabelog-match-candidates.json"
USER_AGENT = "ChargingTheChargeCard/0.1 (+https://local.dev)"
POCKET_JP_RESTAURANT_URL = "https://pocket-concierge.jp/restaurants/{id}/"

PREFECTURE_SLUGS = {
    "Aichi": "aichi",
    "Akita": "akita",
    "Aomori": "aomori",
    "Chiba": "chiba",
    "Ehime": "ehime",
    "Fukui": "fukui",
    "Fukuoka": "fukuoka",
    "Fukushima": "fukushima",
    "Gifu": "gifu",
    "Gunma": "gunma",
    "Hiroshima": "hiroshima",
    "Hokkaido": "hokkaido",
    "Hyogo": "hyogo",
    "Ibaraki": "ibaraki",
    "Ishikawa": "ishikawa",
    "Iwate": "iwate",
    "Kagawa": "kagawa",
    "Kanagawa": "kanagawa",
    "Kumamoto": "kumamoto",
    "Kyoto": "kyoto",
    "Mie": "mie",
    "Miyazaki": "miyazaki",
    "Nagano": "nagano",
    "Nagazaki": "nagasaki",
    "Nagasaki": "nagasaki",
    "Nara": "nara",
    "Niigata": "niigata",
    "Oita": "oita",
    "Okayama": "okayama",
    "Okinawa": "okinawa",
    "Osaka": "osaka",
    "Saga": "saga",
    "Shiga": "shiga",
    "Shimane": "shimane",
    "Shizuoka": "shizuoka",
    "Tokushima": "tokushima",
    "Tokyo": "tokyo",
    "Tottori": "tottori",
    "Toyama": "toyama",
    "Wakayama": "wakayama",
    "Yamagata": "yamagata",
    "Yamaguchi": "yamaguchi",
    "Yamanashi": "yamanashi",
}

BLOCK_RE = re.compile(
    r'<div class="list-rst\b[^"]*"[^>]*data-detail-url="(?P<url>https://tabelog\.com/[^"]+/)"[^>]*>'
    r'(?P<body>.*?)'
    r'(?=<div class="list-rst\b[^"]*"|\Z)',
    re.DOTALL,
)
NAME_RE = re.compile(
    r'<a class="list-rst__rst-name-target[^"]*"[^>]*href="[^"]+">(?P<name>.*?)</a>',
    re.DOTALL,
)
AREA_GENRE_RE = re.compile(
    r'<div class="list-rst__area-genre[^"]*">(?P<text>.*?)</div>',
    re.DOTALL,
)
RATING_RE = re.compile(
    r'<span class="c-rating__val[^"]*list-rst__rating-val">(?P<rating>[\d.]+)</span>'
)
REVIEW_RE = re.compile(
    r'<em class="list-rst__rvw-count-num[^"]*">(?P<count>[\d,]+)</em>'
)
TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.DOTALL | re.IGNORECASE)
KEYWORDS_RE = re.compile(
    r'<meta name="keywords" content="(?P<keywords>[^"]*)"',
    re.DOTALL | re.IGNORECASE,
)
FURIGANA_SUFFIX_RE = re.compile(r"（[^）]*）")
JP_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
LD_JSON_RE = re.compile(r'<script type="application/ld\+json">\s*(?P<json>\{.*?\})\s*</script>', re.DOTALL)
TRANSPORT_RE = re.compile(
    r"<th>\s*Transportation\s*</th>\s*<td>\s*<p>\s*(?P<transport>.*?)\s*</p>",
    re.DOTALL | re.IGNORECASE,
)
ADDRESS_RE = re.compile(
    r"<th>\s*Address\s*</th>\s*<td>\s*(?P<address>.*?)\s*</td>",
    re.DOTALL | re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"<th>\s*Phone number.*?</th>\s*<td>\s*(?P<phone>.*?)\s*</td>",
    re.DOTALL | re.IGNORECASE,
)
DIGIT_RE = re.compile(r"\d+")
GENERIC_JP_KEYWORDS = {
    "すし",
    "寿司",
    "鮨",
    "料理",
    "和食",
    "洋食",
    "フレンチ",
    "イタリアン",
    "焼肉",
    "天ぷら",
    "うなぎ",
}
GENERIC_SUSHI_HINTS = ("sushi", "すし", "寿司", "鮨")
LOCATION_KEYWORD_HINTS = ("都", "道", "府", "県", "市", "区", "町", "村", "駅", "通", "川端", "洲", "門", "坂", "橋", "谷", "原")


def load_records() -> list[dict]:
    return json.loads(RESTAURANTS_PATH.read_text())


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def clean_table_detail_text(value: str) -> str:
    cleaned = strip_tags(value)
    cleaned = re.sub(r"\bShow larger map\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bFind nearby restaurants\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_station_hint(value: str) -> str:
    cleaned = clean_table_detail_text(value)
    cleaned = re.sub(r"(?i)^(?:a|an|about a|about|it is a|it is an)\s+\d+-minute\s+walk from\s+", "", cleaned)
    cleaned = re.sub(r"(?i)^\d+-minute\s+walk from\s+", "", cleaned)
    cleaned = re.sub(r"(?i)\s+on the\s+.+$", "", cleaned)
    cleaned = re.sub(r"(?i)\s+on\s+.+$", "", cleaned)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_ascii(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_unicode(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = FURIGANA_SUFFIX_RE.sub("", value)
    value = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", value)
    return value.strip()


def english_candidate_url(url: str) -> str:
    if "/en/" in url:
        return url
    return url.replace("https://tabelog.com/", "https://tabelog.com/en/", 1)


def normalize_digits(value: str) -> str:
    return "".join(DIGIT_RE.findall(value or ""))


def parse_price_bounds(value: str) -> tuple[int | None, int | None]:
    digits = [int(token.replace(",", "")) for token in re.findall(r"\d[\d,]*", value or "")]
    if not digits:
        return (None, None)
    if len(digits) == 1:
        return (digits[0], digits[0])
    return (digits[0], digits[1])


def tokenize(value: str) -> list[str]:
    return [token for token in normalize_ascii(value).split(" ") if token]


def important_tokens(value: str, ignore: set[str] | None = None) -> set[str]:
    ignore = ignore or set()
    return {token for token in tokenize(value) if token not in ignore and len(token) > 1}


def looks_like_generic_sushi_counter(name: str) -> bool:
    normalized = normalize_unicode(name)
    return bool(normalized) and any(hint in normalized for hint in GENERIC_SUSHI_HINTS)


def record_address_anchor(record: dict) -> str:
    return (record.get("source_localized_address") or record.get("address") or "").strip()


def fetch_native_metadata(record_id: str) -> dict:
    url = POCKET_JP_RESTAURANT_URL.format(id=record_id.split("-")[-1])
    html_text = fetch(url)
    title_match = TITLE_RE.search(html_text)
    keywords_match = KEYWORDS_RE.search(html_text)

    title = strip_tags(title_match.group("title")) if title_match else ""
    keywords = []
    if keywords_match:
        keywords = [part.strip() for part in html.unescape(keywords_match.group("keywords")).split(",") if part.strip()]

    cleaned_title = title.replace(" | Pocket Concierge", "").replace(" | ポケットコンシェルジュ", "").strip()
    title_without_reading = FURIGANA_SUFFIX_RE.sub("", cleaned_title).strip()

    useful_keywords = []
    seen = set()
    for keyword in keywords:
        normalized = normalize_unicode(keyword)
        if not normalized or normalized in seen:
            continue
        if keyword in GENERIC_JP_KEYWORDS:
            continue
        if re.fullmatch(r".+[都道府県市区町村駅]", keyword):
            continue
        seen.add(normalized)
        useful_keywords.append(keyword)

    return {
        "title": cleaned_title,
        "title_without_reading": title_without_reading,
        "keywords": useful_keywords,
    }


def fetch_detail_metadata(url: str) -> dict:
    html_text = fetch(english_candidate_url(url))
    transport_match = TRANSPORT_RE.search(html_text)
    address_match = ADDRESS_RE.search(html_text)
    phone_match = PHONE_RE.search(html_text)
    transportation = strip_tags(transport_match.group("transport")) if transport_match else ""
    full_address_text = clean_table_detail_text(address_match.group("address")) if address_match else ""
    visible_phone = clean_table_detail_text(phone_match.group("phone")) if phone_match else ""
    for match in LD_JSON_RE.finditer(html_text):
        try:
            payload = json.loads(match.group("json"))
        except json.JSONDecodeError:
            continue
        if payload.get("@type") != "Restaurant":
            continue
        address = payload.get("address") or {}
        return {
            "name": payload.get("name") or "",
            "street_address": address.get("streetAddress") or full_address_text,
            "full_address_text": full_address_text,
            "address_locality": address.get("addressLocality") or "",
            "address_region": address.get("addressRegion") or "",
            "postal_code": address.get("postalCode") or "",
            "serves_cuisine": payload.get("servesCuisine") or "",
            "price_range": payload.get("priceRange") or "",
            "telephone": payload.get("telephone") or visible_phone,
            "transportation": transportation,
            "rating_count": payload.get("aggregateRating", {}).get("ratingCount"),
            "rating_value": payload.get("aggregateRating", {}).get("ratingValue"),
            "url": payload.get("@id") or english_candidate_url(url),
        }
    return {}


def overlap_score(left: str, right: str) -> float:
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    return len(shared) / max(len(left_tokens), len(right_tokens))


def candidate_sort_key(item: dict) -> tuple[float, float, int]:
    return (
        item.get("score", 0),
        item.get("score_raw") or 0,
        item.get("review_count") or 0,
    )


def looks_like_location_keyword(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if any(hint in value for hint in LOCATION_KEYWORD_HINTS):
        return True
    normalized = normalize_unicode(value)
    return value in PREFECTURE_SLUGS or normalized in {normalize_unicode(v) for v in PREFECTURE_SLUGS}


def fallback_search_queries(record: dict) -> list[dict]:
    queries: list[dict] = []
    seen: set[str] = set()

    def add_query(label: str, query_text: str) -> None:
        query_text = (query_text or "").strip()
        if not query_text:
            return
        norm = normalize_unicode(query_text) if JP_CHAR_RE.search(query_text) else normalize_ascii(query_text)
        if not norm or norm in seen:
            return
        seen.add(norm)
        queries.append(
            {
                "label": label,
                "query": query_text,
                "url": "https://www.bing.com/search?setlang=ja&cc=jp&mkt=ja-JP&q="
                + urllib.parse.quote(query_text),
            }
        )

    native_title = (record.get("_native_title") or "").strip()
    english_name = (record.get("name") or "").strip()
    jp_terms = [keyword for keyword in (record.get("_native_keywords") or []) if JP_CHAR_RE.search(keyword)]

    base_terms = []
    if native_title:
        base_terms.append(native_title)
    if english_name:
        base_terms.append(f'"{english_name}"')

    location_terms = []
    for keyword in jp_terms:
        if normalize_unicode(keyword) == normalize_unicode(native_title):
            continue
        if looks_like_location_keyword(keyword):
            location_terms.append(keyword)
        if len(location_terms) >= 3:
            break

    for base in base_terms:
        add_query("bing_selection_name", f"site:selection.tabelog.com {base}")
        if location_terms:
            add_query("bing_selection_name_location", f"site:selection.tabelog.com {base} {' '.join(location_terms[:2])}")
        add_query("bing_site_name", f"site:tabelog.com {base}")
        if location_terms:
            add_query("bing_site_name_location", f"site:tabelog.com {base} {' '.join(location_terms[:2])}")

    return queries


def query_variants(record: dict) -> list[tuple[str, str]]:
    name = (record.get("name") or "").strip()
    city = (record.get("city") or "").strip()
    prefecture = (record.get("prefecture") or "").strip()
    district = (record.get("district") or "").strip()
    station_hint = extract_station_hint(record.get("nearest_stations_text") or "")
    address_digits = normalize_digits(record_address_anchor(record))
    slug = PREFECTURE_SLUGS.get(prefecture)
    variants: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_variant(label: str, query_text: str, url: str) -> None:
        query_norm = normalize_unicode(query_text) if JP_CHAR_RE.search(query_text) else normalize_ascii(query_text)
        key = f"{label}:{query_norm}"
        if not query_norm or key in seen:
            return
        seen.add(key)
        variants.append((label, url))

    if slug and name:
        add_variant(f"prefecture_name:{name}", name, f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(name)}")
    if slug and name and city:
        add_variant(
            f"prefecture_name_city:{name} {city}",
            f"{name} {city}",
            f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(f'{name} {city}')}",
        )
    if name and city and prefecture:
        add_variant(
            f"global_name_city_prefecture:{name} {city} {prefecture}",
            f"{name} {city} {prefecture}",
            f"https://tabelog.com/en/rstLst/?sk={urllib.parse.quote(f'{name} {city} {prefecture}')}",
        )
    for location_term in [district, station_hint, address_digits]:
        if slug and name and location_term:
            add_variant(
                f"prefecture_name_location:{name} {location_term}",
                f"{name} {location_term}",
                f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(f'{name} {location_term}')}",
            )
        if name and city and prefecture and location_term:
            add_variant(
                f"global_name_location:{name} {location_term}",
                f"{name} {location_term} {prefecture}",
                f"https://tabelog.com/en/rstLst/?sk={urllib.parse.quote(f'{name} {location_term} {prefecture}')}",
            )
    return variants


def native_query_variants(record: dict) -> list[tuple[str, str]]:
    prefecture = (record.get("prefecture") or "").strip()
    slug = PREFECTURE_SLUGS.get(prefecture)
    native_title = (record.get("_native_title") or "").strip()
    if not slug or not native_title:
        return []

    variants: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_variant(label: str, query_text: str) -> None:
        query_norm = normalize_unicode(query_text) if JP_CHAR_RE.search(query_text) else normalize_ascii(query_text)
        key = f"{label}:{query_norm}"
        if not query_norm or key in seen:
            return
        seen.add(key)
        variants.append((label, f"https://tabelog.com/{slug}/rstLst/?sk={urllib.parse.quote(query_text)}"))

    priority_terms: list[str] = [native_title]
    location_terms: list[str] = []
    for keyword in record.get("_native_keywords", []):
        keyword = (keyword or "").strip()
        normalized = normalize_unicode(keyword) if JP_CHAR_RE.search(keyword) else normalize_ascii(keyword)
        if not keyword or not normalized:
            continue
        if normalized == normalize_unicode(native_title):
            continue
        if keyword in {"ミシュラン", "Michelin"}:
            continue
        if JP_CHAR_RE.search(keyword):
            if keyword not in location_terms:
                location_terms.append(keyword)
        elif keyword not in priority_terms:
            priority_terms.append(keyword)
        if len(priority_terms) >= 4 and len(location_terms) >= 4:
            break

    for term in priority_terms:
        add_variant(f"jp_prefecture_native:{term}", term)
        for location_term in location_terms[:4]:
            if normalize_unicode(location_term) == normalize_unicode(term):
                continue
            add_variant(f"jp_prefecture_native_area:{term} {location_term}", f"{term} {location_term}")

    return variants


def parse_candidates(html_text: str) -> list[dict]:
    candidates: list[dict] = []
    for match in BLOCK_RE.finditer(html_text):
        body = match.group("body")
        name_match = NAME_RE.search(body)
        area_match = AREA_GENRE_RE.search(body)
        rating_match = RATING_RE.search(body)
        review_match = REVIEW_RE.search(body)
        candidates.append(
            {
                "url": html.unescape(match.group("url")),
                "name": strip_tags(name_match.group("name")) if name_match else "",
                "area_genre": strip_tags(area_match.group("text")) if area_match else "",
                "score_raw": float(rating_match.group("rating")) if rating_match else None,
                "review_count": int(review_match.group("count").replace(",", "")) if review_match else None,
            }
        )
    return candidates


def candidate_score(record: dict, candidate: dict, query_label: str) -> float:
    score = 0.0
    ignore_tokens = {
        token
        for token in tokenize(
            " ".join(
                [
                    record.get("prefecture") or "",
                    record.get("city") or "",
                    record.get("district") or "",
                    "restaurant dining house table no the de la ten honten",
                ]
            )
        )
    }

    record_name_tokens = important_tokens(record.get("name") or "", ignore_tokens)
    candidate_name_tokens = important_tokens(candidate.get("name") or "", ignore_tokens)
    name_score = 0.0
    if record_name_tokens and candidate_name_tokens:
        name_score = len(record_name_tokens & candidate_name_tokens) / len(record_name_tokens)
    else:
        name_score = overlap_score(record.get("name") or "", candidate.get("name") or "")
    score += name_score * 10

    native_aliases = record.get("_native_aliases") or []
    candidate_native = normalize_unicode(candidate.get("name") or "")
    native_name_score = 0.0
    if candidate_native and native_aliases:
        normalized_aliases = [normalize_unicode(alias) for alias in native_aliases]
        if candidate_native in normalized_aliases:
            native_name_score = 1.0
        else:
            for alias in normalized_aliases:
                if not alias:
                    continue
                if candidate_native in alias or alias in candidate_native:
                    native_name_score = max(native_name_score, 0.7)
    score += native_name_score * 12

    area_genre = candidate.get("area_genre") or ""
    city = (record.get("city") or "").lower()
    prefecture = (record.get("prefecture") or "").lower()
    district = (record.get("district") or "").lower()
    cuisines = " ".join(record.get("cuisine_types") or [])
    cuisine_score = overlap_score(cuisines, area_genre)

    if city and city in area_genre.lower():
        score += 1.5
    if prefecture and prefecture in area_genre.lower():
        score += 0.75
    if district and district in area_genre.lower():
        score += 0.5
    score += cuisine_score * 3

    if query_label.startswith("jp_"):
        score += 1.0
    if query_label.startswith("prefecture_"):
        score += 0.5

    review_count = candidate.get("review_count") or 0
    if review_count >= 100:
        score += 0.5

    if name_score == 0 and native_name_score == 0 and cuisine_score == 0:
        score -= 2

    return round(score, 4)


def candidate_detail_score(record: dict, detail: dict) -> float:
    if not detail:
        return 0.0
    score = 0.0
    detail_name = detail.get("name") or ""
    locality = normalize_ascii(detail.get("address_locality") or "")
    region = normalize_ascii(detail.get("address_region") or "")
    street_address = detail.get("street_address") or ""
    detail_address = " ".join(
        part
        for part in [
            detail.get("postal_code") or "",
            street_address,
            detail.get("address_locality") or "",
            detail.get("address_region") or "",
        ]
        if part
    )
    city = normalize_ascii(record.get("city") or "")
    prefecture = normalize_ascii(record.get("prefecture") or "")
    district = normalize_ascii(record.get("district") or "")
    record_address = record_address_anchor(record)
    detail_address_search = normalize_ascii(" ".join([detail_address, detail.get("full_address_text") or ""]))
    if prefecture and (prefecture in region or prefecture in detail_address_search):
        score += 2.0
    elif prefecture and (region or detail_address_search):
        score -= 3.0
    if city and (city in locality or city in detail_address_search):
        score += 2.5
    elif city and (locality or detail_address_search):
        score -= 3.0
    if district and (district in locality or district in detail_address_search):
        score += 2.5
    elif district and (locality or detail_address_search):
        score -= 2.0

    native_aliases = [normalize_unicode(alias) for alias in (record.get("_native_aliases") or []) if alias]
    detail_name_native = normalize_unicode(detail_name)
    if detail_name_native and native_aliases:
        if detail_name_native in native_aliases:
            score += 5.0
        elif any(detail_name_native in alias or alias in detail_name_native for alias in native_aliases):
            score += 3.0
        else:
            score -= 2.5
    if looks_like_generic_sushi_counter(detail_name) and (
        city and city in locality and not (detail_name_native and native_aliases and any(
            detail_name_native in alias or alias in detail_name_native for alias in native_aliases
        ))
    ):
        score -= 4.0

    record_phone = normalize_digits(record.get("phone_number") or "")
    detail_phone = normalize_digits(detail.get("telephone") or "")
    if record_phone and detail_phone and record_phone == detail_phone:
        score += 4.0
    elif record_phone and detail_phone:
        score -= 4.0

    record_address_digits = normalize_digits(record_address)
    detail_address_digits = normalize_digits(detail_address)
    if record_address_digits and detail_address_digits:
        if record_address_digits == detail_address_digits:
            score += 4.0
        elif (
            len(record_address_digits) >= 3
            and (record_address_digits in detail_address_digits or detail_address_digits in record_address_digits)
        ):
            score += 3.0
        else:
            score -= 3.5

    station_score = overlap_score(record.get("nearest_stations_text") or "", detail.get("transportation") or "")
    score += station_score * 3
    record_price = (record.get("price_dinner_min_jpy"), record.get("price_dinner_max_jpy"))
    detail_price = parse_price_bounds(detail.get("price_range") or "")
    if all(value is not None for value in [*record_price, *detail_price]):
        record_min, record_max = record_price
        detail_min, detail_max = detail_price
        if record_min <= detail_max and detail_min <= record_max:
            score += 1.5
    score += overlap_score(" ".join(record.get("cuisine_types") or []), detail.get("serves_cuisine") or "") * 3
    score += overlap_score(record.get("name") or "", detail_name) * 4
    return round(score, 4)


def rank_candidates(record: dict, limit_per_query: int, pause_seconds: float) -> dict:
    native_meta = fetch_native_metadata(record.get("id") or "")
    record = dict(record)
    native_aliases = []
    for candidate_alias in [native_meta.get("title_without_reading"), native_meta.get("title")]:
        candidate_alias = (candidate_alias or "").strip()
        if candidate_alias and candidate_alias not in native_aliases:
            native_aliases.append(candidate_alias)
    record["_native_aliases"] = native_aliases
    record["_native_title"] = native_meta.get("title_without_reading") or native_meta.get("title")
    record["_native_keywords"] = native_meta.get("keywords") or []

    ranked: list[dict] = []
    aggregate: dict[str, dict] = {}

    all_queries = [*native_query_variants(record), *query_variants(record)]
    per_query_limit = max(limit_per_query, 10)
    detail_fetch_limit = max(limit_per_query * 6, 25)

    for query_label, url in all_queries:
        try:
            html_text = fetch(url)
        except Exception as exc:
            ranked.append({"query": query_label, "error": str(exc), "candidates": []})
            time.sleep(pause_seconds)
            continue

        query_candidates = []
        for candidate in parse_candidates(html_text):
            candidate["score"] = candidate_score(record, candidate, query_label)
            candidate["query"] = query_label
            query_candidates.append(candidate)
            existing = aggregate.get(candidate["url"])
            if existing is None:
                aggregate[candidate["url"]] = {
                    **candidate,
                    "source_queries": [query_label],
                    "query_hits": 1,
                }
            else:
                existing["query_hits"] = existing.get("query_hits", 1) + 1
                source_queries = existing.setdefault("source_queries", [])
                if query_label not in source_queries:
                    source_queries.append(query_label)
                if candidate_sort_key(candidate) > candidate_sort_key(existing):
                    for key in ["name", "area_genre", "score", "score_raw", "review_count", "query"]:
                        existing[key] = candidate.get(key)

        query_candidates.sort(key=candidate_sort_key, reverse=True)
        ranked.append(
            {
                "query": query_label,
                "url": url,
                "candidates": query_candidates[:per_query_limit],
            }
        )
        time.sleep(pause_seconds)

    best_pre_detail = sorted(aggregate.values(), key=candidate_sort_key, reverse=True)
    enriched_by_original_url: dict[str, dict] = {}
    final_aggregate: dict[str, dict] = {}
    for candidate in best_pre_detail[:detail_fetch_limit]:
        original_url = candidate["url"]
        try:
            detail = fetch_detail_metadata(original_url)
        except Exception as exc:
            detail = {"fetch_error": str(exc)}
        enriched = dict(candidate)
        enriched["detail"] = detail
        enriched["score"] = round(enriched["score"] + candidate_detail_score(record, detail), 4)
        if detail.get("url"):
            enriched["url"] = detail["url"]
        if detail.get("rating_value") and not enriched.get("score_raw"):
            try:
                enriched["score_raw"] = float(detail["rating_value"])
            except ValueError:
                pass
        if detail.get("rating_count") and not enriched.get("review_count"):
            try:
                enriched["review_count"] = int(str(detail["rating_count"]).replace(",", ""))
            except ValueError:
                pass
        enriched_by_original_url[original_url] = enriched

        final_key = enriched["url"]
        existing = final_aggregate.get(final_key)
        if existing is None:
            final_aggregate[final_key] = enriched
        else:
            source_queries = existing.setdefault("source_queries", [])
            for label in enriched.get("source_queries", []):
                if label not in source_queries:
                    source_queries.append(label)
            existing["query_hits"] = max(existing.get("query_hits", 1), enriched.get("query_hits", 1))
            if candidate_sort_key(enriched) > candidate_sort_key(existing):
                final_aggregate[final_key] = {**existing, **enriched, "source_queries": source_queries}

    for batch in ranked:
        for candidate in batch.get("candidates", []):
            enriched = enriched_by_original_url.get(candidate["url"])
            if not enriched:
                continue
            candidate.update(
                {
                    "detail": enriched.get("detail"),
                    "score": enriched.get("score"),
                    "score_raw": enriched.get("score_raw"),
                    "review_count": enriched.get("review_count"),
                    "url": enriched.get("url", candidate["url"]),
                }
            )
        batch["candidates"].sort(key=candidate_sort_key, reverse=True)

    best = sorted(
        final_aggregate.values(),
        key=candidate_sort_key,
        reverse=True,
    )
    fallback_queries = []
    if not best or best[0].get("score", 0) < 6:
        fallback_queries = fallback_search_queries(record)

    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "prefecture": record.get("prefecture"),
        "city": record.get("city"),
        "district": record.get("district"),
        "native_meta": native_meta,
        "queries": ranked,
        "best_candidates": best[:limit_per_query],
        "fallback_queries": fallback_queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N restaurants before matching")
    parser.add_argument("--limit", type=int, default=25, help="Process only the first N restaurants")
    parser.add_argument("--only-id", help="Process only a single restaurant id")
    parser.add_argument("--top", type=int, default=5, help="Keep top N candidates per query/record")
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds to sleep between requests")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSON path")
    parser.add_argument("--progress-file", help="Optional JSON progress sidecar path")
    args = parser.parse_args()

    records = load_records()
    if args.only_id:
        records = [record for record in records if record.get("id") == args.only_id]
    else:
        records = records[args.offset : args.offset + args.limit]

    output_path = Path(args.output)
    progress_path = Path(args.progress_file) if args.progress_file else output_path.with_suffix(output_path.suffix + ".progress.json")
    payload = []
    for index, record in enumerate(records, start=1):
        progress_path.write_text(
            json.dumps(
                {
                    "done": index - 1,
                    "total": len(records),
                    "current_id": record.get("id"),
                    "current_name": record.get("name"),
                    "output": str(output_path),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
        payload.append(rank_candidates(record, limit_per_query=args.top, pause_seconds=args.pause))
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        progress_path.write_text(
            json.dumps(
                {
                    "done": index,
                    "total": len(records),
                    "current_id": record.get("id"),
                    "current_name": record.get("name"),
                    "output": str(output_path),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
        print(f"Matched {index}/{len(records)}: {record.get('name')}")

    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    progress_path.write_text(
        json.dumps(
            {
                "done": len(payload),
                "total": len(records),
                "status": "completed",
                "output": str(output_path),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"Wrote {len(payload)} records to {output_path}")


if __name__ == "__main__":
    main()
