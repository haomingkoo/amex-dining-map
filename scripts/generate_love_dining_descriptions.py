#!/usr/bin/env python3
"""
Generate AI descriptions for Love Dining venues using Groq.

Adds a `summary_ai` field to each record in data/love-dining.json.
Runs incrementally — skips records that already have summary_ai.

Usage:
    python3 scripts/generate_love_dining_descriptions.py
    python3 scripts/generate_love_dining_descriptions.py --batch-size 10 --dry-run
    python3 scripts/generate_love_dining_descriptions.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
LOVE_PATH = DATA_DIR / "love-dining.json"

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
UA = "Mozilla/5.0 (compatible; amex-dining-map/1.0)"


def load_api_key() -> str:
    val = os.environ.get("GROQ_API_KEY", "")
    if val:
        return val
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def groq_generate(prompt: str, api_key: str) -> str:
    import urllib.request

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
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


def build_batch_prompt(records: list[dict]) -> str:
    items = []
    for i, r in enumerate(records, 1):
        cuisine = (r.get("cuisine") or "").replace("\u00a0", " ").strip()
        name = r.get("name") or ""
        venue_type = r.get("type") or "restaurant"
        hotel = r.get("hotel") or ""
        notes = r.get("notes") or ""

        if venue_type == "hotel":
            line = f"{i}. {name} (restaurant at {hotel}) | {cuisine} | Singapore"
        else:
            line = f"{i}. {name} | {cuisine} | Singapore"

        halal_note = ""
        if "halal" in notes.lower():
            halal_note = " | Halal certified"
        if halal_note:
            line += halal_note

        items.append(line)

    return (
        "You are a Singapore dining writer. For each restaurant or hotel dining outlet, write 2 sentences "
        "(35–55 words total) describing its cooking style, setting, and what makes it worth a visit. "
        "All venues participate in the Amex Singapore Love Dining programme — up to 50% off the food bill.\n\n"
        "IMPORTANT RULES to avoid hallucination:\n"
        "- Only name specific dishes if you are genuinely confident they exist at this venue.\n"
        "- For venues you are not certain about, describe the cuisine approach, atmosphere, or occasion — "
        "do NOT invent dish names.\n"
        "- Use language like 'focuses on', 'known for its', 'draws on', 'built around'.\n"
        "- For well-known Singapore venues (Peach Garden, Tung Lok, Jade, etc.) you may cite known signature items.\n"
        "- For hotel outlets, mention the hotel setting briefly.\n\n"
        "Reply with ONLY a JSON array of strings in the same order as the input, no extra text.\n\n"
        + "\n".join(items)
    )


def parse_batch_response(text: str, count: int) -> list[str | None]:
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end])
            if isinstance(parsed, list):
                result = [str(s).strip() if s else None for s in parsed]
                if len(result) < count:
                    result.extend([None] * (count - len(result)))
                return result[:count]
        except json.JSONDecodeError:
            pass

    lines = [line.strip().strip('"').strip("'") for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("[") and not line.startswith("]")]
    result = (lines + [None] * count)[:count]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI descriptions for Love Dining venues")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Regenerate even if description exists")
    parser.add_argument("--min-words", type=int, default=0,
                        help="Regenerate descriptions shorter than N words")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key and not args.dry_run:
        print("ERROR: GROQ_API_KEY not found in environment or .env file.")
        sys.exit(1)

    data = json.loads(LOVE_PATH.read_text())
    print(f"Loaded {len(data)} Love Dining records.")

    def needs_description(r: dict) -> bool:
        existing = r.get("summary_ai", "")
        if args.force:
            return True
        if args.min_words and existing and len(existing.split()) < args.min_words:
            return True
        return not existing

    todo = [r for r in data if needs_description(r)]
    print(f"Records needing descriptions: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return

    by_id = {r["id"]: r for r in data}
    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    total_done = 0

    for batch_num, batch in enumerate(batches, 1):
        print(f"\nBatch {batch_num}/{len(batches)} ({len(batch)} records)...")

        if args.dry_run:
            for r in batch:
                label = f"{r['name']} @ {r.get('hotel', '')}" if r.get("hotel") else r["name"]
                print(f"  DRY: {label} ({r.get('cuisine', '')})")
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
            if desc:
                by_id[record["id"]]["summary_ai"] = desc
                label = f"{record['name']} @ {record.get('hotel', '')}" if record.get("hotel") else record["name"]
                print(f"  ✓ {label}: {desc[:70]}...")
                written += 1
            else:
                print(f"  – {record['name']}: no description parsed")

        total_done += written
        LOVE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"  Saved. Total done so far: {total_done}")

        if batch_num < len(batches):
            time.sleep(2)

    print(f"\nDone. Added descriptions for {total_done} venues.")
    print(f"Output → {LOVE_PATH}")


if __name__ == "__main__":
    main()
