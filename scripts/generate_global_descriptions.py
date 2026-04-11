#!/usr/bin/env python3
"""
Generate AI descriptions for global (non-Japan) restaurants using Groq.

Adds a `summary_ai` field to each record in data/global-restaurants.json.
Runs incrementally — skips records that already have summary_ai or summary_official.

Usage:
    python3 scripts/generate_global_descriptions.py
    python3 scripts/generate_global_descriptions.py --batch-size 20 --dry-run
    python3 scripts/generate_global_descriptions.py --country France
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
GLOBAL_PATH = DATA_DIR / "global-restaurants.json"

GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
UA = "Mozilla/5.0 (compatible; amex-dining-map/1.0)"


def compact_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def load_api_key() -> str:
    """Load GROQ_API_KEY from env or .env file."""
    val = os.environ.get("GROQ_API_KEY", "")
    if val:
        return val
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"").strip("'")
    return ""


def groq_generate(prompt: str, api_key: str) -> str:
    """Call Groq chat completions API and return the text content."""
    import urllib.request
    import urllib.error

    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.6,
        "max_tokens": 2048,
    }).encode()

    req = urllib.request.Request(
        GROQ_API_URL,
        data=body,
        headers={
            "User-Agent": UA,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 30 * (2 ** attempt)
                print(f"  Groq 429 (rate limit) — waiting {wait}s (attempt {attempt + 1}/5)...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Groq rate limit: gave up after 5 retries")


def build_batch_prompt(records: list[dict]) -> str:
    items = []
    for i, r in enumerate(records, 1):
        cuisines = ", ".join(r.get("cuisines") or []) or "contemporary"
        city = r.get("city") or ""
        country = r.get("country") or ""
        name = r.get("name") or ""
        website = r.get("website_url") or ""
        known_for = ", ".join(r.get("known_for_tags") or [])
        signature = ", ".join(r.get("signature_dish_tags") or [])
        source_summary = (r.get("summary_official") or "").strip()
        signals = r.get("external_signals") or {}
        site_summary = (
            signals.get("official_site_description")
            or signals.get("official_site_meta_description")
            or ""
        ).strip()
        # Extra specificity signals from website enrichment
        headings = "; ".join(signals.get("official_site_headings") or [])
        keywords = ", ".join(signals.get("official_site_keywords") or [])
        serves_cuisine = ", ".join(signals.get("official_site_serves_cuisine") or [])

        line = f"{i}. {name} | {cuisines} | {city}, {country}"
        if website:
            line += f" | {website}"
        if known_for:
            line += f" | known for: {known_for}"
        if signature:
            line += f" | signature: {signature}"
        if serves_cuisine:
            line += f" | serves: {serves_cuisine}"
        if keywords:
            line += f" | keywords: {keywords}"
        if headings:
            line += f" | headings: {headings}"
        if source_summary:
            line += f" | official source: {source_summary}"
        if site_summary and site_summary != source_summary:
            line += f" | official site: {site_summary}"
        items.append(line)

    return (
        "You write restaurant entries for a luxury card dining guide, in the style of the Michelin Guide "
        "or a serious food critic. Entries are 2–3 sentences, 50–80 words.\n\n"
        "THE MICHELIN STYLE — study these principles:\n"
        "1. LEAD with what makes THIS place different from every other restaurant of the same type in the same city. "
        "Not 'a fine Italian restaurant' — but 'the house-made tagliolini with truffle' or 'the wood-fired whole fish'.\n"
        "2. NAME SPECIFICS when the evidence provides them: a signature dish, a named format (omakase counter, "
        "robata grill, degustation), a defining feature (rooftop terrace, natural wine list, open kitchen, 24-seat room).\n"
        "3. RESTAURANT IDENTITY: if headings or keywords suggest the restaurant has a story "
        "(chef-driven, family-owned, long-established, farm-to-table philosophy), reflect that character.\n"
        "4. END with the reason to go — a single clear reason that a diner would tell a friend. Not vague. Specific.\n\n"
        "WRITING STYLE EXAMPLES (style only — do not copy these words into your output):\n"
        "- Style A (rich evidence): Sentence 1 names the specific format or signature (tasting menu, wood-fired grill, "
        "sake counter). Sentence 2 gives the reason to go: the setting, the format, or a distinctive detail.\n"
        "- Style B (medium evidence): Sentence 1 describes the cooking identity clearly. Sentence 2 explains the mood "
        "or draws attention to one feature mentioned in the input (wine list, view, intimacy).\n"
        "- Style C (thin evidence): Two honest, spare sentences. No invented details. State the cuisine and location "
        "plainly and end with a factual reason a diner might choose it over alternatives.\n\n"
        "STRICT RULES:\n"
        "- Only use facts explicitly in the provided input. No invented dishes, chefs, or accolades.\n"
        "- If headings/keywords/serves mention a specific dish, item, or chef's name — that is the most valuable thing to write about. "
        "A named chef, a named dish, or a named ingredient is always preferred over a generic style label.\n"
        "- If evidence is thin, be honest and spare: describe the proposition plainly without padding.\n"
        "- NEVER use: 'culinary journey', 'gastronomic experience', 'standout in the city', 'welcoming atmosphere', "
        "'locals and visitors alike', 'culinary delights', 'a must-visit', 'passionate team', 'a true gem'.\n\n"
        "Reply with ONLY a JSON array of strings in the same order as the input list, no extra text.\n\n"
        + "\n".join(items)
    )


def parse_batch_response(text: str, count: int) -> list[str | None]:
    """Extract list of descriptions from model response."""
    def clean_desc(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        cleaned = cleaned.removeprefix("- ").strip()
        cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned).strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        return cleaned or None

    # Try to find JSON array in response
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end])
            if isinstance(parsed, list):
                # Pad or truncate to match count
                result = [clean_desc(str(s)) if s else None for s in parsed]
                if len(result) < count:
                    result.extend([None] * (count - len(result)))
                return result[:count]
        except json.JSONDecodeError:
            pass

    # Fallback: parse [N. Name]\nDescription format, matching by NUMBER not position.
    # This handles the case where the model outputs descriptions under named headers
    # but potentially in a different order or with gaps.
    print(f"  [warn] JSON parse failed, using name-indexed fallback (snippet: {text[:120]!r})")
    raw_lines = text.splitlines()
    # Build a map: slot_number (1-based) → description text
    slot_map: dict[int, str] = {}
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        m = re.match(r"^\[(\d+)[.)]\s*", line)
        if m or (re.match(r"^\[", line) and line.endswith("]") and re.search(r"\d+", line)):
            slot = int(m.group(1)) if m else None
            if slot is not None:
                i += 1
                desc_parts: list[str] = []
                while i < len(raw_lines):
                    nxt = raw_lines[i].strip()
                    if not nxt or re.match(r"^\[\d+[.)]\s*", nxt) or (nxt.startswith("[") and nxt.endswith("]")):
                        break
                    desc_parts.append(nxt)
                    i += 1
                if desc_parts:
                    slot_map[slot] = clean_desc(" ".join(desc_parts)) or ""
                continue
        i += 1
    if slot_map:
        # Reconstruct ordered list using slot numbers
        result = [slot_map.get(j) or None for j in range(1, count + 1)]
        return result

    # Last resort: strip numbered prefixes and take lines in order
    lines = [clean_desc(ln) for ln in raw_lines if ln.strip()]
    lines = [ln for ln in lines if ln and not re.match(r"^\[", ln)]
    return (lines + [None] * count)[:count]


def has_description_evidence(record: dict) -> bool:
    """Only generate prose when source files contain enough factual signal."""
    if record.get("summary_official"):
        return True

    if record.get("known_for_tags") or record.get("signature_dish_tags"):
        return True

    signals = record.get("external_signals") or {}
    site_description = compact_space(
        signals.get("official_site_description")
        or signals.get("official_site_meta_description")
    )
    source_type = compact_space(signals.get("official_site_description_source"))
    if len(site_description.split()) >= 8 and source_type in {"meta", "og:description", "twitter:description", "jsonld"}:
        return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI descriptions for global restaurants")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--country", help="Filter to a specific country")
    parser.add_argument("--limit", type=int, help="Max records to process (for testing)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if description exists")
    parser.add_argument("--min-words", type=int, default=0,
                        help="Regenerate descriptions shorter than N words (e.g. --min-words 10)")
    parser.add_argument("--allow-weak-evidence", action="store_true",
                        help="Also generate for records without strong source-backed description signals")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key and not args.dry_run:
        print("ERROR: GROQ_API_KEY not found in environment or .env file.")
        sys.exit(1)

    data = json.loads(GLOBAL_PATH.read_text())
    print(f"Loaded {len(data)} global records.")

    def needs_description(r: dict) -> bool:
        if r.get("summary_official"):
            return False  # always keep official descriptions
        existing = r.get("summary_ai", "")
        if args.force:
            return True
        if args.min_words and existing and len(existing.split()) < args.min_words:
            return True
        return not existing

    # Filter records that need descriptions
    todo = [
        r for r in data
        if needs_description(r)
        and (args.allow_weak_evidence or has_description_evidence(r))
        and (not args.country or r.get("country") == args.country)
    ]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Records needing descriptions: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return

    # Deduplicate todo: first by ID, then by (normalized-name, country).
    # Chain restaurants often share an ID; same-brand chains in the same country
    # (e.g. 50 BLOCK HOUSE locations in Germany) will have unique IDs but produce
    # identical descriptions — deduplicate them to one Groq call and fan out.
    def norm_name(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    seen_ids: set[str] = set()
    seen_name_country: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for r in todo:
        key_id = r["id"]
        key_nc = (norm_name(r.get("name") or ""), (r.get("country") or "").lower())
        if key_id in seen_ids or key_nc in seen_name_country:
            continue
        seen_ids.add(key_id)
        seen_name_country.add(key_nc)
        deduped.append(r)
    if len(deduped) < len(todo):
        print(f"Deduplicated {len(todo)} → {len(deduped)} unique name+country entries.")
    todo = deduped

    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    total_done = 0

    for batch_num, batch in enumerate(batches, 1):
        print(f"\nBatch {batch_num}/{len(batches)} ({len(batch)} records)...")

        if args.dry_run:
            for r in batch:
                print(f"  DRY: {r['name']} ({r['country']})")
            total_done += len(batch)
            continue

        prompt = build_batch_prompt(batch)
        try:
            response = groq_generate(prompt, api_key)
        except Exception as exc:
            print(f"  Groq error: {exc} — skipping batch")
            time.sleep(5)
            continue

        descriptions = parse_batch_response(response, len(batch))
        written = 0
        for record, desc in zip(batch, descriptions):
            # Reject clearly malformed descriptions (stray numbers, parser artifacts)
            if desc and len(desc.split()) < 10:
                print(f"  – {record['name']}: rejected short description ({desc!r})")
                desc = None
            if desc:
                # Fan out to all records sharing the same ID OR the same name+country
                # (handles chains whose locations have unique IDs but identical evidence)
                rec_name = norm_name(record.get("name") or "")
                rec_country = (record.get("country") or "").lower()
                locations = [
                    r for r in data
                    if r["id"] == record["id"]
                    or (norm_name(r.get("name") or "") == rec_name
                        and (r.get("country") or "").lower() == rec_country)
                ]
                for r in locations:
                    r["summary_ai"] = desc
                location_note = f" ({len(locations)} locations)" if len(locations) > 1 else ""
                print(f"  ✓ {record['name']}{location_note}: {desc[:70]}...")
                written += len(locations)
            else:
                print(f"  – {record['name']}: no description parsed")

        total_done += written

        # Save after each batch
        GLOBAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"  Saved. Total done so far: {total_done}")

        # Rate limiting — Groq free tier: ~6000 TPM, ~30 RPM
        # Each batch of 20 uses ~1800 tokens; sleep 15s keeps us under 6000 TPM
        if batch_num < len(batches):
            time.sleep(15)

    print(f"\nDone. Added descriptions for {total_done} restaurants.")
    print(f"Output → {GLOBAL_PATH}")


if __name__ == "__main__":
    main()
