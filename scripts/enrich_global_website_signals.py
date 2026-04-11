#!/usr/bin/env python3
"""
Fetch richer official-site signals for global restaurants and store source-backed facts.

Adds to record["external_signals"]:
  - official_site_title
  - official_site_description
  - official_site_description_source
  - official_site_meta_description
  - official_site_serves_cuisine
  - official_site_keywords
  - official_site_headings
  - official_site_final_url
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import urllib.error
import urllib.request

try:
    from lxml import html as lxml_html
except Exception:  # pragma: no cover - optional dependency
    lxml_html = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GLOBAL_PATH = DATA_DIR / "global-restaurants.json"
CACHE_PATH = DATA_DIR / "global-website-signals-cache.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

GENERIC_TEXT_MARKERS = (
    "embeddable widget",
    "book online",
    "book your table",
    "book a table",
    "book now",
    "make a booking",
    "reserve a table",
    "reserve now",
    "find a table",
    "cookie",
    "privacy policy",
    "javascript",
    "sign in",
    "coming soon",
    "skip to content",
    "accept all",
    "sign up with your email address",
    "receive news and updates",
    "subscribe",
)

GENERIC_TITLE_MARKERS = (
    "google",
    "opentable",
    "resdiary",
    "sevenrooms",
    "quandoo",
)

BOOKING_PATH_MARKERS = (
    "reserv",
    "book",
    "booking",
    "contact",
    "module",
    "gift",
    "find-a-table",
    "new-events",
)

CONTENT_HINTS = (
    "menu",
    "tasting",
    "seasonal",
    "seafood",
    "wine",
    "cocktail",
    "sake",
    "bar",
    "grill",
    "charcoal",
    "rooftop",
    "harbour",
    "beach",
    "ocean",
    "degustation",
    "omakase",
    "steak",
    "restaurant",
    "brasserie",
    "izakaya",
    "produce",
    "ingredient",
    "chef",
    "dining",
)

BAD_VISIBLE_MARKERS = (
    " monday ",
    " tuesday ",
    " wednesday ",
    " thursday ",
    " friday ",
    " saturday ",
    " sunday ",
    " hours ",
    " until late",
    "open daily",
    "info@",
    "@",
)

ADDRESS_MARKERS = (
    " avenue",
    " ave",
    " street",
    " st ",
    " road",
    " rd ",
    " boulevard",
    " blvd",
    " floor",
    " level",
    " lane",
)

RESTAURANTISH_TYPES = {
    "restaurant",
    "foodestablishment",
    "localbusiness",
    "barorpub",
    "cafeorcoffeeshop",
    "bakery",
    "hotel",
}


def compact_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    value = compact_space(html.unescape(str(value)))
    value = value.replace("\xa0", " ").strip()
    return compact_space(value)


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(compact_space(url))
    if not parts.scheme:
        return compact_space(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def looks_booking_path(url: str) -> bool:
    lowered = normalize_url(url).lower()
    return any(marker in lowered for marker in BOOKING_PATH_MARKERS)


def candidate_urls(url: str) -> list[str]:
    """Generate fetch candidates, preferring HTTPS and homepage fallbacks."""
    normalized = normalize_url(url)
    if not normalized:
        return []

    parts = urlsplit(normalized)
    if not parts.netloc:
        return [normalized]

    candidates: list[str] = []

    def add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    root_https = urlunsplit(("https", parts.netloc, "/", "", ""))
    root_http = urlunsplit(("http", parts.netloc, "/", "", ""))
    same_https = urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))

    add(normalized)
    if parts.scheme == "http":
        add(same_https)

    if looks_booking_path(normalized):
        add(root_https)
        add(root_http)

    segments = [segment for segment in (parts.path or "/").split("/") if segment]
    while segments:
        segments = segments[:-1]
        parent = "/" + "/".join(segments)
        if not parent.endswith("/"):
            parent += "/"
        add(urlunsplit(("https", parts.netloc, parent, "", "")))
        add(urlunsplit(("http", parts.netloc, parent, "", "")))

    add(root_https)
    add(root_http)
    return candidates[:8]


def fetch_html(url: str, timeout: int = 14) -> tuple[str, str, int | None]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError(f"non-html content: {content_type}")
        body_bytes = resp.read(400_000)
        if len(body_bytes) == 400_000:
            print(f"  [warn] HTML truncated at 400KB: {url}", file=sys.stderr)
        body = body_bytes.decode("utf-8", errors="replace")
        return body, resp.geturl(), getattr(resp, "status", None)


def xpath_text_list(doc, expression: str, limit: int = 20) -> list[str]:
    values: list[str] = []
    if lxml_html is None:
        return values

    for element in doc.xpath(expression):
        text = clean_text(" ".join(element.itertext()))
        if not text or text in values:
            continue
        values.append(text)
        if len(values) >= limit:
            break
    return values


def parse_html_signals(html_text: str) -> dict[str, Any]:
    if lxml_html is None:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        description_match = re.search(
            r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|twitter:description)["\'][^>]+content=["\']([^"\']+)',
            html_text,
            re.IGNORECASE,
        )
        return {
            "title": clean_text(title_match.group(1)) if title_match else "",
            "metas": {
                "description": clean_text(description_match.group(1)) if description_match else "",
            },
            "headings": [],
            "paragraphs": [],
            "jsonld": [],
        }

    parser = lxml_html.HTMLParser(encoding="utf-8")
    doc = lxml_html.fromstring(html_text, parser=parser)

    metas: dict[str, str] = {}
    for node in doc.xpath("//meta[@content]"):
        key = clean_text(node.get("name") or node.get("property") or node.get("http-equiv") or "").lower()
        value = clean_text(node.get("content"))
        if key and value and key not in metas:
            metas[key] = value

    jsonld_blocks: list[str] = []
    for node in doc.xpath('//script[contains(@type, "ld+json")]'):
        raw = clean_text(node.text)
        if raw:
            jsonld_blocks.append(raw)

    return {
        "title": clean_text(doc.findtext(".//title")),
        "metas": metas,
        "headings": xpath_text_list(doc, "//h1|//h2|//h3", limit=12),
        "paragraphs": xpath_text_list(doc, "//main//p | //article//p | //section//p | //p", limit=40),
        "jsonld": jsonld_blocks,
    }


def collect_jsonld_objects(node: Any, sink: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        sink.append(node)
        for value in node.values():
            collect_jsonld_objects(value, sink)
    elif isinstance(node, list):
        for value in node:
            collect_jsonld_objects(value, sink)


def split_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        parts = value
    elif isinstance(value, str):
        parts = re.split(r"[|,/;•]", value)
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = clean_text(str(part))
        normalized = item.lower()
        if not item or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(item)
    return cleaned[:8]


def is_restaurantish_type(type_value: Any) -> bool:
    if isinstance(type_value, list):
        values = [clean_text(str(item)).lower().lstrip("#") for item in type_value]
    else:
        values = [clean_text(str(type_value)).lower().lstrip("#")] if type_value else []
    return any(value in RESTAURANTISH_TYPES for value in values)


def extract_jsonld_signals(blocks: list[str]) -> dict[str, Any]:
    descriptions: list[str] = []
    serves_cuisine: list[str] = []
    keywords: list[str] = []
    titles: list[str] = []

    for raw in blocks:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        objects: list[dict[str, Any]] = []
        collect_jsonld_objects(parsed, objects)
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if not is_restaurantish_type(obj.get("@type")):
                continue

            name = clean_text(obj.get("name"))
            description = clean_text(obj.get("description"))
            titles.extend([name] if name else [])
            descriptions.extend([description] if description else [])
            serves_cuisine.extend(split_keywords(obj.get("servesCuisine")))
            keywords.extend(split_keywords(obj.get("keywords")))

    return {
        "titles": unique_list(titles, limit=4),
        "descriptions": unique_list(descriptions, limit=6),
        "serves_cuisine": unique_list(serves_cuisine, limit=6),
        "keywords": unique_list(keywords, limit=8),
    }


def unique_list(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def looks_meaningful_text(text: str | None, title: str | None, record_name: str | None) -> bool:
    text = clean_text(text)
    if not text or len(text.split()) < 8:
        return False

    lowered = text.lower()
    weekday_hits = len(re.findall(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered))
    clock_hits = len(re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lowered))
    if any(marker in lowered for marker in GENERIC_TEXT_MARKERS):
        return False
    padded = f" {lowered} "
    if any(marker in padded for marker in BAD_VISIBLE_MARKERS) and not any(hint in lowered for hint in CONTENT_HINTS):
        return False
    if weekday_hits >= 2 or clock_hits >= 2:
        return False
    if any(marker in padded for marker in ADDRESS_MARKERS) and sum(ch.isdigit() for ch in text) >= 3:
        return False
    if sum(ch.isdigit() for ch in text) >= 8 and not any(hint in lowered for hint in CONTENT_HINTS):
        return False

    if title and clean_text(text).lower() == clean_text(title).lower():
        return False

    if record_name and clean_text(text).lower() == clean_text(record_name).lower():
        return False

    return True


def looks_meaningful_title(title: str | None, record_name: str | None) -> bool:
    title = clean_text(title)
    if not title:
        return False
    lowered = title.lower()
    if any(marker in lowered for marker in GENERIC_TITLE_MARKERS):
        return False
    if record_name and clean_text(record_name).lower() == lowered:
        return True
    return len(title.split()) >= 2


def score_text_candidate(text: str, title: str | None, record_name: str | None, source: str) -> int:
    if not looks_meaningful_text(text, title, record_name):
        return -100

    lowered = text.lower()
    score = 20
    if source == "meta":
        score += 18
    elif source == "og:description":
        score += 16
    elif source == "twitter:description":
        score += 14
    elif source == "jsonld":
        score += 16
    elif source == "visible_text":
        score += 12

    if any(hint in lowered for hint in CONTENT_HINTS):
        score += 10
    if record_name and clean_text(record_name).lower() in lowered:
        score += 3

    word_count = len(text.split())
    if 10 <= word_count <= 45:
        score += 8
    elif word_count > 80:
        score -= 6

    return score


def best_visible_paragraph(paragraphs: list[str], title: str | None, record_name: str | None) -> str | None:
    candidates: list[tuple[int, str]] = []
    for paragraph in paragraphs[:20]:
        score = score_text_candidate(paragraph, title, record_name, "visible_text")
        if score > 0:
            candidates.append((score, paragraph))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def extract_signal_payload(html_text: str, page_url: str, record_name: str | None) -> dict[str, Any]:
    parsed = parse_html_signals(html_text)
    metas = parsed.get("metas", {})
    jsonld = extract_jsonld_signals(parsed.get("jsonld", []))
    meta_keywords = split_keywords(metas.get("keywords"))

    title = parsed.get("title") or metas.get("og:title") or metas.get("twitter:title") or ""
    if not looks_meaningful_title(title, record_name):
        title = jsonld["titles"][0] if jsonld["titles"] else title

    description_candidates: list[tuple[str, str]] = []
    for key in ("description", "og:description", "twitter:description"):
        value = clean_text(metas.get(key))
        if value:
            label = {
                "description": "meta",
                "og:description": "og:description",
                "twitter:description": "twitter:description",
            }[key]
            description_candidates.append((label, value))

    for value in jsonld["descriptions"]:
        description_candidates.append(("jsonld", value))

    visible_text = best_visible_paragraph(parsed.get("paragraphs", []), title, record_name)
    if visible_text:
        description_candidates.append(("visible_text", visible_text))

    best_description = ""
    best_source = ""
    best_score = -10_000
    for source, value in description_candidates:
        score = score_text_candidate(value, title, record_name, source)
        if score > best_score:
            best_score = score
            best_description = value
            best_source = source

    payload = {
        "title": clean_text(title),
        "description": clean_text(best_description) if best_score > 0 else "",
        "description_source": best_source if best_score > 0 else "",
        "meta_description": clean_text(metas.get("description")),
        "serves_cuisine": jsonld["serves_cuisine"],
        "keywords": unique_list(meta_keywords + jsonld["keywords"], limit=8),
        "headings": unique_list(parsed.get("headings", []), limit=6),
        "final_url": page_url,
        "score": best_score if best_score > 0 else 0,
    }
    return payload


def result_score(payload: dict[str, Any], record_name: str | None, source_url: str) -> int:
    score = 0
    if payload.get("title"):
        score += 4
    if payload.get("description"):
        score += 25
    if payload.get("serves_cuisine"):
        score += 6
    if payload.get("keywords"):
        score += 5
    if payload.get("headings"):
        score += 3
    score += int(payload.get("score") or 0)

    final_url = normalize_url(payload.get("final_url"))
    if final_url and not looks_booking_path(final_url):
        score += 4
    if final_url and looks_booking_path(final_url):
        score -= 3
    return score


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def fetch_signal(url: str, record_name: str | None) -> tuple[str, dict[str, Any]]:
    errors: list[str] = []
    best_payload: dict[str, Any] | None = None
    best_score = -10_000

    for candidate in candidate_urls(url):
        try:
            html_text, final_url, status = fetch_html(candidate)
            payload = extract_signal_payload(html_text, final_url, record_name)
            payload["fetched_at"] = time.strftime("%Y-%m-%d")
            payload["fetched_from_url"] = candidate
            payload["status"] = status
            score = result_score(payload, record_name, candidate)
            if score > best_score:
                best_score = score
                best_payload = payload
            # Stop early once we have a rich non-booking result.
            if payload.get("description") and not looks_booking_path(final_url):
                break
        except Exception as exc:
            errors.append(f"{candidate} :: {str(exc)[:200]}")

    if best_payload is not None:
        if errors:
            best_payload["attempt_errors"] = errors[:4]
        return url, best_payload

    payload = {
        "error": errors[0] if errors else "unknown fetch failure",
        "fetched_at": time.strftime("%Y-%m-%d"),
    }
    return url, payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="Only enrich records from this country")
    parser.add_argument("--limit", type=int, default=0, help="Only process N unique website URLs")
    parser.add_argument("--pause", type=float, default=0.0, help="Legacy pause option; usually keep at 0 when using concurrency")
    parser.add_argument("--concurrency", type=int, default=10, help="Parallel website fetches (default: 10)")
    parser.add_argument("--force", action="store_true", help="Refresh even when cached")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = json.loads(GLOBAL_PATH.read_text())
    cache = load_cache()

    url_to_records: dict[str, list[dict[str, Any]]] = {}
    for record in data:
        if args.country and record.get("country") != args.country:
            continue
        url = normalize_url(record.get("website_url"))
        if not url:
            continue
        url_to_records.setdefault(url, []).append(record)

    urls = sorted(url_to_records)
    if args.limit:
        urls = urls[:args.limit]

    print(f"Unique website URLs to process: {len(urls)}")

    pending_urls = [url for url in urls if args.force or url not in cache]
    print(f"Cached URLs reused: {len(urls) - len(pending_urls)}")
    print(f"URLs to fetch now: {len(pending_urls)}")

    if pending_urls:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
            future_map = {
                executor.submit(fetch_signal, url, (url_to_records[url][0].get("name") or "")): url
                for url in pending_urls
            }
            for processed, future in enumerate(as_completed(future_map), 1):
                url, payload = future.result()
                cache[url] = payload
                if processed % 50 == 0 or processed == len(pending_urls):
                    print(f"  fetched {processed}/{len(pending_urls)} urls")
                if args.pause:
                    time.sleep(args.pause)

    processed = 0
    useful = 0
    for url in urls:
        records = url_to_records[url]
        cached = cache.get(url, {})

        title = clean_text(cached.get("title"))
        description = clean_text(cached.get("description"))
        description_source = clean_text(cached.get("description_source"))
        meta_description = clean_text(cached.get("meta_description"))
        serves_cuisine = unique_list(cached.get("serves_cuisine") or [], limit=6)
        keywords = unique_list(cached.get("keywords") or [], limit=8)
        headings = unique_list(cached.get("headings") or [], limit=6)
        final_url = normalize_url(cached.get("final_url"))

        meaningful = bool(description)
        if meaningful:
            useful += 1

        if args.dry_run:
            print(
                f"DRY {url} | meaningful={meaningful} | source={description_source!r} | "
                f"title={title!r} | description={description!r}"
            )
            processed += 1
            continue

        for record in records:
            signals = dict(record.get("external_signals") or {})

            if title:
                signals["official_site_title"] = title
            else:
                signals.pop("official_site_title", None)

            if description:
                signals["official_site_description"] = description
                signals["official_site_description_source"] = description_source or "unknown"
            else:
                signals.pop("official_site_description", None)
                signals.pop("official_site_description_source", None)

            if meta_description:
                signals["official_site_meta_description"] = meta_description
            else:
                signals.pop("official_site_meta_description", None)

            if serves_cuisine:
                signals["official_site_serves_cuisine"] = serves_cuisine
            else:
                signals.pop("official_site_serves_cuisine", None)

            if keywords:
                signals["official_site_keywords"] = keywords
            else:
                signals.pop("official_site_keywords", None)

            if headings:
                signals["official_site_headings"] = headings
            else:
                signals.pop("official_site_headings", None)

            if final_url:
                signals["official_site_final_url"] = final_url
            else:
                signals.pop("official_site_final_url", None)

            record["external_signals"] = signals

        processed += 1

    if args.dry_run:
        print("(dry-run: no files written)")
        return

    save_json(GLOBAL_PATH, data)
    save_json(CACHE_PATH, cache)
    print(f"Done. Updated {processed} website URLs; {useful} had usable source descriptions.")
    print(f"Output -> {GLOBAL_PATH}")
    print(f"Cache -> {CACHE_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
