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
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
try:
    from scripts.timeutil import iso_now
except ImportError:  # running as `python3 scripts/<file>.py`
    from timeutil import iso_now

try:
    from scripts import source_change_alert, tft_menu_reviews
    from scripts.tft_menu_reviews import (
        review_item_sha256,
        review_observation_sha256,
        review_queue_sha256,
    )
except ModuleNotFoundError:
    import source_change_alert, tft_menu_reviews
    from tft_menu_reviews import (
        review_item_sha256,
        review_observation_sha256,
        review_queue_sha256,
    )


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
REVIEW_PDF_ROOT = Path("data/reviews/tft-menu-pdfs")
MENU_FILENAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,180}[-_]?Menu(?:[-_](?:Platinum|Platinium|Centurion))?\.pdf$",
    re.IGNORECASE,
)


def matching_terminal_decision(item: dict, decisions: list[dict]) -> dict | None:
    candidate_id = review_item_sha256(item)
    matches = [
        decision
        for decision in decisions
        if decision.get("candidate_id") == candidate_id
        and decision.get("decision") in {"approved", "rejected"}
    ]
    if len(matches) > 1:
        raise ValueError("menu candidate has conflicting terminal decisions")
    return matches[0] if matches else None


def enqueue_review(
    queue: list[dict],
    item: dict,
    decisions: list[dict] | None = None,
    prior_queue: list[dict] | None = None,
) -> dict | None:
    queued = {"status": "review_required", **item}
    observed = review_observation_sha256(queued)
    prior_matches = [
        prior
        for prior in prior_queue or []
        if review_observation_sha256(prior) == observed
    ]
    queued["first_detected_at"] = (
        prior_matches[0].get("first_detected_at")
        or prior_matches[0].get("detected_at")
        if len(prior_matches) == 1
        else queued.get("detected_at")
    )
    queued["detected_at"] = queued["first_detected_at"]
    queued["candidate_id"] = review_item_sha256(queued)
    if matching_terminal_decision(queued, decisions or []) is not None:
        return None
    queue.append(queued)
    return queued


def preserve_detection_times(queue: list[dict], prior_queue: list[dict]) -> None:
    prior_by_candidate = {
        item.get("candidate_id"): item
        for item in prior_queue
        if item.get("candidate_id")
    }
    for item in queue:
        prior = prior_by_candidate.get(item.get("candidate_id"))
        first_detected_at = (
            (prior or {}).get("first_detected_at")
            or (prior or {}).get("detected_at")
            or item.get("detected_at")
        )
        item["first_detected_at"] = first_detected_at
        item["detected_at"] = first_detected_at
        item["candidate_id"] = review_item_sha256(item)


def approved_candidate_filename(
    decisions: list[dict],
    venue_id: str,
    card: str,
    candidates: list[str],
    roster_digest: str | None,
    listing_digest: str,
) -> str | None:
    matches = []
    for decision in decisions:
        candidate = decision.get("candidate") or {}
        if (
            decision.get("decision") == "approved"
            and candidate.get("venue_id") == venue_id
            and candidate.get("card") == card
            and candidate.get("filename") in candidates
            and candidate.get("roster_sha256") == roster_digest
            and candidate.get("listing_sha256") == listing_digest
        ):
            matches.append(candidate["filename"])
    return matches[0] if len(set(matches)) == 1 else None


def superseding_decision(
    decisions: list[dict], asset: dict, venue_id: str | None
) -> dict | None:
    matches = []
    for decision in decisions:
        candidate = decision.get("candidate") or {}
        previous = candidate.get("previous") or {}
        if (
            decision.get("decision") == "approved"
            and venue_id
            and candidate.get("venue_id") == venue_id
            and candidate.get("card") == asset.get("card")
            and candidate.get("roster_sha256") == asset.get("roster_sha256")
            and candidate.get("listing_sha256") == asset.get("listing_sha256")
            and previous.get("filename") == asset.get("filename")
            and previous.get("sha256") == asset.get("sha256")
        ):
            matches.append(decision)
    return matches[0] if len(matches) == 1 else None


def listing_sha256(listings: dict[str, dict[str, dict]]) -> str:
    projection = {
        card: [
            {
                "filename": filename,
                "aem_uuid": entry.get("aem_uuid"),
            }
            for filename, entry in sorted(listing.items())
        ]
        for card, listing in sorted(listings.items())
    }
    canonical = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
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
    return re.sub(r"[-_]?Menu(?:[-_](?:Platinum|Platinium|Centurion))?\.pdf$", "", filename, flags=re.IGNORECASE)


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

    result = {
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
    for key in ("review_manifest_sha256", "reviewed_at"):
        if previous.get(key) is not None:
            result[key] = previous[key]
    return result


def active_menu_after_observation(info: dict, previous: dict | None) -> dict | None:
    previous = previous or {}
    if info.get("status") == "published":
        return info
    if info.get("status") == "review_required" and previous.get("status") == "published":
        return dict(previous)
    return None


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


def retain_review_pdf(pdf_bytes: bytes, root: Path = REVIEW_PDF_ROOT) -> Path:
    if not pdf_bytes.startswith(b"%PDF") or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("menu asset is not a bounded PDF")
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{digest}.pdf"
    if destination.exists():
        if destination.read_bytes() != pdf_bytes:
            raise ValueError("retained menu PDF hash collision")
        return destination
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{digest}.", suffix=".tmp", dir=root
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(pdf_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            if destination.read_bytes() != pdf_bytes:
                raise ValueError("retained menu PDF hash collision")
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return destination


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
        "--review-pdf-root",
        type=Path,
        default=REVIEW_PDF_ROOT,
        help="Content-addressed archive for exact observed menu PDF bytes.",
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

    input_text = input_path.read_text(encoding="utf-8")
    payload = json.loads(input_text)
    venues = payload.get("venues") or []
    if not venues:
        print("No venues in input file.", file=sys.stderr)
        return 1

    checked_at = iso_now()
    listings = {key: fetch_aem_menu_listing(key) for key in AEM_MENU_SOURCES}
    listing_digest = listing_sha256(listings)
    roster_digest = (payload.get("source_images") or {}).get(
        "participating_merchants_sha256"
    )
    prior_review_queue = list(
        (payload.get("menu_source") or {}).get("review_queue") or []
    )
    review_decisions = list((payload.get("menu_source") or {}).get("review_decisions") or [])
    tft_menu_reviews.verify_decision_receipts(payload)
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
        concrete_candidate_queued = False
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
            previous = previous_menus.get(source_key) or {}
            if not previous and source_key == "platinum":
                previous = venue.get("menu_pdf") or {}
            selected = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                ambiguous_assets.update(
                    {(source_key, filename): venue["id"] for filename in candidates}
                )
                preferred = approved_candidate_filename(
                    review_decisions,
                    venue["id"],
                    source_key,
                    candidates,
                    roster_digest,
                    listing_digest,
                )
                if preferred:
                    selected = preferred
                elif previous.get("filename") in candidates:
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
                    pdf_bytes = None
                    observation_failed = True
                    print(f"  ! menu observation failed for {venue['name']}", file=sys.stderr)
            if pdf_bytes is not None and not args.dry_run:
                retain_review_pdf(pdf_bytes, args.review_pdf_root)

            previous = previous_menus.get(source_key) or {}
            if not previous and source_key == "platinum":
                previous = venue.get("menu_pdf") or {}
            info = venue_menu_info(venue, entry, pdf_bytes, checked_at, previous)
            if entry:
                observed_assets.add((source_key, entry["filename"]))
            active_info = active_menu_after_observation(info, previous)
            if active_info is not None:
                source_infos[source_key] = active_info
            if info["status"] == "review_required":
                concrete_candidate_queued = enqueue_review(
                    review_queue,
                    {
                        "kind": "changed_or_new_venue_menu",
                        "venue_id": venue["id"],
                        "venue_name": venue["name"],
                        "card": source_key,
                        "filename": info["filename"],
                        "url": entry["url"],
                        "sha256": info["sha256"],
                        "bytes": info["bytes"],
                        "aem_uuid": info.get("aem_uuid"),
                        "previous_sha256": info.get("previous_sha256"),
                        "previous": (
                            dict(previous)
                            if previous.get("status") == "published"
                            else None
                        ),
                        "roster_sha256": roster_digest,
                        "listing_sha256": listing_digest,
                        "detected_at": checked_at,
                    },
                    review_decisions,
                    prior_review_queue,
                ) is not None or concrete_candidate_queued
            if observation_failed:
                enqueue_review(
                    review_queue,
                    {
                        "kind": "observation_failed",
                        "venue_id": venue["id"],
                        "venue_name": venue["name"],
                        "card": source_key,
                        "filename": entry["filename"],
                        "aem_uuid": entry.get("aem_uuid"),
                        "roster_sha256": roster_digest,
                        "listing_sha256": listing_digest,
                        "detected_at": checked_at,
                    },
                    review_decisions,
                    prior_review_queue,
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
            if not concrete_candidate_queued:
                enqueue_review(
                    review_queue,
                    {
                        "kind": "missing_venue_menu",
                        "venue_id": venue["id"],
                        "venue_name": venue["name"],
                        "roster_sha256": roster_digest,
                        "listing_sha256": listing_digest,
                        "detected_at": checked_at,
                    },
                    review_decisions,
                    prior_review_queue,
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
            candidate_bytes: bytes | None = None
            try:
                candidate_bytes = http_get(entry["url"], MAX_PDF_BYTES)
                if not candidate_bytes.startswith(b"%PDF"):
                    raise ValueError("menu asset is not a PDF")
                asset["sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
                asset["bytes"] = len(candidate_bytes)
            except (urllib.error.URLError, ValueError):
                candidate_bytes = None
                asset["observation_error"] = "bounded_pdf_fetch_failed"
            if candidate_bytes is not None and not args.dry_run:
                retain_review_pdf(candidate_bytes, args.review_pdf_root)
        unmatched_assets.append(asset)
        if candidate_venue_ids:
            if candidate_venue_id:
                candidate_venue = next(
                    venue for venue in venues if venue["id"] == candidate_venue_id
                )
                active = (candidate_venue.get("menu_pdfs") or {}).get(source_key) or {}
                asset["active_filename"] = active.get("filename")
                asset["active_sha256"] = active.get("sha256")
                asset["previous"] = (
                    dict(active) if active.get("status") == "published" else None
                )
            asset["roster_sha256"] = roster_digest
            asset["listing_sha256"] = listing_digest
            queue_item = {"kind": "ambiguous_exact_match", **asset}
            terminal = matching_terminal_decision(queue_item, review_decisions)
            superseded = superseding_decision(
                review_decisions, asset, candidate_venue_id
            )
            if terminal is not None:
                asset["review_status"] = terminal["decision"]
                asset["review_manifest_sha256"] = terminal.get("manifest_sha256")
            elif superseded is not None:
                asset["review_status"] = "superseded"
                asset["review_manifest_sha256"] = superseded.get(
                    "manifest_sha256"
                )
            else:
                enqueue_review(
                    review_queue, queue_item, review_decisions, prior_review_queue
                )
    unmatched = sorted(asset["filename"] for asset in unmatched_assets)
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} PDFs in AEM listing did not match any venue:", file=sys.stderr)
        for f in unmatched:
            print(f"  - {f}", file=sys.stderr)

    preserve_detection_times(review_queue, prior_review_queue)

    payload["menu_source"] = {
        "aem_listing_urls": {key: source["listing_url"] for key, source in AEM_MENU_SOURCES.items()},
        "checked_at": checked_at,
        "listing_sha256": listing_digest,
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
        "review_decisions": review_decisions,
    }

    print(
        f"\nMatched {matched_venue_count}/{len(venues)} venues, {matched_menu_count} menus "
        f"(buffet: {buffet_count}, review: {review_count})",
        file=sys.stderr,
    )

    if args.dry_run:
        print("[dry-run] not writing output file", file=sys.stderr)
        return 0

    with source_change_alert._ledger_lock(output_path):
        if input_path.resolve() == output_path.resolve() and input_path.read_text(
            encoding="utf-8"
        ) != input_text:
            raise RuntimeError("TFT data changed during menu refresh; retry from fresh input")
        source_change_alert._atomic_write_json(output_path, payload)
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
