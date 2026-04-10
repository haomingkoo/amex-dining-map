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
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
GLOBAL_PATH = DATA_DIR / "global-restaurants.json"

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
UA = "Mozilla/5.0 (compatible; amex-dining-map/1.0)"


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

    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1024,
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
        cuisines = ", ".join(r.get("cuisines") or []) or "contemporary"
        city = r.get("city") or ""
        country = r.get("country") or ""
        name = r.get("name") or ""
        items.append(f"{i}. {name} ({cuisines}) — {city}, {country}")

    return (
        "Write a one-sentence (max 20 words) food-focused description for each of these restaurants. "
        "Focus on the cuisine style and what makes it worth visiting. Be specific and vivid, not generic. "
        "Reply with ONLY a JSON array of strings in the same order, no extra text.\n\n"
        + "\n".join(items)
    )


def parse_batch_response(text: str, count: int) -> list[str | None]:
    """Extract list of descriptions from model response."""
    # Try to find JSON array in response
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end])
            if isinstance(parsed, list):
                # Pad or truncate to match count
                result = [str(s).strip() if s else None for s in parsed]
                if len(result) < count:
                    result.extend([None] * (count - len(result)))
                return result[:count]
        except json.JSONDecodeError:
            pass

    # Fallback: split by lines and take first N non-empty lines
    lines = [line.strip().strip('"').strip("'") for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("[") and not line.startswith("]")]
    result = (lines + [None] * count)[:count]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI descriptions for global restaurants")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--country", help="Filter to a specific country")
    parser.add_argument("--limit", type=int, help="Max records to process (for testing)")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key and not args.dry_run:
        print("ERROR: GROQ_API_KEY not found in environment or .env file.")
        sys.exit(1)

    data = json.loads(GLOBAL_PATH.read_text())
    print(f"Loaded {len(data)} global records.")

    # Filter records that need descriptions
    todo = [
        r for r in data
        if not r.get("summary_official") and not r.get("summary_ai")
        and (not args.country or r.get("country") == args.country)
    ]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Records needing descriptions: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return

    # Index data by id for quick update
    by_id = {r["id"]: r for r in data}

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
            if desc:
                by_id[record["id"]]["summary_ai"] = desc
                print(f"  ✓ {record['name']}: {desc[:70]}...")
                written += 1
            else:
                print(f"  – {record['name']}: no description parsed")

        total_done += written

        # Save after each batch
        GLOBAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"  Saved. Total done so far: {total_done}")

        # Rate limiting — Groq allows ~6000 TPM on free tier
        if batch_num < len(batches):
            time.sleep(2)

    print(f"\nDone. Added descriptions for {total_done} restaurants.")
    print(f"Output → {GLOBAL_PATH}")


if __name__ == "__main__":
    main()
