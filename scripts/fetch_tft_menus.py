#!/usr/bin/env python3
"""Map Amex Table for Two venues to their published set-menu PDFs.

The Amex CDN exposes a JSON directory listing of all published menus at
``dining.1.json``. Each asset is named like ``{slug}-Menu_Platinum.pdf``,
``{slug}-Menu_Centurion.pdf``, or ``{slug}_Menu.pdf``. This script fetches those listings,
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


AEM_MENU_SOURCES = {
    "platinum": {
        "label": "Platinum",
        "listing_url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining.1.json",
        "base_url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining",
    },
    "centurion": {
        "label": "Centurion",
        "listing_url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/centurion/dining-and-lifestyle.1.json",
        "base_url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/centurion/dining-and-lifestyle",
    },
}
USER_AGENT = "Mozilla/5.0 (compatible; AmexDiningMap/1.0)"
HTTP_TIMEOUT = 15
MENU_FILENAME_RE = re.compile(r".+[-_]?Menu(?:[-_](?:Platinum|Centurion))?\.pdf$", re.IGNORECASE)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_aem_menu_listing(source_key: str) -> dict[str, dict]:
    """Return a dict of menu PDF filename -> AEM asset metadata."""
    source = AEM_MENU_SOURCES[source_key]
    payload = json.loads(http_get(source["listing_url"]))
    menus = {}
    for name, node in payload.items():
        if not isinstance(node, dict):
            continue
        if node.get("jcr:primaryType") != "dam:Asset":
            continue
        if not MENU_FILENAME_RE.match(name):
            continue
        menus[name] = {
            "card_key": source_key,
            "card_label": source["label"],
            "filename": name,
            "url": f"{source['base_url']}/{name}",
            "aem_created": node.get("jcr:created"),
            "aem_uuid": node.get("jcr:uuid"),
        }
    return menus


def normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def filename_stem(filename: str) -> str:
    return re.sub(r"[-_]?Menu(?:[-_](?:Platinum|Centurion))?\.pdf$", "", filename, flags=re.IGNORECASE)


def direct_menu_candidate_filenames(stem: str, source_key: str) -> list[str]:
    label = AEM_MENU_SOURCES[source_key]["label"]
    return [
        f"{stem}-Menu_{label}.pdf",
        f"{stem}-Menu-{label}.pdf",
        f"{stem}_Menu_{label}.pdf",
        f"{stem}_Menu-{label}.pdf",
        f"{stem}-Menu.pdf",
        f"{stem}_Menu.pdf",
    ]


def fetch_direct_menu_entry(source_key: str, known_filenames: list[str]) -> tuple[dict | None, bytes | None]:
    """Probe direct PDF URLs when the AEM listing omits a counterpart menu."""
    source = AEM_MENU_SOURCES[source_key]
    seen: set[str] = set()
    stems = [filename_stem(filename) for filename in known_filenames]
    for stem in stems:
        for filename in direct_menu_candidate_filenames(stem, source_key):
            if filename in seen:
                continue
            seen.add(filename)
            url = f"{source['base_url']}/{filename}"
            try:
                pdf_bytes = http_get(url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            if not pdf_bytes.startswith(b"%PDF"):
                continue
            return {
                "card_key": source_key,
                "card_label": source["label"],
                "filename": filename,
                "url": url,
                "aem_created": None,
                "aem_uuid": None,
                "discovered_via": "direct_url_probe",
            }, pdf_bytes
    return None, None


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


def venue_menu_info(
    venue: dict,
    listing_entry: dict | None,
    pdf_bytes: bytes | None,
    checked_at: str,
    previous: dict | None = None,
) -> dict:
    """Return menu PDF metadata for one venue/source pair."""
    previous = previous or {}

    if listing_entry is None:
        status = "buffet_no_menu_expected" if has_buffet_tag(venue) else "no_pdf_found"
        return {
            "status": status,
            "url": None,
            "filename": None,
            "card": None,
            "label": None,
            "checked_at": checked_at,
            "first_seen_at": previous.get("first_seen_at"),
            "last_seen_at": previous.get("last_seen_at"),
            "sha256": None,
            "bytes": None,
            "aem_created": None,
            "changed_at": previous.get("changed_at"),
        }

    sha256 = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes is not None else previous.get("sha256")
    size = len(pdf_bytes) if pdf_bytes is not None else previous.get("bytes")
    prev_sha = previous.get("sha256")
    changed_at = checked_at if (prev_sha and sha256 and prev_sha != sha256) else previous.get("changed_at")
    first_seen = previous.get("first_seen_at") or checked_at

    return {
        "status": "published",
        "url": listing_entry["url"],
        "filename": listing_entry["filename"],
        "card": listing_entry.get("card_key"),
        "label": listing_entry.get("card_label"),
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
    listings = {key: fetch_aem_menu_listing(key) for key in AEM_MENU_SOURCES}
    for key, listing in listings.items():
        print(f"AEM {AEM_MENU_SOURCES[key]['label']} listing: {len(listing)} menu PDFs found", file=sys.stderr)

    matched_menu_count = 0
    matched_venue_count = 0
    buffet_count = 0
    review_count = 0
    matched_filenames: set[str] = set()

    for venue in venues:
        previous_menus = venue.get("menu_pdfs") or {}
        source_infos = {}
        listing_matches = {
            source_key: match_venue_to_filename(venue["name"], list(listing.keys()))
            for source_key, listing in listings.items()
        }
        known_filenames = [filename for filename in listing_matches.values() if filename]
        for source_key, listing in listings.items():
            match = listing_matches[source_key]
            entry = listing.get(match) if match else None
            pdf_bytes: bytes | None = None
            if entry is None and known_filenames and not args.no_download:
                entry, pdf_bytes = fetch_direct_menu_entry(source_key, known_filenames)
            if entry and pdf_bytes is None and not args.no_download:
                try:
                    pdf_bytes = http_get(entry["url"])
                    if cache_dir is not None and not args.dry_run:
                        maybe_save_pdf(pdf_bytes, entry["filename"], cache_dir)
                except urllib.error.URLError as exc:
                    print(f"  ! download failed for {venue['name']}: {exc}", file=sys.stderr)

            previous = previous_menus.get(source_key)
            if previous is None and source_key == "platinum":
                previous = venue.get("menu_pdf") or {}
            info = venue_menu_info(venue, entry, pdf_bytes, checked_at, previous)
            if info["status"] == "published":
                source_infos[source_key] = info
                matched_filenames.add(entry["filename"])

        venue["menu_pdfs"] = source_infos
        platinum_info = source_infos.get("platinum")
        venue["menu_pdf"] = platinum_info or next(iter(source_infos.values()), venue_menu_info(venue, None, None, checked_at, venue.get("menu_pdf") or {}))

        if source_infos:
            matched_menu_count += len(source_infos)
            matched_venue_count += 1
            parts = []
            for key, info in source_infos.items():
                size_str = f"{info['bytes']:,}B" if info["bytes"] else "?"
                parts.append(f"{AEM_MENU_SOURCES[key]['label']}: {info['filename']} ({size_str})")
            print(f"  OK  {venue['name']:38s}  {' | '.join(parts)}")
        elif venue["menu_pdf"]["status"] == "buffet_no_menu_expected":
            buffet_count += 1
            print(f"  BUF {venue['name']:38s}  (buffet — no menu PDF expected)")
        else:
            review_count += 1
            print(f"  ??  {venue['name']:38s}  NO PDF FOUND — review")

    all_filenames = {name for listing in listings.values() for name in listing}
    unmatched = sorted(all_filenames - matched_filenames)
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} PDFs in AEM listing did not match any venue:", file=sys.stderr)
        for f in unmatched:
            print(f"  - {f}", file=sys.stderr)

    payload["menu_source"] = {
        "aem_listing_urls": {key: source["listing_url"] for key, source in AEM_MENU_SOURCES.items()},
        "checked_at": checked_at,
        "pdfs_in_listing": sum(len(listing) for listing in listings.values()),
        "menus_matched": matched_menu_count,
        "venues_matched": matched_venue_count,
        "venues_buffet": buffet_count,
        "venues_review": review_count,
        "unmatched_pdfs": unmatched,
    }

    print(
        f"\nMatched {matched_venue_count}/{len(venues)} venues, {matched_menu_count} menus "
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
