#!/usr/bin/env python3
"""Generate Tabelog candidate matches for Japan dining venues.

This does not publish ratings directly. It fetches Tabelog search pages,
extracts plausible candidates, scores them, and writes the ranked results to
data/tabelog-match-candidates.json for review or later auto-accept logic.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESTAURANTS_PATH = DATA_DIR / "japan-restaurants.json"
OUTPUT_PATH = DATA_DIR / "tabelog-match-candidates.json"
CACHE_PATH = DATA_DIR / "tabelog-match-http-cache.json"
USER_AGENT = "ChargingTheChargeCard/0.1 (+https://local.dev)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)
POCKET_JP_RESTAURANT_URL = "https://pocket-concierge.jp/restaurants/{id}/"
HTTP_CACHE = {"native_meta": {}, "search_pages": {}, "detail_pages": {}}
BROWSE_INDEX: dict[str, list[dict]] = {}  # prefecture_slug -> list of candidates from area browse
# Dense prefectures: browse sub-areas to bypass Tabelog's 60-page-per-area cap.
# Discovered from each prefecture's index page (e.g., tabelog.com/tokyo/).
DENSE_PREFECTURE_SUBAREAS: dict[str, list[str]] = {}
def tlog(msg: str) -> None:
    """Print a timestamped log message."""
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def progress_bar(
    current: int,
    total: int,
    start_time: datetime.datetime,
    name: str = "",
    status_counts: dict[str, int] | None = None,
) -> None:
    """Render an inline progress bar with ETA."""
    cols = shutil.get_terminal_size((80, 20)).columns
    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    rate = current / elapsed if elapsed > 0 else 0
    eta = (total - current) / rate if rate > 0 else 0
    pct = current / total if total else 1
    eta_str = f"{int(eta // 60)}m{int(eta % 60):02d}s" if eta < 3600 else f"{eta / 3600:.1f}h"
    elapsed_str = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"

    stats = ""
    if status_counts:
        v = status_counts.get("verified", 0)
        r = status_counts.get("review", 0)
        j = status_counts.get("reject", 0)
        stats = f" V:{v} R:{r} X:{j}"

    info = f" {current}/{total} [{elapsed_str}<{eta_str}, {rate:.1f}/s]{stats}"
    name_part = f" {name[:20]}" if name else ""
    bar_width = max(10, cols - len(info) - len(name_part) - 4)
    filled = int(bar_width * pct)
    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    line = f"\r{bar}{info}{name_part}"
    sys.stderr.write(line[:cols])
    sys.stderr.flush()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

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
EN_WARD_RE = re.compile(r"\b([A-Za-z][A-Za-z'’ -]+-ku)\b", re.IGNORECASE)
JP_WARD_RE = re.compile(r"([\u3400-\u9fff]{1,10}区)")
STATION_NAME_RE = re.compile(r"(?:JR\s+)?([A-Za-z0-9'’` -]+?)\s+Station", re.IGNORECASE)
MOVED_SUCCESSOR_RE = re.compile(
    r'移転前の店舗情報です。新しい店舗は<a href="(?P<url>https://tabelog\.com/[^"]+/)"',
    re.DOTALL,
)
YAHOO_RESULT_RE = re.compile(
    r"<li><a href=\"(?P<url>https://(?:selection\.tabelog\.com|s\.tabelog\.com|tabelog\.com)/[^\"]+)\"[^>]*>(?P<title>.*?)</a>(?P<body>.*?)(?=</li>)",
    re.DOTALL,
)
DDG_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL,
)
DDG_SNIPPET_RE = re.compile(
    r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
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


def load_http_cache(path: Path) -> None:
    global HTTP_CACHE
    if not path.exists():
        HTTP_CACHE = {"native_meta": {}, "search_pages": {}, "detail_pages": {}, "llm_judgments": {}}
        return
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        payload = {}
    HTTP_CACHE = {
        "native_meta": payload.get("native_meta") or {},
        "search_pages": payload.get("search_pages") or {},
        "detail_pages": payload.get("detail_pages") or {},
        "llm_judgments": payload.get("llm_judgments") or {},
    }


def atomic_write_json(path: Path, data: object) -> None:
    """Write JSON to a file atomically via temp file + rename."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_http_cache(path: Path) -> None:
    atomic_write_json(path, HTTP_CACHE)


def load_env_value(key: str) -> str:
    direct = os.getenv(key)
    if direct:
        return direct
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("'\"")
    return ""


def fetch(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc
    user_agent = BROWSER_USER_AGENT if host in {"search.yahoo.co.jp", "www.bing.com", "bing.com", "tabelog.com", "html.duckduckgo.com"} else USER_AGENT
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def groq_judge_match(record: dict, candidates: list[dict]) -> dict | None:
    """Use Groq LLM to pick the best Tabelog match from ambiguous candidates.

    Returns the chosen candidate dict with updated match_status/confidence,
    or None if the LLM says no match.
    """
    api_key = load_env_value("GROQ_API_KEY")
    if not api_key:
        return None

    # Build cache key
    cache_key = f"{record.get('id')}:{','.join(c['url'] for c in candidates[:5])}"
    cached = HTTP_CACHE.get("llm_judgments", {}).get(cache_key)
    if cached is not None:
        if not cached.get("chosen_url"):
            return None
        for c in candidates:
            if c["url"] == cached["chosen_url"]:
                c["match_status"] = "review"
                c["match_confidence"] = max(c.get("match_confidence", 0), 60)
                c["match_reasons"] = list(c.get("match_reasons") or []) + ["groq_judge"]
                return c
        return None

    # Build prompt
    restaurant_info = (
        f"Name: {record.get('name')}\n"
        f"Japanese name: {record.get('_native_title') or 'unknown'}\n"
        f"Prefecture: {record.get('prefecture')}\n"
        f"City: {record.get('city')}\n"
        f"District: {record.get('district')}\n"
        f"Address: {record_address_anchor(record)}\n"
        f"Phone: {record.get('phone_number') or 'unknown'}\n"
        f"Cuisine: {', '.join(record.get('cuisines') or [])}\n"
        f"Nearest station: {record.get('nearest_stations_text') or 'unknown'}"
    )

    candidate_lines = []
    for i, c in enumerate(candidates[:5], 1):
        detail = c.get("detail") or {}
        candidate_lines.append(
            f"Candidate {i}:\n"
            f"  URL: {c['url']}\n"
            f"  Name on Tabelog: {c.get('name') or detail.get('name') or 'unknown'}\n"
            f"  Address: {detail.get('street_address') or detail.get('full_address_text') or 'unknown'}\n"
            f"  Phone: {detail.get('telephone') or 'unknown'}\n"
            f"  Cuisine: {detail.get('serves_cuisine') or 'unknown'}\n"
            f"  Score: {c.get('score_raw') or detail.get('rating_value') or 'unknown'}\n"
            f"  Transport: {detail.get('transportation') or 'unknown'}"
        )

    prompt = (
        "You are matching a restaurant from Pocket Concierge to its Tabelog listing.\n\n"
        f"Restaurant to match:\n{restaurant_info}\n\n"
        f"Tabelog candidates:\n{''.join(candidate_lines)}\n\n"
        "Which candidate number is the correct Tabelog listing for this restaurant? "
        "Consider name, address, phone number, and location. "
        "Reply with ONLY the number (1-5) or 'none' if no candidate matches."
    )

    try:
        response = post_json(
            GROQ_API_URL,
            {
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 10,
            },
            {"Authorization": f"Bearer {api_key}"},
        )
        answer = (response.get("choices", [{}])[0].get("message", {}).get("content") or "").strip().lower()
    except Exception as exc:
        print(f"    Groq error: {exc}")
        return None

    # Parse answer
    chosen_url = None
    if answer and answer[0].isdigit():
        idx = int(answer[0]) - 1
        if 0 <= idx < len(candidates):
            chosen_url = candidates[idx]["url"]

    HTTP_CACHE.setdefault("llm_judgments", {})[cache_key] = {
        "answer": answer,
        "chosen_url": chosen_url,
    }

    if chosen_url:
        for c in candidates:
            if c["url"] == chosen_url:
                c["match_status"] = "review"
                c["match_confidence"] = max(c.get("match_confidence", 0), 60)
                c["match_reasons"] = list(c.get("match_reasons") or []) + ["groq_judge"]
                return c
    return None


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def clean_table_detail_text(value: str) -> str:
    cleaned = strip_tags(value)
    cleaned = re.sub(r"\bShow larger map\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bFind nearby restaurants\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_station_hint(value: str) -> str:
    hints = extract_station_hints(value)
    if hints:
        return hints[0]
    cleaned = clean_table_detail_text(value)
    cleaned = re.sub(r"(?i)^(?:a|an|about a|about|it is a|it is an)\s+\d+-minute\s+walk from\s+", "", cleaned)
    cleaned = re.sub(r"(?i)^\d+-minute\s+walk from\s+", "", cleaned)
    cleaned = re.sub(r"(?i)\s+on the\s+.+$", "", cleaned)
    cleaned = re.sub(r"(?i)\s+on\s+.+$", "", cleaned)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_station_hints(value: str) -> list[str]:
    raw = clean_table_detail_text(value)
    if not raw:
        return []

    items = [re.sub(r"\s+", " ", match.group(1)).strip(" ,") for match in STATION_NAME_RE.finditer(raw)]
    if "nearest station" in raw.lower() and items:
        items = items[-1:] + items[:-1]

    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        normalized = normalize_ascii(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(item)
    return ordered


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
    canonical = canonical_candidate_url(url)
    if "/en/" in canonical:
        return canonical
    return canonical.replace("https://tabelog.com/", "https://tabelog.com/en/", 1)


def canonical_candidate_url(url: str) -> str:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.netloc not in {"tabelog.com", "selection.tabelog.com", "s.tabelog.com"}:
        return url
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] in {"en", "cn", "tw", "kr"}:
        path_parts = path_parts[1:]
    id_index = next((index for index, part in enumerate(path_parts) if part.isdigit()), None)
    if id_index is None or id_index < 2:
        return url
    canonical_parts = path_parts[: id_index + 1]
    canonical_path = "/" + "/".join(canonical_parts) + "/"
    return urllib.parse.urlunsplit(("https", "tabelog.com", canonical_path, "", ""))


def normalize_digits(value: str) -> str:
    return "".join(DIGIT_RE.findall(value or ""))


def address_block_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.findall(r"\d+(?:-\d+)+|\d+", normalized)


def address_blocks_match(left: str, right: str) -> bool:
    left_tokens = address_block_tokens(left)
    right_tokens = address_block_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    left_hyphenated = [token for token in left_tokens if "-" in token]
    right_hyphenated = [token for token in right_tokens if "-" in token]
    if left_hyphenated and right_hyphenated:
        left_core = set(left_hyphenated)
        right_core = set(right_hyphenated)
        if left_core & right_core:
            return True

    left_joined = " ".join(left_tokens)
    right_joined = " ".join(right_tokens)
    return bool(left_joined and right_joined and (left_joined in right_joined or right_joined in left_joined))


def primary_address_block(value: str) -> str:
    tokens = address_block_tokens(value)
    for token in tokens:
        if "-" in token:
            return token
    return tokens[0] if tokens else ""


def address_locality_hints(record: dict) -> list[str]:
    address = record_address_anchor(record)
    items = [
        record.get("district") or "",
        *(match.group(1) for match in EN_WARD_RE.finditer(address)),
        *(match.group(1) for match in JP_WARD_RE.finditer(address)),
    ]

    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        item = (item or "").strip()
        if not item:
            continue
        normalized = normalize_unicode(item) if JP_CHAR_RE.search(item) else normalize_ascii(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(item)
    return ordered


def hyphenated_phone_variants(local_digits: str) -> list[str]:
    digits = normalize_digits(local_digits)
    if not digits:
        return []
    patterns: list[tuple[int, int, int]] = []
    if len(digits) == 10:
        patterns = [(2, 4, 4), (3, 3, 4), (4, 2, 4)]
    elif len(digits) == 11:
        patterns = [(3, 4, 4), (4, 3, 4), (5, 2, 4)]

    variants: list[str] = []
    for first, second, third in patterns:
        if first + second + third != len(digits):
            continue
        parts = [digits[:first], digits[first : first + second], digits[first + second :]]
        variants.append("-".join(parts))
        variants.append(" ".join(parts))
    return variants


def phone_query_variants(value: str) -> list[str]:
    digits = normalize_digits(value or "")
    if not digits:
        return []
    variants: list[str] = []
    if digits.startswith("81") and len(digits) >= 11:
        local = "0" + digits[2:]
        variants.append(local)
        variants.extend(hyphenated_phone_variants(local))
    variants.append(digits)
    variants.extend(hyphenated_phone_variants(digits))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


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


def record_location_terms(record: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        key = normalize_unicode(value) if JP_CHAR_RE.search(value) else normalize_ascii(value)
        if not key or key in seen:
            return
        seen.add(key)
        terms.append(value)

    for key in ["district", "city", "prefecture"]:
        add_term(record.get(key) or "")

    station_hint = extract_station_hint(record.get("nearest_stations_text") or "")
    add_term(station_hint)

    for keyword in record.get("_native_keywords") or []:
        if looks_like_location_keyword(keyword):
            add_term(keyword)

    return terms


def search_alias_terms(record: dict) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    def add_alias(value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        key = normalize_unicode(value) if JP_CHAR_RE.search(value) else normalize_ascii(value)
        if not key or key in seen:
            return
        seen.add(key)
        aliases.append(value)

    native_title = (record.get("_native_title") or "").strip()
    english_name = (record.get("name") or "").strip()
    add_alias(native_title)
    add_alias(english_name)
    for alias in record.get("_native_aliases") or []:
        add_alias(alias)
    for keyword in record.get("_native_keywords") or []:
        if looks_like_location_keyword(keyword) or keyword in GENERIC_JP_KEYWORDS:
            continue
        add_alias(keyword)

    return aliases


def fetch_native_metadata(record_id: str) -> dict:
    cached = HTTP_CACHE["native_meta"].get(record_id)
    if cached:
        return dict(cached)

    url = POCKET_JP_RESTAURANT_URL.format(id=record_id.split("-")[-1])
    try:
        html_text = fetch(url)
    except Exception:
        payload = {"title": "", "title_without_reading": "", "keywords": []}
        HTTP_CACHE["native_meta"][record_id] = payload
        return dict(payload)
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

    payload = {
        "title": cleaned_title,
        "title_without_reading": title_without_reading,
        "keywords": useful_keywords,
    }
    HTTP_CACHE["native_meta"][record_id] = payload
    return dict(payload)


def fetch_detail_metadata(url: str, _visited: set[str] | None = None) -> dict:
    _visited = _visited or set()
    if url in _visited:
        return {}
    _visited.add(url)
    cached = HTTP_CACHE["detail_pages"].get(url)
    if cached is not None:
        return dict(cached)

    html_text = fetch(english_candidate_url(url))
    moved_match = MOVED_SUCCESSOR_RE.search(html_text)
    if moved_match:
        successor_url = canonical_candidate_url(moved_match.group("url"))
        if successor_url and successor_url != url:
            successor = fetch_detail_metadata(successor_url, _visited)
            if successor:
                payload = dict(successor)
                payload.setdefault("moved_from", canonical_candidate_url(url))
                HTTP_CACHE["detail_pages"][url] = payload
                return dict(payload)

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
        payload = {
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
        HTTP_CACHE["detail_pages"][url] = payload
        return dict(payload)
    HTTP_CACHE["detail_pages"][url] = {}
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
        {
            "verified": 2,
            "review": 1,
            "reject": 0,
        }.get(item.get("match_status"), -1),
        item.get("match_confidence", 0),
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


def native_location_terms(record: dict, limit: int = 3) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    native_title_norm = normalize_unicode(record.get("_native_title") or "")
    for keyword in record.get("_native_keywords") or []:
        keyword = (keyword or "").strip()
        if not keyword:
            continue
        if normalize_unicode(keyword) == native_title_norm:
            continue
        if not looks_like_location_keyword(keyword):
            continue
        norm = normalize_unicode(keyword)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        terms.append(keyword)
        if len(terms) >= limit:
            break
    return terms


def search_alias_terms(record: dict, limit: int = 6) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        norm = normalize_unicode(value) if JP_CHAR_RE.search(value) else normalize_ascii(value)
        if not norm or norm in seen:
            return
        seen.add(norm)
        terms.append(value)

    add_term(record.get("_native_title") or "")
    add_term(record.get("name") or "")
    for alias in record.get("_native_aliases") or []:
        add_term(alias)
    for keyword in record.get("_native_keywords") or []:
        if looks_like_location_keyword(keyword) or keyword in GENERIC_JP_KEYWORDS:
            continue
        add_term(keyword)
        if len(terms) >= limit:
            break
    return terms[:limit]


def location_terms(record: dict, limit: int = 3) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        norm = normalize_unicode(value) if JP_CHAR_RE.search(value) else normalize_ascii(value)
        if not norm or norm in seen:
            return
        seen.add(norm)
        terms.append(value)

    for term in address_locality_hints(record):
        add_term(term)
    for term in extract_station_hints(record.get("nearest_stations_text") or "")[:2]:
        add_term(term)
    add_term(record.get("city") or "")
    add_term(record.get("prefecture") or "")
    for term in native_location_terms(record, limit=limit):
        add_term(term)
    return terms[:limit]


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
                "url": "https://search.yahoo.co.jp/search?p="
                + urllib.parse.quote(query_text),
            }
        )

    alias_terms = search_alias_terms(record)
    phone_terms = phone_query_variants(record.get("phone_number") or "")
    address_block = primary_address_block(record_address_anchor(record))
    location_term_list = location_terms(record)

    base_terms: list[str] = []
    for alias in alias_terms[:4]:
        if JP_CHAR_RE.search(alias):
            base_terms.append(alias)
        else:
            base_terms.append(f'"{alias}"')

    for base in base_terms:
        brand_terms = ["食べログ"] if JP_CHAR_RE.search(base) else ["Tabelog", "食べログ"]
        for brand_term in brand_terms:
            add_query("yahoo_brand_name", f"{base} {brand_term}")
            if location_term_list:
                add_query("yahoo_brand_name_location", f"{base} {location_term_list[0]} {brand_term}")
            if address_block:
                add_query("yahoo_brand_name_block", f"{base} {address_block} {brand_term}")
            for phone_term in phone_terms[:1]:
                add_query("yahoo_brand_name_phone", f"{base} {phone_term} {brand_term}")
                if location_term_list:
                    add_query("yahoo_brand_name_location_phone", f"{base} {location_term_list[0]} {phone_term} {brand_term}")

        add_query("yahoo_selection_name", f"site:selection.tabelog.com {base}")
        if location_term_list:
            add_query("yahoo_selection_name_location", f"site:selection.tabelog.com {base} {location_term_list[0]}")
        add_query("yahoo_site_name", f"site:tabelog.com {base}")
        if location_term_list:
            add_query("yahoo_site_name_location", f"site:tabelog.com {base} {location_term_list[0]}")
        if address_block:
            add_query("yahoo_site_name_block", f"site:tabelog.com {base} {address_block}")
            add_query("yahoo_selection_name_block", f"site:selection.tabelog.com {base} {address_block}")
        if location_term_list and address_block:
            add_query("yahoo_site_name_location_block", f"site:tabelog.com {base} {location_term_list[0]} {address_block}")
            add_query("yahoo_selection_name_location_block", f"site:selection.tabelog.com {base} {location_term_list[0]} {address_block}")
        for phone_term in phone_terms[:1]:
            add_query("yahoo_site_name_phone", f"site:tabelog.com {base} {phone_term}")
            add_query("yahoo_selection_name_phone", f"site:selection.tabelog.com {base} {phone_term}")
            if location_term_list:
                add_query("yahoo_site_name_location_phone", f"site:tabelog.com {base} {location_term_list[0]} {phone_term}")
                add_query("yahoo_selection_name_location_phone", f"site:selection.tabelog.com {base} {location_term_list[0]} {phone_term}")

    for phone_term in phone_terms[:1]:
        if location_term_list:
            add_query("yahoo_site_phone_location", f"site:tabelog.com {phone_term} {location_term_list[0]}")
        if address_block:
            add_query("yahoo_site_phone_block", f"site:tabelog.com {phone_term} {address_block}")
        add_query("yahoo_brand_phone", f"{phone_term} 食べログ")
        if location_term_list:
            add_query("yahoo_brand_phone_location", f"{phone_term} {location_term_list[0]} 食べログ")

    return queries[:28]


def query_variants(record: dict) -> list[tuple[str, str]]:
    city = (record.get("city") or "").strip()
    prefecture = (record.get("prefecture") or "").strip()
    query_locations = location_terms(record, limit=4)
    address_digits = normalize_digits(record_address_anchor(record))
    address_block = primary_address_block(record_address_anchor(record))
    phone_terms = phone_query_variants(record.get("phone_number") or "")
    slug = PREFECTURE_SLUGS.get(prefecture)
    variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    english_terms = [term for term in search_alias_terms(record) if not JP_CHAR_RE.search(term)]

    def add_variant(label: str, query_text: str, url: str) -> None:
        query_norm = normalize_unicode(query_text) if JP_CHAR_RE.search(query_text) else normalize_ascii(query_text)
        key = f"{label}:{query_norm}"
        if not query_norm or key in seen:
            return
        seen.add(key)
        variants.append((label, url))

    for name in english_terms[:4]:
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
        for location_term in [*query_locations, address_digits]:
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
        for extra_term in [address_block, *phone_terms[:2]]:
            if slug and name and extra_term:
                add_variant(
                    f"prefecture_name_extra:{name} {extra_term}",
                    f"{name} {extra_term}",
                    f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(f'{name} {extra_term}')}",
                )
    # Phone-only queries on English Tabelog
    for phone_term in phone_terms[:3]:
        if slug and phone_term:
            add_variant(
                f"prefecture_phone_only:{phone_term}",
                phone_term,
                f"https://tabelog.com/en/{slug}/rstLst/?sk={urllib.parse.quote(phone_term)}",
            )
    return variants


def native_query_variants(record: dict) -> list[tuple[str, str]]:
    prefecture = (record.get("prefecture") or "").strip()
    slug = PREFECTURE_SLUGS.get(prefecture)
    native_terms = [term for term in search_alias_terms(record) if JP_CHAR_RE.search(term)]
    if not slug or not native_terms:
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

    location_term_list = native_location_terms(record, limit=3)
    address_digits = normalize_digits(record_address_anchor(record))
    address_block = primary_address_block(record_address_anchor(record))
    phone_terms = phone_query_variants(record.get("phone_number") or "")
    for native_title in native_terms[:5]:
        add_variant(f"jp_prefecture_native:{native_title}", native_title)
        for location_term in location_term_list[:2]:
            add_variant(f"jp_prefecture_native_location:{native_title} {location_term}", f"{native_title} {location_term}")
        if address_digits:
            add_variant(f"jp_prefecture_native_digits:{native_title} {address_digits}", f"{native_title} {address_digits}")
        if address_block:
            add_variant(f"jp_prefecture_native_block:{native_title} {address_block}", f"{native_title} {address_block}")
        if location_term_list and address_block:
            add_variant(
                f"jp_prefecture_native_location_block:{native_title} {' '.join(location_term_list[:2])} {address_block}",
                f"{native_title} {' '.join(location_term_list[:2])} {address_block}",
            )
        for phone_term in phone_terms[:2]:
            add_variant(f"jp_prefecture_native_phone:{native_title} {phone_term}", f"{native_title} {phone_term}")
            if location_term_list:
                add_variant(
                    f"jp_prefecture_native_location_phone:{native_title} {' '.join(location_term_list[:2])} {phone_term}",
                    f"{native_title} {' '.join(location_term_list[:2])} {phone_term}",
                )

    # Phone-only queries (phone is nearly unique per restaurant)
    for phone_term in phone_terms[:3]:
        add_variant(f"jp_prefecture_phone_only:{phone_term}", phone_term)

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
                "url": canonical_candidate_url(html.unescape(match.group("url"))),
                "name": strip_tags(name_match.group("name")) if name_match else "",
                "area_genre": strip_tags(area_match.group("text")) if area_match else "",
                "score_raw": float(rating_match.group("rating")) if rating_match else None,
                "review_count": int(review_match.group("count").replace(",", "")) if review_match else None,
            }
        )
    return candidates


def fetch_search_candidates(url: str) -> list[dict]:
    cached = HTTP_CACHE["search_pages"].get(url)
    if cached is not None:
        return [dict(item) for item in cached]
    candidates = parse_candidates(fetch(url))
    HTTP_CACHE["search_pages"][url] = candidates
    return [dict(item) for item in candidates]


def fetch_yahoo_search_candidates(url: str) -> list[dict]:
    cached = HTTP_CACHE["search_pages"].get(url)
    if cached is not None:
        return [dict(item) for item in cached]

    html_text = fetch(url)
    candidates: list[dict] = []
    for match in YAHOO_RESULT_RE.finditer(html_text):
        body = match.group("body")
        candidates.append(
            {
                "url": canonical_candidate_url(html.unescape(match.group("url"))),
                "name": strip_tags(match.group("title")),
                "area_genre": strip_tags(body),
                "score_raw": None,
                "review_count": None,
            }
        )
    HTTP_CACHE["search_pages"][url] = candidates
    return [dict(item) for item in candidates]


def resolve_ddg_url(raw_url: str) -> str:
    """Resolve DuckDuckGo redirect URLs to actual target URLs."""
    raw_url = html.unescape(raw_url)
    if "duckduckgo.com/l/" in raw_url or "duckduckgo.com/y.js" in raw_url:
        parsed = urllib.parse.urlsplit(raw_url)
        params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in params:
            return params["uddg"][0]
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    return raw_url


def fetch_ddg_search_candidates(url: str) -> list[dict]:
    """Fetch search results from DuckDuckGo HTML endpoint, filtering to tabelog.com."""
    cached = HTTP_CACHE["search_pages"].get(url)
    if cached is not None:
        return [dict(item) for item in cached]

    html_text = fetch(url)
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for match in DDG_RESULT_RE.finditer(html_text):
        resolved = resolve_ddg_url(match.group("url"))
        if "tabelog.com" not in resolved:
            continue
        canonical = canonical_candidate_url(resolved)
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        candidates.append(
            {
                "url": canonical,
                "name": strip_tags(match.group("title")),
                "area_genre": "",
                "score_raw": None,
                "review_count": None,
            }
        )
    HTTP_CACHE["search_pages"][url] = candidates
    return [dict(item) for item in candidates]


def ddg_fallback_queries(record: dict) -> list[dict]:
    """Generate DuckDuckGo search queries for Tabelog discovery."""
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
                "label": f"ddg_{label}",
                "query": query_text,
                "url": "https://html.duckduckgo.com/html/?q="
                + urllib.parse.quote(query_text),
            }
        )

    alias_terms = search_alias_terms(record)
    location_term_list = location_terms(record)
    phone_terms = phone_query_variants(record.get("phone_number") or "")
    address_block = primary_address_block(record_address_anchor(record))
    district = (record.get("district") or "").strip()
    city = (record.get("city") or "").strip()
    prefecture = (record.get("prefecture") or "").strip()

    for alias in alias_terms[:4]:
        add_query("site_name", f"{alias} site:tabelog.com")
        if district:
            add_query("site_name_district", f"{alias} {district} site:tabelog.com")
        if city:
            add_query("site_name_city", f"{alias} {city} site:tabelog.com")
        if prefecture:
            add_query("site_name_prefecture", f"{alias} {prefecture} site:tabelog.com")
        if address_block:
            add_query("site_name_block", f"{alias} {address_block} site:tabelog.com")
        add_query("brand_name", f"{alias} 食べログ")
        if city:
            add_query("brand_name_city", f"{alias} {city} 食べログ")

    for phone_term in phone_terms[:3]:
        add_query("site_phone", f"{phone_term} site:tabelog.com")
        add_query("brand_phone", f"{phone_term} 食べログ")
        if city:
            add_query("site_phone_city", f"{phone_term} {city} site:tabelog.com")

    return queries


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


def candidate_match_assessment(record: dict, detail: dict) -> dict:
    if not detail:
        return {
            "status": "reject",
            "confidence": 0,
            "reasons": [],
            "conflicts": ["missing_detail"],
        }

    detail_name = detail.get("name") or ""
    detail_address = " ".join(
        part
        for part in [
            detail.get("street_address") or "",
            detail.get("full_address_text") or "",
            detail.get("address_locality") or "",
            detail.get("address_region") or "",
            detail.get("postal_code") or "",
        ]
        if part
    )
    detail_address_search = normalize_ascii(detail_address)
    locality = normalize_ascii(detail.get("address_locality") or "")
    region = normalize_ascii(detail.get("address_region") or "")

    prefecture = normalize_ascii(record.get("prefecture") or "")
    city = normalize_ascii(record.get("city") or "")
    district = normalize_ascii(record.get("district") or "")
    record_address_digits = normalize_digits(record_address_anchor(record))
    detail_address_digits = normalize_digits(detail_address)
    record_phone = normalize_digits(record.get("phone_number") or "")
    detail_phone = normalize_digits(detail.get("telephone") or "")
    native_aliases = [normalize_unicode(alias) for alias in (record.get("_native_aliases") or []) if alias]
    detail_name_native = normalize_unicode(detail_name)

    prefecture_match = not prefecture or prefecture in region or prefecture in detail_address_search
    city_match = not city or city in locality or city in detail_address_search
    district_match = not district or district in locality or district in detail_address_search
    digits_exact = bool(record_address_digits and detail_address_digits and record_address_digits == detail_address_digits)
    digits_partial = bool(
        record_address_digits
        and detail_address_digits
        and len(record_address_digits) >= 3
        and (record_address_digits in detail_address_digits or detail_address_digits in record_address_digits)
    )
    block_match = address_blocks_match(record_address_anchor(record), detail_address)
    address_digits_good = digits_exact or digits_partial or block_match
    address_digits_conflict = bool(record_address_digits and detail_address_digits and not address_digits_good)
    phone_exact = bool(record_phone and detail_phone and record_phone == detail_phone)
    phone_conflict = bool(record_phone and detail_phone and record_phone != detail_phone)
    native_name_strong = bool(
        detail_name_native
        and native_aliases
        and (
            detail_name_native in native_aliases
            or any(detail_name_native in alias or alias in detail_name_native for alias in native_aliases)
        )
    )
    english_name_strong = overlap_score(record.get("name") or "", detail_name) >= 0.65
    station_strong = overlap_score(record.get("nearest_stations_text") or "", detail.get("transportation") or "") >= 0.45
    locality_missing = not locality.strip()
    identity_anchor_strong = phone_exact and address_digits_good and (native_name_strong or english_name_strong)
    allow_soft_location = prefecture_match and locality_missing and identity_anchor_strong

    reasons: list[str] = []
    conflicts: list[str] = []
    confidence = 0.0

    if prefecture_match:
        confidence += 14
    elif prefecture:
        confidence -= 35
        conflicts.append("prefecture_mismatch")
    if city_match:
        confidence += 14
    elif city and not allow_soft_location:
        confidence -= 30
        conflicts.append("city_mismatch")
    elif city:
        reasons.append("city_soft_match")
        confidence += 4

    if phone_exact:
        reasons.append("phone_exact")
        confidence += 10
    elif phone_conflict:
        conflicts.append("phone_conflict")
        confidence -= 6
    if district_match and district:
        reasons.append("district_match")
        confidence += 16
    elif district and not allow_soft_location:
        conflicts.append("district_mismatch")
        confidence -= 18
    elif district:
        reasons.append("district_soft_match")
        confidence += 4
    if digits_exact:
        reasons.append("address_digits_exact")
        confidence += 20
    elif digits_partial:
        reasons.append("address_digits_partial")
        confidence += 12
    elif block_match:
        reasons.append("address_block_match")
        confidence += 12
    elif record_address_digits and detail_address_digits:
        conflicts.append("address_digits_conflict")
        confidence -= 18
    if native_name_strong:
        reasons.append("native_name_strong")
        confidence += 18
    elif english_name_strong:
        reasons.append("english_name_strong")
        confidence += 12
    if station_strong:
        reasons.append("station_strong")
        confidence += 7

    cuisine_score = overlap_score(" ".join(record.get("cuisine_types") or []), detail.get("serves_cuisine") or "")
    if cuisine_score >= 0.5:
        reasons.append("cuisine_support")
        confidence += 5

    if not (native_name_strong or english_name_strong):
        confidence -= 6
    if not district_match and address_digits_conflict:
        confidence -= 8
        conflicts.append("district_address_conflict")
    if phone_conflict and not (district_match and address_digits_good):
        confidence -= 4

    if prefecture_match and city_match and phone_exact and district_match and address_digits_good and not conflicts:
        confidence = max(confidence, 72)
        if native_name_strong or english_name_strong:
            confidence = max(confidence, 86)

    confidence = max(0, min(100, round(confidence)))
    if confidence >= 70 and not conflicts:
        status = "verified"
    elif confidence >= 55:
        status = "review"
    else:
        status = "reject"
    return {
        "status": status,
        "confidence": confidence,
        "reasons": reasons,
        "conflicts": conflicts,
        "support_count": len(reasons),
        "conflict_count": len(conflicts),
    }


def external_candidate_score(record: dict, candidate: dict, query_label: str) -> float:
    blob = " ".join([candidate.get("name") or "", candidate.get("area_genre") or ""])
    score = 0.0
    score += overlap_score(record.get("name") or "", blob) * 8
    score += overlap_score(" ".join(record.get("_native_aliases") or []), blob) * 10
    if (record.get("district") or "").lower() in blob.lower():
        score += 2.0
    if (record.get("city") or "").lower() in blob.lower():
        score += 1.0
    if query_label.startswith("yahoo_selection"):
        score += 0.5
    return round(score, 4)


def enrich_candidate(record: dict, candidate: dict) -> dict:
    original_url = candidate["url"]
    try:
        detail = fetch_detail_metadata(original_url)
    except Exception as exc:
        detail = {"fetch_error": str(exc)}
    enriched = dict(candidate)
    enriched["detail"] = detail
    enriched["score"] = round(enriched["score"] + candidate_detail_score(record, detail), 4)
    if detail.get("url"):
        enriched["url"] = canonical_candidate_url(detail["url"])
    assessment = candidate_match_assessment(record, detail)
    enriched["match_status"] = assessment["status"]
    enriched["match_confidence"] = assessment["confidence"]
    enriched["match_reasons"] = assessment["reasons"]
    enriched["match_conflicts"] = assessment["conflicts"]
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
    return enriched


def merge_candidate(candidate: dict, aggregate: dict[str, dict]) -> None:
    final_key = candidate["url"]
    existing = aggregate.get(final_key)
    if existing is None:
        aggregate[final_key] = candidate
        return
    source_queries = existing.setdefault("source_queries", [])
    for label in candidate.get("source_queries", []):
        if label not in source_queries:
            source_queries.append(label)
    existing["query_hits"] = max(existing.get("query_hits", 1), candidate.get("query_hits", 1))
    if candidate_sort_key(candidate) > candidate_sort_key(existing):
        aggregate[final_key] = {**existing, **candidate, "source_queries": source_queries}


def pairwise_preference(top_conf: float, second_conf: float, temperature: float = 8.0) -> float:
    delta = (top_conf - second_conf) / max(temperature, 1e-6)
    return 1.0 / (1.0 + math.exp(-delta))


def log_gap_ratio(top_conf: float, second_conf: float) -> float:
    return math.log((top_conf + 1.0) / (second_conf + 1.0))


def apply_margin_policy(best: list[dict]) -> list[dict]:
    if not best:
        return best
    top = best[0]
    second = best[1] if len(best) > 1 else None
    if top.get("match_status") not in {"verified", "review"}:
        return best
    top_conf = top.get("match_confidence", 0)
    second_conf = second.get("match_confidence", 0) if second else 0
    preference = pairwise_preference(top_conf, second_conf)
    log_ratio = log_gap_ratio(top_conf, second_conf)
    clear_win = preference >= 0.9 and log_ratio >= 0.8
    has_conflicts = bool(top.get("match_conflicts") or [])
    support_count = len(top.get("match_reasons") or [])

    if top.get("match_status") == "review" and clear_win and not has_conflicts and top_conf >= 65 and support_count >= 5:
        top["match_status"] = "verified"
        reasons = list(top.get("match_reasons") or [])
        if "margin_promoted" not in reasons:
            reasons.append("margin_promoted")
        top["match_reasons"] = reasons
        return best

    if top.get("match_status") == "verified" and not clear_win:
        top["match_status"] = "review"
        reasons = list(top.get("match_reasons") or [])
        if "close_runner_up" not in reasons:
            reasons.append("close_runner_up")
        top["match_reasons"] = reasons
    return best


def build_decision_trace(best: list[dict]) -> dict:
    def summarize(candidate: dict | None) -> dict | None:
        if not candidate:
            return None
        return {
            "name": candidate.get("name"),
            "url": candidate.get("url"),
            "status": candidate.get("match_status"),
            "confidence": candidate.get("match_confidence", 0),
            "support_count": len(candidate.get("match_reasons") or []),
            "conflict_count": len(candidate.get("match_conflicts") or []),
            "reasons": candidate.get("match_reasons") or [],
            "conflicts": candidate.get("match_conflicts") or [],
        }

    top = best[0] if best else None
    second = best[1] if len(best) > 1 else None
    third = best[2] if len(best) > 2 else None
    top_conf = top.get("match_confidence", 0) if top else 0
    second_conf = second.get("match_confidence", 0) if second else 0
    third_conf = third.get("match_confidence", 0) if third else 0
    top_pref = pairwise_preference(top_conf, second_conf)
    top_log_gap = log_gap_ratio(top_conf, second_conf)
    return {
        "policy_version": "v0.6",
        "top": summarize(top),
        "second": summarize(second),
        "third": summarize(third),
        "gap_top_second": top_conf - second_conf,
        "gap_second_third": second_conf - third_conf,
        "top_vs_second_preference": round(top_pref, 4),
        "top_vs_second_log_gap": round(top_log_gap, 4),
        "suggested_accept": bool(
            top
            and top.get("match_confidence", 0) >= 70
            and not (top.get("match_conflicts") or [])
            and top_pref >= 0.9
            and top_log_gap >= 0.8
        ),
    }


def discover_subareas(slug: str, pause_seconds: float) -> list[str]:
    """Discover sub-area codes for a prefecture from Tabelog's index page.

    Returns area codes like ['A1301', 'A1302', ...] for Tokyo.
    Results are cached in DENSE_PREFECTURE_SUBAREAS.
    """
    if slug in DENSE_PREFECTURE_SUBAREAS:
        return DENSE_PREFECTURE_SUBAREAS[slug]

    url = f"https://tabelog.com/{slug}/"
    try:
        html = fetch(url)
        codes = sorted(set(re.findall(rf"/{re.escape(slug)}/(A\d{{4}})", html)))
    except Exception:
        codes = []
    DENSE_PREFECTURE_SUBAREAS[slug] = codes
    time.sleep(pause_seconds)
    return codes


def _browse_area_pages(
    path_prefix: str, max_pages: int, pause_seconds: float, seen_urls: set[str],
) -> list[dict]:
    """Browse listing pages for one area path and return new candidates."""
    new: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"https://tabelog.com/{path_prefix}/rstLst/{page}/?Srt=D&SrtT=rt&sort_mode=1"
        try:
            page_candidates = fetch_search_candidates(url)
        except Exception:
            break
        if not page_candidates:
            break
        for candidate in page_candidates:
            if candidate["url"] not in seen_urls:
                seen_urls.add(candidate["url"])
                new.append(candidate)
        time.sleep(pause_seconds)
    return new


# Prefectures dense enough to need sub-area browsing (60-page cap per area).
SUBAREA_BROWSE_SLUGS = {"tokyo", "osaka", "kyoto"}


def build_browse_index(slug: str, max_pages: int, pause_seconds: float) -> list[dict]:
    """Browse Tabelog JP area listing pages sorted by rating and return all candidates.

    Uses Japanese listing pages (not /en/) so names are in Japanese for better
    matching against native Pocket Concierge names.

    For dense prefectures (Tokyo/Osaka/Kyoto), Tabelog caps listings at 60 pages
    per area. To get deeper coverage, we browse each sub-area separately and merge
    the results. For Tokyo this means 31 sub-areas instead of one top-level browse.
    """
    if slug in BROWSE_INDEX:
        return BROWSE_INDEX[slug]

    all_candidates: list[dict] = []
    seen_urls: set[str] = set()

    browse_start = datetime.datetime.now()

    if slug in SUBAREA_BROWSE_SLUGS:
        # First browse the top-level listing (captures the top 1200 by rating)
        top_level = _browse_area_pages(slug, min(max_pages, 60), pause_seconds, seen_urls)
        all_candidates.extend(top_level)
        tlog(f"Browse {slug} top-level: {len(top_level)} candidates (60 pages max)")

        # Then browse each sub-area for deeper coverage.
        # Cap per sub-area at 15 pages -- most Amex restaurants are top-rated
        # within their area, so pages 1-15 (300 restaurants) suffices.
        subareas = discover_subareas(slug, pause_seconds)
        pages_per_subarea = min(max_pages, 15)
        for i, area_code in enumerate(subareas, 1):
            area_path = f"{slug}/{area_code}"
            area_new = _browse_area_pages(area_path, pages_per_subarea, pause_seconds, seen_urls)
            all_candidates.extend(area_new)
            tlog(f"  Sub-area {area_code} ({i}/{len(subareas)}): +{len(area_new)} new, {len(all_candidates)} total")
    else:
        all_candidates = _browse_area_pages(slug, max_pages, pause_seconds, seen_urls)

    elapsed = datetime.datetime.now() - browse_start
    BROWSE_INDEX[slug] = all_candidates
    tlog(f"Browse index for {slug}: {len(all_candidates)} total candidates ({elapsed.total_seconds():.1f}s)")
    return all_candidates


def browse_match_candidates(record: dict, browse_pool: list[dict]) -> list[dict]:
    """Find candidates from the browse pool that match the record by name.

    Uses a two-phase approach: exact match first, then looser substring match.
    This prevents false positives like matching 'Defi Georges Marceau' to
    'Restaurant Georges Marceau'.
    """
    native_title = normalize_unicode(record.get("_native_title") or "")
    native_aliases = [normalize_unicode(a) for a in (record.get("_native_aliases") or []) if a]
    native_keywords = [
        normalize_unicode(k) for k in (record.get("_native_keywords") or [])
        if k and not looks_like_location_keyword(k) and k not in GENERIC_JP_KEYWORDS
    ]
    english_name = normalize_ascii(record.get("name") or "")

    def match_strength(candidate: dict) -> int:
        """Return match strength: 3=exact native, 2=exact english, 1=substring, 0=no match."""
        cand_native = normalize_unicode(candidate.get("name") or "")
        cand_ascii = normalize_ascii(candidate.get("name") or "")

        # Exact native name match (strongest)
        if native_title and cand_native and native_title == cand_native:
            return 3
        if native_aliases and cand_native:
            for alias in native_aliases:
                if alias and alias == cand_native:
                    return 3
        if native_keywords and cand_native:
            for kw in native_keywords:
                if kw and kw == cand_native:
                    return 3

        # Exact english name match
        if english_name and cand_ascii and english_name == cand_ascii:
            return 2

        # Substring containment (looser)
        if native_title and cand_native:
            shorter, longer = sorted([native_title, cand_native], key=len)
            if shorter in longer and len(shorter) >= 2 and len(shorter) / len(longer) >= 0.5:
                return 1
        if native_aliases and cand_native:
            for alias in native_aliases:
                if not alias:
                    continue
                shorter, longer = sorted([alias, cand_native], key=len)
                if shorter in longer and len(shorter) >= 2 and len(shorter) / len(longer) >= 0.5:
                    return 1
        if native_keywords and cand_native:
            for kw in native_keywords:
                if not kw:
                    continue
                shorter, longer = sorted([kw, cand_native], key=len)
                if shorter in longer and len(shorter) >= 2 and len(shorter) / len(longer) >= 0.5:
                    return 1
        if english_name and cand_ascii:
            shorter, longer = sorted([english_name, cand_ascii], key=len)
            if shorter in longer and len(shorter) >= 4 and len(shorter) / len(longer) >= 0.5:
                return 1

        return 0

    # Score all candidates
    scored_matches: list[tuple[int, dict]] = []
    for candidate in browse_pool:
        strength = match_strength(candidate)
        if strength > 0:
            scored = dict(candidate)
            scored["score"] = candidate_score(record, candidate, "browse_area")
            scored["query"] = "browse_area"
            scored["_match_strength"] = strength
            scored_matches.append((strength, scored))

    # Return strongest matches first; if exact matches exist, drop substring-only
    if not scored_matches:
        return []
    best_strength = max(s for s, _ in scored_matches)
    matches = [c for s, c in scored_matches if s >= best_strength]
    return sorted(matches, key=lambda c: c.get("score", 0), reverse=True)


def rank_candidates(
    record: dict,
    limit_per_query: int,
    pause_seconds: float,
    mode: str,
    detail_limit_override: int | None,
    browse_pages: int = 0,
) -> dict:
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
    per_query_limit = max(limit_per_query, 10)
    detail_fetch_limit = detail_limit_override or max(limit_per_query * 4, 12)

    # --- Area browse discovery (primary when enabled) ---
    if browse_pages > 0:
        prefecture = (record.get("prefecture") or "").strip()
        slug = PREFECTURE_SLUGS.get(prefecture)
        if slug:
            # Dense cities (Tokyo/Osaka/Kyoto) auto-browse sub-areas to
            # bypass Tabelog's 60-page cap. browse_pages controls depth per area.
            browse_pool = build_browse_index(slug, browse_pages, pause_seconds)
            browse_matches = browse_match_candidates(record, browse_pool)
            if browse_matches:
                ranked.append({
                    "query": "browse_area",
                    "url": f"https://tabelog.com/en/{slug}/rstLst/",
                    "candidates": browse_matches[:per_query_limit],
                })
                for candidate in browse_matches:
                    existing = aggregate.get(candidate["url"])
                    if existing is None:
                        aggregate[candidate["url"]] = {
                            **candidate,
                            "source_queries": ["browse_area"],
                            "query_hits": 1,
                        }
                    else:
                        existing["query_hits"] = existing.get("query_hits", 1) + 1

    # --- Search-based discovery (fallback or when browse disabled) ---
    all_queries = [*native_query_variants(record), *query_variants(record)]
    if browse_pages > 0 and aggregate:
        all_queries = []  # Skip search when browse found candidates

    for query_label, url in all_queries:
        try:
            query_candidates = fetch_search_candidates(url)
        except Exception as exc:
            ranked.append({"query": query_label, "error": str(exc), "candidates": []})
            time.sleep(pause_seconds)
            continue

        enriched_candidates = []
        for candidate in query_candidates:
            candidate["score"] = candidate_score(record, candidate, query_label)
            candidate["query"] = query_label
            enriched_candidates.append(candidate)
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

        enriched_candidates.sort(key=candidate_sort_key, reverse=True)
        ranked.append(
            {
                "query": query_label,
                "url": url,
                "candidates": enriched_candidates[:per_query_limit],
            }
        )
        time.sleep(pause_seconds)

    best_pre_detail = sorted(aggregate.values(), key=candidate_sort_key, reverse=True)
    if mode == "discover":
        best = best_pre_detail[:limit_per_query]
        for candidate in best:
            candidate["match_status"] = "review"
            candidate["match_confidence"] = 0
            candidate["match_reasons"] = []
            candidate["match_conflicts"] = []
        fallback_queries = []
        if not best:
            fallback_queries = fallback_search_queries(record)
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "prefecture": record.get("prefecture"),
            "city": record.get("city"),
            "district": record.get("district"),
            "native_meta": native_meta,
            "queries": ranked,
            "best_candidates": best,
            "fallback_queries": fallback_queries,
        }

    enriched_by_original_url: dict[str, dict] = {}
    final_aggregate: dict[str, dict] = {}
    for candidate in best_pre_detail[:detail_fetch_limit]:
        original_url = candidate["url"]
        enriched = enrich_candidate(record, candidate)
        enriched_by_original_url[original_url] = enriched
        merge_candidate(enriched, final_aggregate)

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
                    "match_status": enriched.get("match_status"),
                    "match_confidence": enriched.get("match_confidence"),
                    "match_reasons": enriched.get("match_reasons"),
                    "match_conflicts": enriched.get("match_conflicts"),
                }
            )
        batch["candidates"].sort(key=candidate_sort_key, reverse=True)

    best = sorted(
        final_aggregate.values(),
        key=candidate_sort_key,
        reverse=True,
    )
    best = apply_margin_policy(best)
    fallback_queries = []
    ddg_queries = []
    top = best[0] if best else None
    runner_up = best[1] if len(best) > 1 else None
    gap = (top.get("match_confidence", 0) - runner_up.get("match_confidence", 0)) if top and runner_up else 999

    # Skip all external fallback when browse mode is active
    if browse_pages == 0 and (not top or top.get("match_status") != "verified" or gap < 12):
        external_aggregate: dict[str, dict] = {}

        # DDG fallback (primary - more reliable)
        ddg_queries = ddg_fallback_queries(record)
        for query in ddg_queries:
            try:
                query_candidates = fetch_ddg_search_candidates(query["url"])
            except Exception:
                continue
            for candidate in query_candidates[:per_query_limit]:
                candidate["score"] = external_candidate_score(record, candidate, query["label"])
                candidate["query"] = query["label"]
                existing = external_aggregate.get(candidate["url"])
                if existing is None or candidate_sort_key(candidate) > candidate_sort_key(existing):
                    external_aggregate[candidate["url"]] = {
                        **candidate,
                        "source_queries": [query["label"]],
                        "query_hits": 1,
                    }
            time.sleep(pause_seconds)

        # Yahoo fallback (secondary)
        fallback_queries = fallback_search_queries(record)
        for query in fallback_queries:
            try:
                query_candidates = fetch_yahoo_search_candidates(query["url"])
            except Exception:
                continue
            for candidate in query_candidates[:per_query_limit]:
                candidate["score"] = external_candidate_score(record, candidate, query["label"])
                candidate["query"] = query["label"]
                existing = external_aggregate.get(candidate["url"])
                if existing is None or candidate_sort_key(candidate) > candidate_sort_key(existing):
                    external_aggregate[candidate["url"]] = {
                        **candidate,
                        "source_queries": [query["label"]],
                        "query_hits": 1,
                    }
            time.sleep(pause_seconds)

        external_best = sorted(external_aggregate.values(), key=candidate_sort_key, reverse=True)
        if external_best:
            ranked.append({"query": "external_fallback", "url": "external_search", "candidates": external_best[:per_query_limit]})
        for candidate in external_best[: max(limit_per_query * 2, 8)]:
            enriched = enrich_candidate(record, candidate)
            merge_candidate(enriched, final_aggregate)

        best = sorted(final_aggregate.values(), key=candidate_sort_key, reverse=True)
        best = apply_margin_policy(best)

    # Groq LLM judge for low-confidence matches
    top = best[0] if best else None
    if top and top.get("match_confidence", 0) < 50 and best:
        groq_pick = groq_judge_match(record, best[:5])
        if groq_pick:
            # Re-sort with the Groq-promoted candidate
            best = sorted(best, key=candidate_sort_key, reverse=True)

    decision_trace = build_decision_trace(best)

    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "prefecture": record.get("prefecture"),
        "city": record.get("city"),
        "district": record.get("district"),
        "native_meta": native_meta,
        "queries": ranked,
        "best_candidates": best[:limit_per_query],
        "decision_trace": decision_trace,
        "fallback_queries": fallback_queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N restaurants before matching")
    parser.add_argument("--limit", type=int, default=25, help="Process only the first N restaurants")
    parser.add_argument("--only-id", help="Process only a single restaurant id")
    parser.add_argument("--only-ids-file", help="JSON file with list of restaurant IDs to process")
    parser.add_argument("--top", type=int, default=5, help="Keep top N candidates per query/record")
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds to sleep between requests")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSON path")
    parser.add_argument("--progress-file", help="Optional JSON progress sidecar path")
    parser.add_argument("--cache-path", default=str(CACHE_PATH), help="Persistent HTTP cache path")
    parser.add_argument("--mode", choices=["full", "discover"], default="full", help="Run discovery only or full matching")
    parser.add_argument("--detail-limit", type=int, help="Override the number of candidate detail pages to fetch per restaurant")
    parser.add_argument("--purge-search-cache", action="store_true", help="Clear all cached search results (keeps detail pages and native metadata)")
    parser.add_argument("--browse-pages", type=int, default=0, help="Use area browse as primary discovery. Number of listing pages to browse per prefecture (0=disabled, 30=recommended)")
    parser.add_argument("--resume", action="store_true", help="Resume from existing output file, skipping already-matched restaurants")
    args = parser.parse_args()

    cache_path = Path(args.cache_path)
    load_http_cache(cache_path)

    if args.purge_search_cache:
        count = len(HTTP_CACHE.get("search_pages", {}))
        HTTP_CACHE["search_pages"] = {}
        save_http_cache(cache_path)
        print(f"Purged {count} cached search results. Detail pages and native metadata preserved.")

    records = load_records()
    if args.only_id:
        records = [record for record in records if record.get("id") == args.only_id]
    elif args.only_ids_file:
        id_set = set(json.loads(Path(args.only_ids_file).read_text()))
        records = [record for record in records if record.get("id") in id_set]
    else:
        records = records[args.offset : args.offset + args.limit]

    output_path = Path(args.output)
    progress_path = Path(args.progress_file) if args.progress_file else output_path.with_suffix(output_path.suffix + ".progress.json")

    # Resume support: load existing results and skip already-processed records
    payload: list[dict] = []
    skip_count = 0
    if args.resume and output_path.exists() and output_path.stat().st_size > 0:
        try:
            payload = json.loads(output_path.read_text())
            skip_count = len(payload)
            print(f"Resuming: loaded {skip_count} existing results from {output_path}")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not load existing results ({exc}), starting fresh")
            payload = []

    run_start = datetime.datetime.now()
    remaining = len(records) - skip_count
    tlog(f"Starting matching run: {remaining} remaining ({skip_count} cached), browse_pages={args.browse_pages}")
    status_counts: dict[str, int] = {"verified": 0, "review": 0, "reject": 0}

    for index, record in enumerate(records, start=1):
        if index <= skip_count:
            continue
        progress_bar(index - skip_count, remaining, run_start, record.get("name", ""), status_counts)
        atomic_write_json(
            progress_path,
            {
                "done": index - 1,
                "total": len(records),
                "current_id": record.get("id"),
                "current_name": record.get("name"),
                "output": str(output_path),
            },
        )
        result = rank_candidates(
            record,
            limit_per_query=args.top,
            pause_seconds=args.pause,
            mode=args.mode,
            detail_limit_override=args.detail_limit,
            browse_pages=args.browse_pages,
        )
        payload.append(result)

        # Track status counts from best candidate
        best = result.get("best_candidates") or []
        top_status = best[0].get("match_status", "reject") if best else "reject"
        status_counts[top_status] = status_counts.get(top_status, 0) + 1

        atomic_write_json(output_path, payload)
        save_http_cache(cache_path)
        atomic_write_json(
            progress_path,
            {
                "done": index,
                "total": len(records),
                "current_id": record.get("id"),
                "current_name": record.get("name"),
                "output": str(output_path),
            },
        )
        progress_bar(index - skip_count, remaining, run_start, record.get("name", ""), status_counts)

    sys.stderr.write("\n")
    sys.stderr.flush()
    atomic_write_json(output_path, payload)
    save_http_cache(cache_path)
    atomic_write_json(
        progress_path,
        {
            "done": len(payload),
            "total": len(records),
            "status": "completed",
            "output": str(output_path),
        },
    )
    total_elapsed = datetime.datetime.now() - run_start
    v, r, x = status_counts.get("verified", 0), status_counts.get("review", 0), status_counts.get("reject", 0)
    tlog(f"Done! {len(payload)} records -> {output_path} ({total_elapsed.total_seconds():.1f}s)")
    tlog(f"Results: {v} verified, {r} review, {x} rejected")


if __name__ == "__main__":
    main()
