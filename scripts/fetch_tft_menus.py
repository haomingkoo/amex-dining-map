#!/usr/bin/env python3
"""Map Amex Table for Two venues to their published set-menu PDFs.

The Amex CDN exposes a JSON directory listing of all published menus at
``dining.1.json``. Each asset is named like ``{slug}-Menu_Platinum.pdf``,
``{slug}-Menu_Centurion.pdf``, or ``{slug}_Menu.pdf``. This script fetches those listings,
fuzzy-matches every PDF to a venue in ``data/table-for-two.json``, downloads
each PDF to compute a content hash, and writes back per-venue menu metadata
so the frontend can link straight to the official PDF.

Buffet venues legitimately have no set menu PDF; those are marked with
``menu_pdf_status = "buffet_no_menu_expected"`` when the reviewed venue
category or app tags identify a buffet, and ``"no_pdf_found"`` otherwise
(review).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
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
MAX_LISTING_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MENU_FILENAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,180}[-_]?Menu(?:[-_](?:Platinum|Centurion))?\.pdf$",
    re.IGNORECASE,
)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def review_queue_sha256(queue: list[dict]) -> str:
    """Fingerprint review content without scrape-time noise or insertion order."""
    stable_items = [
        {key: value for key, value in item.items() if key != "detected_at"}
        for item in queue
    ]
    canonical = json.dumps(
        sorted(stable_items, key=lambda item: json.dumps(item, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, max_bytes: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        "\\" in url
        or any(character.isspace() or ord(character) < 32 for character in url)
        or parsed.scheme != "https"
        or not (host == "americanexpress.com" or host.endswith(".americanexpress.com"))
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("menu source must be an Amex HTTPS URL")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("menu source response exceeds the byte limit")
        payload = resp.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("menu source response exceeds the byte limit")
    return payload


def fetch_aem_menu_listing(source_key: str) -> dict[str, dict]:
    """Return a dict of menu PDF filename -> AEM asset metadata."""
    source = AEM_MENU_SOURCES[source_key]
    payload = json.loads(http_get(source["listing_url"], MAX_LISTING_BYTES))
    menus = {}
    for name, node in payload.items():
        if not isinstance(node, dict):
            continue
        if node.get("jcr:primaryType") != "dam:Asset":
            continue
        if not MENU_FILENAME_RE.fullmatch(name):
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
                pdf_bytes = http_get(url, MAX_PDF_BYTES)
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


def match_venue_candidates(venue_name: str, candidates: list[str]) -> list[str]:
    """Return every candidate at the strongest matching tier."""
    norm_name = normalize_for_match(venue_name)
    norm_no_the = norm_name[3:] if norm_name.startswith("the") else norm_name
    words = venue_name.split()
    norm_first = normalize_for_match(words[0]) if words else ""
    norm_first2 = normalize_for_match(" ".join(words[:2])) if len(words) > 1 else ""

    by_stem: list[tuple[str, str]] = [(normalize_for_match(filename_stem(f)), f) for f in candidates]

    for target in (norm_name, norm_no_the):
        matches = sorted(fname for stem, fname in by_stem if stem == target)
        if matches:
            return matches

    for target in (norm_first2, norm_first):
        if not target:
            continue
        matches = sorted(fname for stem, fname in by_stem if stem == target)
        if matches:
            return matches

    matches = sorted(
        fname
        for stem, fname in by_stem
        if stem and (stem in norm_name or norm_no_the in stem)
    )
    return matches


def match_venue_to_filename(venue_name: str, candidates: list[str]) -> str | None:
    matches = match_venue_candidates(venue_name, candidates)
    return matches[0] if len(matches) == 1 else None


def claim_menu_asset(
    claims: dict[tuple[str, str], str], source_key: str, filename: str, venue_id: str
) -> bool:
    identity = (source_key, filename)
    existing = claims.get(identity)
    if existing is not None and existing != venue_id:
        return False
    claims[identity] = venue_id
    return True


def strongest_asset_claimants(
    venues: list[dict], listings: dict[str, dict[str, dict]]
) -> dict[tuple[str, str], set[str]]:
    claimants: dict[tuple[str, str], set[str]] = {}
    for venue in venues:
        for source_key, listing in listings.items():
            for filename in match_venue_candidates(venue["name"], list(listing)):
                claimants.setdefault((source_key, filename), set()).add(venue["id"])
    return claimants


def has_buffet_tag(venue: dict) -> bool:
    tags = venue.get("app_tags") or []
    return str(venue.get("category") or "").casefold() == "buffet" or any(
        "buffet" in str(tag).casefold() for tag in tags
    )


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

    if pdf_bytes is None or not pdf_bytes.startswith(b"%PDF"):
        if (
            previous.get("status") == "published"
            and previous.get("filename") == listing_entry.get("filename")
            and previous.get("url") == listing_entry.get("url")
            and re.fullmatch(r"[0-9a-f]{64}", str(previous.get("sha256")))
        ):
            return dict(previous)
        return venue_menu_info(venue, None, None, checked_at, previous)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    size = len(pdf_bytes)
    prev_sha = previous.get("sha256")
    same_identity = (
        previous.get("status") == "published"
        and previous.get("filename") == listing_entry.get("filename")
        and previous.get("url") == listing_entry.get("url")
        and previous.get("card") == listing_entry.get("card_key")
    )
    if not same_identity or prev_sha != sha256:
        return {
            "status": "review_required",
            "url": None,
            "filename": listing_entry["filename"],
            "card": listing_entry.get("card_key"),
            "label": listing_entry.get("card_label"),
            "checked_at": checked_at,
            "sha256": sha256,
            "bytes": size,
            "aem_created": listing_entry.get("aem_created"),
            "aem_uuid": listing_entry.get("aem_uuid"),
            "previous_sha256": prev_sha,
        }
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
    if (
        not pdf_bytes.startswith(b"%PDF")
        or MENU_FILENAME_RE.fullmatch(filename) is None
        or Path(filename).name != filename
    ):
        raise ValueError("unsafe menu filename")
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = (cache_dir / filename).resolve()
    if destination.parent != cache_dir.resolve():
        raise ValueError("unsafe menu cache destination")
    destination.write_bytes(pdf_bytes)


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
    observed_assets: set[tuple[str, str]] = set()
    ambiguous_assets: dict[tuple[str, str], str] = {}
    asset_claims: dict[tuple[str, str], str] = {}
    review_queue: list[dict] = []
    candidate_claimants = strongest_asset_claimants(venues, listings)

    for venue in venues:
        previous_menus = venue.get("menu_pdfs") or {}
        source_infos = {}
        listing_matches = {}
        for source_key, listing in listings.items():
            candidates = match_venue_candidates(venue["name"], list(listing.keys()))
            contested = [
                filename
                for filename in candidates
                if len(candidate_claimants[(source_key, filename)]) > 1
            ]
            if contested:
                ambiguous_assets.update(
                    {(source_key, filename): venue["id"] for filename in contested}
                )
                candidates = []
            previous = previous_menus.get(source_key)
            if previous is None and source_key == "platinum":
                previous = venue.get("menu_pdf") or {}
            selected = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                ambiguous_assets.update(
                    {(source_key, filename): venue["id"] for filename in candidates}
                )
                if previous.get("filename") in candidates:
                    selected = previous["filename"]
            if selected:
                asset_key = (source_key, selected)
                if not claim_menu_asset(
                    asset_claims, source_key, selected, venue["id"]
                ):
                    ambiguous_assets[asset_key] = venue["id"]
                    selected = None
            listing_matches[source_key] = selected
        known_filenames = [filename for filename in listing_matches.values() if filename]
        for source_key, listing in listings.items():
            match = listing_matches[source_key]
            entry = listing.get(match) if match else None
            pdf_bytes: bytes | None = None
            observation_failed = False
            if entry is None and known_filenames and not args.no_download:
                entry, pdf_bytes = fetch_direct_menu_entry(source_key, known_filenames)
            if entry and pdf_bytes is None and not args.no_download:
                try:
                    pdf_bytes = http_get(entry["url"], MAX_PDF_BYTES)
                    if not pdf_bytes.startswith(b"%PDF"):
                        raise ValueError("menu asset is not a PDF")
                    if cache_dir is not None and not args.dry_run:
                        maybe_save_pdf(pdf_bytes, entry["filename"], cache_dir)
                except (urllib.error.URLError, ValueError):
                    observation_failed = True
                    print(f"  ! menu observation failed for {venue['name']}", file=sys.stderr)

            previous = previous_menus.get(source_key)
            if previous is None and source_key == "platinum":
                previous = venue.get("menu_pdf") or {}
            info = venue_menu_info(venue, entry, pdf_bytes, checked_at, previous)
            if entry:
                observed_assets.add((source_key, entry["filename"]))
            if info["status"] in {"published", "review_required"}:
                source_infos[source_key] = info
            if info["status"] == "review_required":
                review_queue.append(
                    {
                        "kind": "changed_or_new_venue_menu",
                        "status": "review_required",
                        "venue_id": venue["id"],
                        "venue_name": venue["name"],
                        "card": source_key,
                        "filename": info["filename"],
                        "sha256": info["sha256"],
                        "bytes": info["bytes"],
                        "aem_uuid": info.get("aem_uuid"),
                        "previous_sha256": info.get("previous_sha256"),
                        "detected_at": checked_at,
                    }
                )
            if observation_failed:
                review_queue.append(
                    {
                        "kind": "observation_failed",
                        "status": "review_required",
                        "venue_id": venue["id"],
                        "venue_name": venue["name"],
                        "card": source_key,
                        "filename": entry["filename"],
                        "aem_uuid": entry.get("aem_uuid"),
                        "detected_at": checked_at,
                    }
                )

        venue["menu_pdfs"] = source_infos
        platinum_info = source_infos.get("platinum")
        venue["menu_pdf"] = platinum_info or next(iter(source_infos.values()), venue_menu_info(venue, None, None, checked_at, venue.get("menu_pdf") or {}))

        published_infos = {
            key: info for key, info in source_infos.items() if info["status"] == "published"
        }
        if published_infos:
            matched_menu_count += len(published_infos)
            matched_venue_count += 1
            parts = []
            for key, info in published_infos.items():
                size_str = f"{info['bytes']:,}B" if info["bytes"] else "?"
                parts.append(f"{AEM_MENU_SOURCES[key]['label']}: {info['filename']} ({size_str})")
            print(f"  OK  {venue['name']:38s}  {' | '.join(parts)}")
        elif venue["menu_pdf"]["status"] == "buffet_no_menu_expected":
            buffet_count += 1
            print(f"  BUF {venue['name']:38s}  (buffet — no menu PDF expected)")
        else:
            review_count += 1
            review_queue.append(
                {
                    "kind": "missing_venue_menu",
                    "status": "review_required",
                    "venue_id": venue["id"],
                    "venue_name": venue["name"],
                    "detected_at": checked_at,
                }
            )
            print(f"  ??  {venue['name']:38s}  NO PDF FOUND — review")

    all_assets = {
        (source_key, name)
        for source_key, listing in listings.items()
        for name in listing
    }
    unmatched_assets = []
    for source_key, filename in sorted(all_assets - observed_assets):
        entry = listings[source_key][filename]
        candidate_venue_id = ambiguous_assets.get((source_key, filename))
        candidate_venue_ids = sorted(
            candidate_claimants.get((source_key, filename)) or []
        )
        if len(candidate_venue_ids) > 1:
            candidate_venue_id = None
        asset = {
            "card": source_key,
            "filename": filename,
            "url": entry["url"],
            "aem_created": entry.get("aem_created"),
            "aem_uuid": entry.get("aem_uuid"),
            "classification": (
                "current_venue_duplicate"
                if candidate_venue_ids
                else "not_in_reviewed_roster"
            ),
            "candidate_venue_id": candidate_venue_id,
            "candidate_venue_ids": candidate_venue_ids,
            "review_status": "review_required",
            "detected_at": checked_at,
        }
        if candidate_venue_ids and not args.no_download:
            try:
                candidate_bytes = http_get(entry["url"], MAX_PDF_BYTES)
                if not candidate_bytes.startswith(b"%PDF"):
                    raise ValueError("menu asset is not a PDF")
                asset["sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
                asset["bytes"] = len(candidate_bytes)
            except (urllib.error.URLError, ValueError):
                asset["observation_error"] = "bounded_pdf_fetch_failed"
        unmatched_assets.append(asset)
        if candidate_venue_ids:
            if candidate_venue_id:
                candidate_venue = next(
                    venue for venue in venues if venue["id"] == candidate_venue_id
                )
                active = (candidate_venue.get("menu_pdfs") or {}).get(source_key) or {}
                asset["active_filename"] = active.get("filename")
                asset["active_sha256"] = active.get("sha256")
            asset["roster_sha256"] = (
                payload.get("source_images") or {}
            ).get("participating_merchants_sha256")
            review_queue.append(
                {"kind": "ambiguous_exact_match", "status": "review_required", **asset}
            )
    unmatched = sorted(asset["filename"] for asset in unmatched_assets)
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
        "unmatched_assets": unmatched_assets,
        "review_queue": review_queue,
        "review_queue_count": len(review_queue),
        "review_queue_sha256": review_queue_sha256(review_queue),
        "review_required": bool(review_count or review_queue),
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
