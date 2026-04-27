#!/usr/bin/env python3
"""Map Amex Table for Two venues to their published set-menu PDFs.

The Amex CDN exposes a JSON directory listing of all published menus at
``dining.1.json``. Each asset is named like ``{slug}-Menu_Platinum.pdf`` or
``{slug}-Menu.pdf`` or ``{slug}_Menu.pdf``. This script fetches that listing,
fuzzy-matches every PDF to a venue in ``data/table-for-two.json``, downloads
each PDF to compute a content hash, and writes back per-venue menu metadata
so the frontend can link straight to the official PDF.

Buffet venues (e.g. Colony) legitimately have no set menu PDF; those are
marked with ``menu_pdf_status = "buffet_no_menu_expected"`` when the venue
carries a "Buffet" app tag, and ``"no_pdf_found"`` otherwise (review).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


AEM_LISTING_URL = (
    "https://www.americanexpress.com/content/dam/amex/en-sg/"
    "benefits/the-platinum-card/dining.1.json"
)
AEM_BASE_URL = (
    "https://www.americanexpress.com/content/dam/amex/en-sg/"
    "benefits/the-platinum-card/dining"
)
USER_AGENT = "Mozilla/5.0 (compatible; AmexDiningMap/1.0)"
HTTP_TIMEOUT = 15
MENU_FILENAME_RE = re.compile(r".+-?_?Menu(_Platinum)?\.pdf$", re.IGNORECASE)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_aem_menu_listing() -> dict[str, dict]:
    """Return a dict of menu PDF filename -> AEM asset metadata."""
    payload = json.loads(http_get(AEM_LISTING_URL))
    menus = {}
    for name, node in payload.items():
        if not isinstance(node, dict):
            continue
        if node.get("jcr:primaryType") != "dam:Asset":
            continue
        if not MENU_FILENAME_RE.match(name):
            continue
        menus[name] = {
            "filename": name,
            "url": f"{AEM_BASE_URL}/{name}",
            "aem_created": node.get("jcr:created"),
            "aem_uuid": node.get("jcr:uuid"),
        }
    return menus


def normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def filename_stem(filename: str) -> str:
    stem = filename
    for suffix in ("-Menu_Platinum.pdf", "-Menu.pdf", "_Menu_Platinum.pdf", "_Menu.pdf"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def match_venue_to_filename(venue_name: str, candidates: list[str]) -> str | None:
    """Pick the menu filename that best matches the venue name.

    Strategy: normalize both sides (lowercase alphanumerics only), then prefer
    exact stem match, then "drop the leading 'The'" match, then first-word(s)
    prefix match. Returns the original filename or None.
    """
    norm_name = normalize_for_match(venue_name)
    norm_no_the = norm_name[3:] if norm_name.startswith("the") else norm_name
    words = venue_name.split()
    norm_first = normalize_for_match(words[0]) if words else ""
    norm_first2 = normalize_for_match(" ".join(words[:2])) if len(words) > 1 else ""

    by_stem: list[tuple[str, str]] = [(normalize_for_match(filename_stem(f)), f) for f in candidates]

    for target in (norm_name, norm_no_the):
        for stem, fname in by_stem:
            if stem == target:
                return fname

    for target in (norm_first2, norm_first):
        if not target:
            continue
        for stem, fname in by_stem:
            if stem == target:
                return fname

    for stem, fname in by_stem:
        if not stem:
            continue
        if stem in norm_name or norm_no_the in stem:
            return fname

    return None


def has_buffet_tag(venue: dict) -> bool:
    tags = venue.get("app_tags") or []
    return any("buffet" in t.lower() for t in tags)


def update_venue_menu(
    venue: dict,
    listing_entry: dict | None,
    pdf_bytes: bytes | None,
    checked_at: str,
) -> None:
    """Mutate venue in place with menu PDF metadata."""
    previous = venue.get("menu_pdf") or {}

    if listing_entry is None:
        status = "buffet_no_menu_expected" if has_buffet_tag(venue) else "no_pdf_found"
        venue["menu_pdf"] = {
            "status": status,
            "url": None,
            "filename": None,
            "checked_at": checked_at,
            "first_seen_at": previous.get("first_seen_at"),
            "last_seen_at": previous.get("last_seen_at"),
            "sha256": None,
            "bytes": None,
            "aem_created": None,
            "changed_at": previous.get("changed_at"),
        }
        return

    sha256 = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes is not None else previous.get("sha256")
    size = len(pdf_bytes) if pdf_bytes is not None else previous.get("bytes")
    prev_sha = previous.get("sha256")
    changed_at = checked_at if (prev_sha and sha256 and prev_sha != sha256) else previous.get("changed_at")
    first_seen = previous.get("first_seen_at") or checked_at

    venue["menu_pdf"] = {
        "status": "published",
        "url": listing_entry["url"],
        "filename": listing_entry["filename"],
        "checked_at": checked_at,
        "first_seen_at": first_seen,
        "last_seen_at": checked_at,
        "sha256": sha256,
        "bytes": size,
        "aem_created": listing_entry.get("aem_created"),
        "changed_at": changed_at,
    }


def maybe_save_pdf(pdf_bytes: bytes, filename: str, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / filename).write_bytes(pdf_bytes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/table-for-two.json")
    parser.add_argument("--output", default="data/table-for-two.json")
    parser.add_argument(
        "--cache-dir",
        default="data/tft-menus",
        help="Directory to save downloaded PDFs (set empty to skip).",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Skip PDF downloads (no sha256/bytes computed; faster).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    venues = payload.get("venues") or []
    if not venues:
        print("No venues in input file.", file=sys.stderr)
        return 1

    checked_at = iso_now()
    listing = fetch_aem_menu_listing()
    print(f"AEM listing: {len(listing)} menu PDFs found", file=sys.stderr)

    available_filenames = list(listing.keys())
    matched_count = 0
    buffet_count = 0
    review_count = 0
    matched_filenames: set[str] = set()

    for venue in venues:
        match = match_venue_to_filename(venue["name"], available_filenames)
        entry = listing.get(match) if match else None

        pdf_bytes: bytes | None = None
        if entry and not args.no_download:
            try:
                pdf_bytes = http_get(entry["url"])
                if cache_dir is not None and not args.dry_run:
                    maybe_save_pdf(pdf_bytes, entry["filename"], cache_dir)
            except urllib.error.URLError as exc:
                print(f"  ! download failed for {venue['name']}: {exc}", file=sys.stderr)

        update_venue_menu(venue, entry, pdf_bytes, checked_at)

        info = venue["menu_pdf"]
        if info["status"] == "published":
            matched_count += 1
            matched_filenames.add(entry["filename"])
            size_str = f"{info['bytes']:,}B" if info["bytes"] else "?"
            print(f"  OK  {venue['name']:38s}  {info['filename']:40s}  {size_str}")
        elif info["status"] == "buffet_no_menu_expected":
            buffet_count += 1
            print(f"  BUF {venue['name']:38s}  (buffet — no menu PDF expected)")
        else:
            review_count += 1
            print(f"  ??  {venue['name']:38s}  NO PDF FOUND — review")

    unmatched = sorted(set(available_filenames) - matched_filenames)
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} PDFs in AEM listing did not match any venue:", file=sys.stderr)
        for f in unmatched:
            print(f"  - {f}", file=sys.stderr)

    payload["menu_source"] = {
        "aem_listing_url": AEM_LISTING_URL,
        "checked_at": checked_at,
        "pdfs_in_listing": len(listing),
        "venues_matched": matched_count,
        "venues_buffet": buffet_count,
        "venues_review": review_count,
        "unmatched_pdfs": unmatched,
    }

    print(
        f"\nMatched {matched_count}/{len(venues)} "
        f"(buffet: {buffet_count}, review: {review_count})",
        file=sys.stderr,
    )

    if args.dry_run:
        print("[dry-run] not writing output file", file=sys.stderr)
        return 0

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
