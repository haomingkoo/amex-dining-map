#!/usr/bin/env python3
"""Derive source-backed known-for and specialty tags for global restaurants."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GLOBAL_PATH = DATA_DIR / "global-restaurants.json"

KNOWN_FOR_PATTERNS = [
    (r"\btasting menus?\b|\bdegustation\b", "Tasting menu"),
    (r"\bseasonal menus?\b|\bseasonal dishes\b", "Seasonal menus"),
    (r"\bnostalgic dishes\b", "Nostalgic dishes"),
    (r"\ball-australian beverages\b", "All-Australian drinks"),
    (r"\b24-seat\b|\b24 seat\b|\bsmall dining room\b", "Small dining room"),
    (r"\bover fire and coal\b|\bfire and coal\b", "Fire-and-coal cooking"),
    (r"\bcharcoal\b", "Charcoal cooking"),
    (r"\bmodern asian bbq\b|\bprogressive asian bbq\b", "Modern Asian BBQ"),
    (r"\bwaterfront\b|\bbeachfront\b|\bocean views?\b|\bharbour views?\b|\bclarkes beach\b", "Waterfront views"),
    (r"\bcurated wines?\b|\bwine list\b|\bwine bar\b|\brare and boutique wines?\b", "Wine focus"),
    (r"\bsake list\b", "Sake list"),
    (r"\bcocktail\b", "Cocktails"),
    (r"\bexpress lunch\b", "Express lunch"),
    (r"\bizakaya\b|\bizakayas\b", "Izakaya style"),
    (r"\brooftop\b|\bskyline\b", "Rooftop views"),
    (r"\bwood-?fired\b|\bwood fire\b", "Wood-fired cooking"),
    (r"\blocal produce\b|\bproduce-led\b", "Produce-led menu"),
    (r"\bsushi counter\b", "Sushi counter"),
    (r"\bchef'?s table\b", "Chef's table"),
    (r"景觀餐廳|竹林|山澗|秘境", "Scenic setting"),
    (r"預約制", "Reservation-only"),
]

SIGNATURE_PATTERNS = [
    (r"\btasting menus?\b|\bdegustation\b", "Tasting menu"),
    (r"\bseafood\b", "Seafood"),
    (r"\bsteakhouse\b|\bsteaks?\b|\bcuts\b", "Steaks"),
    (r"\bpintxos\b", "Pintxos"),
    (r"\bsashimi\b", "Sashimi"),
    (r"\bchicken karaage\b", "Chicken karaage"),
    (r"\bwagyu sirloin\b", "Wagyu sirloin"),
    (r"\bsesame noodles\b", "Sesame noodles"),
    (r"\bomakase\b", "Omakase"),
    (r"\bpizza\b", "Pizza"),
    (r"\bpasta\b", "Pasta"),
    (r"\boysters?\b", "Oysters"),
    (r"\byakitori\b", "Yakitori"),
    (r"\bdumplings?\b", "Dumplings"),
    (r"\brobata\b", "Robata grill"),
    (r"\bplant based\b|\bbotanical cuisine\b", "Plant-based cooking"),
    (r"\bpan-?asian food\b|\bcantonese and pan-?asian food\b", "Pan-Asian cooking"),
    (r"\bmodern asian cuisine\b|\bmodern asian\b", "Modern Asian cooking"),
    (r"\bjapanese(?: cuisine)?\b", "Japanese cooking"),
    (r"\bthai(?: cuisine)?\b", "Thai cooking"),
    (r"\bgreek cuisine\b", "Greek cooking"),
    (r"\bgreek taverna\b|\bgreek\b", "Greek cooking"),
    (r"\bspanish(?: cuisine)?\b", "Spanish cooking"),
    (r"\bsicilian\b", "Sicilian cooking"),
    (r"\bitalian cuisine\b", "Italian cooking"),
    (r"\bitalian dining\b|\bitalian\b", "Italian cooking"),
    (r"\bfrench cuisine\b", "French cooking"),
    (r"\beuropean dining\b|\bmodern european\b", "Modern European cooking"),
    (r"\b%E6%AD%90%E4%BA%9E料理\b|歐亞料理", "Eurasian cooking"),
]

SUMMARY_CONTENT_PATTERNS = [
    r"\btasting menus?\b|\bdegustation\b",
    r"\bseafood\b|\bsteakhouse\b|\bsteaks?\b|\bpintxos\b",
    r"\bsashimi\b|\bchicken karaage\b|\bwagyu sirloin\b|\bsesame noodles\b|\bomakase\b",
    r"\bwaterfront\b|\bbeachfront\b|\bocean views?\b|\bharbour views?\b",
    r"\bwine\b|\bsake\b|\bcocktail\b|\bseasonal\b|\bcharcoal\b|\bfire and coal\b",
    r"景觀餐廳|歐亞料理|竹林|山澗|秘境|預約制",
]

SPECIFIC_FOOD_PATTERNS = [
    r"\bchef\b|\bchefs\b",
    r"\bmenu\b|\bmenus\b|\bdishes?\b",
    r"\bproduce\b|\bingredients?\b",
    r"\bsteak\b|\bsteaks\b|\brobata\b|\bgrill\b|\bcharcoal\b|\bfire\b",
    r"\bseafood\b|\bsushi\b|\bomakase\b|\bsashimi\b|\btapas\b|\bpaella\b",
    r"\bwine\b|\bcocktail\b|\bsake\b",
    r"\btaverna\b|\bbrasserie\b|\bizakaya\b",
    r"\bplant based\b|\bbotanical cuisine\b",
]

CTA_SENTENCE_PREFIXES = (
    "book ",
    "reserve ",
    "secure ",
    "contact ",
    "come join ",
)

EVENT_MARKERS = (
    "wedding",
    "weddings",
    "event",
    "events",
    "venue hire",
    "private dining",
    "functions",
    "celebration",
    "gift card",
)


def append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def compact_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def filtered_site_description(record: dict) -> str:
    signals = record.get("external_signals") or {}
    description = compact_space(
        signals.get("official_site_description")
        or signals.get("official_site_meta_description")
    )
    if not description:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", description)
    kept: list[str] = []
    for sentence in sentences:
        cleaned = compact_space(sentence)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(lowered.startswith(prefix) for prefix in CTA_SENTENCE_PREFIXES):
            continue
        if lowered.startswith("located at "):
            continue
        if any(marker in lowered for marker in EVENT_MARKERS):
            continue
        kept.append(cleaned)
    return compact_space(" ".join(kept))


def source_text(record: dict) -> str:
    signals = record.get("external_signals") or {}
    parts = [
        record.get("summary_official"),
        signals.get("official_site_title"),
        filtered_site_description(record),
        " ".join(signals.get("official_site_headings") or []),
        " ".join(signals.get("official_site_keywords") or []),
        " ".join(signals.get("official_site_serves_cuisine") or []),
    ]
    return compact_space(" ".join(part for part in parts if part))


def derive_tags(record: dict) -> tuple[list[str], list[str]]:
    text = source_text(record)
    if not text:
        return [], []

    lowered = text.lower()
    known_for: list[str] = []
    specialties: list[str] = []

    for pattern, label in KNOWN_FOR_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            append_unique(known_for, label)

    for pattern, label in SIGNATURE_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            append_unique(specialties, label)

    return known_for[:4], specialties[:4]


def description_mentions_record_cuisine(record: dict, description: str) -> bool:
    lowered = description.lower()
    for cuisine in record.get("cuisines") or []:
        token = compact_space(cuisine).lower()
        if not token:
            continue
        if token in lowered:
            return True
        for part in re.split(r"[\s/&,-]+", token):
            if len(part) >= 4 and re.search(rf"\b{re.escape(part)}\b", lowered):
                return True
    return False


def cleaned_source_summary(record: dict, known_for: list[str], specialties: list[str]) -> str | None:
    description = filtered_site_description(record)
    if not description:
        return None

    description = re.sub(r"\bBook your table.*$", "", description, flags=re.IGNORECASE).strip(" .")
    description = re.sub(r"\bReserve your table.*$", "", description, flags=re.IGNORECASE).strip(" .")
    description = re.sub(r"\bContact us today.*$", "", description, flags=re.IGNORECASE).strip(" .")
    description = compact_space(description)

    if len(description.split()) < 8:
        return None

    signals = record.get("external_signals") or {}
    description_source = (signals.get("official_site_description_source") or "").strip()

    has_content = (
        any(re.search(pattern, description, flags=re.IGNORECASE) for pattern in SUMMARY_CONTENT_PATTERNS)
        or any(re.search(pattern, description, flags=re.IGNORECASE) for pattern in SPECIFIC_FOOD_PATTERNS)
        or description_mentions_record_cuisine(record, description)
    )

    if known_for or specialties:
        # Tags exist but the description itself must still have food content — tags may have
        # come from headings or keywords, not the description text.
        return description if has_content else None

    if any(re.search(pattern, description, flags=re.IGNORECASE) for pattern in SUMMARY_CONTENT_PATTERNS):
        return description

    if description_source in {"meta", "og:description", "twitter:description", "jsonld"}:
        if any(re.search(pattern, description, flags=re.IGNORECASE) for pattern in SPECIFIC_FOOD_PATTERNS):
            return description
        if description_mentions_record_cuisine(record, description):
            return description

    return None


def main() -> None:
    data = json.loads(GLOBAL_PATH.read_text())
    with_known = 0
    with_specialties = 0
    for record in data:
        known_for, specialties = derive_tags(record)
        record["known_for_tags"] = known_for
        record["signature_dish_tags"] = specialties
        record["summary_official"] = cleaned_source_summary(record, known_for, specialties)
        if known_for:
            with_known += 1
        if specialties:
            with_specialties += 1

    GLOBAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Updated {len(data)} records.")
    print(f"Known-for tags on {with_known} records.")
    print(f"Specialty tags on {with_specialties} records.")
    print(f"Official summaries on {sum(bool((r.get('summary_official') or '').strip()) for r in data)} records.")


if __name__ == "__main__":
    main()
