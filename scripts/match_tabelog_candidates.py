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
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESTAURANTS_PATH = DATA_DIR / "japan-restaurants.json"
OUTPUT_PATH = DATA_DIR / "tabelog-match-candidates.json"
USER_AGENT = "ChargingTheChargeCard/0.1 (+https://local.dev)"

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


def load_records() -> list[dict]:
    return json.loads(RESTAURANTS_PATH.read_text())


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def normalize_ascii(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def tokenize(value: str) -> list[str]:
    return [token for token in normalize_ascii(value).split(" ") if token]


def important_tokens(value: str, ignore: set[str] | None = None) -> set[str]:
    ignore = ignore or set()
    return {token for token in tokenize(value) if token not in ignore and len(token) > 1}


def overlap_score(left: str, right: str) -> float:
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    return len(shared) / max(len(left_tokens), len(right_tokens))


def query_variants(record: dict) -> list[tuple[str, str]]:
    name = (record.get("name") or "").strip()
    city = (record.get("city") or "").strip()
    prefecture = (record.get("prefecture") or "").strip()
    slug = PREFECTURE_SLUGS.get(prefecture)
    variants: list[tuple[str, str]] = []
    if slug and name:
        variants.append((f"prefecture_name:{name}", f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(name)}"))
    if slug and name and city:
        variants.append(
            (
                f"prefecture_name_city:{name} {city}",
                f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(f'{name} {city}')}",
            )
        )
    if name and city and prefecture:
        variants.append(
            (
                f"global_name_city_prefecture:{name} {city} {prefecture}",
                f"https://tabelog.com/en/rstLst/?sk={urllib.parse.quote(f'{name} {city} {prefecture}')}",
            )
        )
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

    if query_label.startswith("prefecture_"):
        score += 0.5

    review_count = candidate.get("review_count") or 0
    if review_count >= 100:
        score += 0.5

    if name_score == 0 and cuisine_score == 0:
        score -= 2

    return round(score, 4)


def rank_candidates(record: dict, limit_per_query: int, pause_seconds: float) -> dict:
    seen_urls: set[str] = set()
    ranked: list[dict] = []

    for query_label, url in query_variants(record):
        try:
            html_text = fetch(url)
        except Exception as exc:
            ranked.append({"query": query_label, "error": str(exc), "candidates": []})
            time.sleep(pause_seconds)
            continue

        query_candidates = []
        for candidate in parse_candidates(html_text):
            if candidate["url"] in seen_urls:
                continue
            seen_urls.add(candidate["url"])
            candidate["score"] = candidate_score(record, candidate, query_label)
            candidate["query"] = query_label
            query_candidates.append(candidate)

        query_candidates.sort(
            key=lambda item: (
                item.get("score", 0),
                item.get("score_raw") or 0,
                item.get("review_count") or 0,
            ),
            reverse=True,
        )
        ranked.append(
            {
                "query": query_label,
                "url": url,
                "candidates": query_candidates[:limit_per_query],
            }
        )
        time.sleep(pause_seconds)

    best = sorted(
        [candidate for batch in ranked for candidate in batch.get("candidates", [])],
        key=lambda item: (
            item.get("score", 0),
            item.get("score_raw") or 0,
            item.get("review_count") or 0,
        ),
        reverse=True,
    )

    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "prefecture": record.get("prefecture"),
        "city": record.get("city"),
        "district": record.get("district"),
        "queries": ranked,
        "best_candidates": best[:limit_per_query],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25, help="Process only the first N restaurants")
    parser.add_argument("--only-id", help="Process only a single restaurant id")
    parser.add_argument("--top", type=int, default=5, help="Keep top N candidates per query/record")
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds to sleep between requests")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSON path")
    args = parser.parse_args()

    records = load_records()
    if args.only_id:
        records = [record for record in records if record.get("id") == args.only_id]
    else:
        records = records[: args.limit]

    payload = []
    for index, record in enumerate(records, start=1):
        payload.append(rank_candidates(record, limit_per_query=args.top, pause_seconds=args.pause))
        print(f"Matched {index}/{len(records)}: {record.get('name')}")

    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(payload)} records to {output_path}")


if __name__ == "__main__":
    main()
