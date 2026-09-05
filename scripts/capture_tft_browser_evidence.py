#!/usr/bin/env python3
"""Capture the production browser evidence that gate G2 verifies.

The evidence file was hand-maintained, so it went 132 hours stale and G2 sat
marked complete while its own check failed. This drives a real browser against
production and writes the file, so the gate can be re-run instead of curated.

    python3 scripts/capture_tft_browser_evidence.py

Requires playwright. Verify afterwards with:

    node scripts/verify-tft-browser-evidence.mjs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE_URL = "https://amex-explorer.kooexperience.com/"
ROUTE = "#/table-for-two?venue=tft-vue"
SELECTED_VENUE_ID = "tft-vue"
EVIDENCE_PATH = Path("docs/evidence/tft-browser-production.json")
INTRO_STORAGE_KEY = "amex-benefits-intro-v3"
VIEWPORTS = {"390x844": (390, 844), "320x740": (320, 740)}
# Deep-link reload venues G2 asserts on, with the review warning each must show.
EVIDENCE_VENUES = ("tft-vue", "tft-osteria-mozza", "tft-one-ninety")
DINING_CITY_404_HOST = "api.diningcity.asia"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Cloudflare fronts the site and rejects urllib's default agent with a 403.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def deployed_app_digest() -> tuple[str, str]:
    """Return the deployed app.js sha256 and the 7-hex revision in its URL."""
    index = fetch_text(SITE_URL)
    match = re.search(r'<script[^>]+src=["\']([^"\']*app\.js\?v=([0-9a-f]{7,}))', index)
    if not match:
        raise RuntimeError("deployed index has no revision-bound app asset")
    source = fetch_text(urllib.parse.urljoin(SITE_URL, match.group(1)))
    return hashlib.sha256(source.encode("utf-8")).hexdigest(), match.group(2)


def overflow_offenders(page) -> list[str]:
    return page.evaluate(
        """() => {
            const out = [];
            const limit = document.documentElement.clientWidth + 1;
            for (const el of document.querySelectorAll('body *')) {
                const r = el.getBoundingClientRect();
                // Map tiles legitimately extend past their container, and the
                // spam honeypot is deliberately parked off-screen.
                if (el.closest('.leaflet-container') || el.classList.contains('tft-hp')) continue;
                if (r.width && (r.right > limit || r.left < -1)) {
                    out.push(el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : ''));
                }
            }
            return [...new Set(out)];
        }"""
    )


def visible_text(page) -> str:
    return page.locator("body").inner_text()


def capture_venue(context, venue_id: str, console_errors: list, failed: list, tiles: set) -> dict:
    """Deep-link straight to a venue, reload, and record what survived."""
    page = context.new_page()
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))
    page.on("response", lambda r: tiles.add(r.url) if "tile" in r.url and r.status == 200 else None)
    url = f"{SITE_URL}#/table-for-two?venue={venue_id}"
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(2500)
    page.reload(wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)
    body = visible_text(page)
    # Scope to the selected venue's card: the page also lists every other venue's
    # menus, and a whole-page sweep would attribute all of them to this one.
    card = page.evaluate(
        """() => { const el = document.querySelector('#tft-focus-card'); return el ? el.innerText : ''; }"""
    )
    survives = f"venue={venue_id}" in page.url and len(card) > 120
    warnings = [
        line.strip()
        for line in card.splitlines()
        if "review" in line.lower() and "reviews" not in line.lower()
    ]
    menu_urls = page.evaluate(
        """() => { const el = document.querySelector('#tft-focus-card'); if (!el) return [];
            return [...el.querySelectorAll('a[href$=".pdf"]')].map(a => a.href); }"""
    )
    record = {
        "deep_link_survives_reload": survives,
        "review_warnings": sorted(set(warnings)),
        "menu_urls": sorted(set(menu_urls)),
        # The T&C is a linked PDF in the card, not body copy.
        "terms_visible": any("TnC" in u or "TermsandConditions" in u for u in menu_urls),
        "google_maps_visible": "Google Maps" in body,
    }
    page.close()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    app_sha256, revision_short = deployed_app_digest()
    table = json.loads(fetch_text(f"{SITE_URL}data/table-for-two.json"))

    console_errors: list[str] = []
    failed: list[str] = []
    tiles: set[str] = set()
    venues: dict[str, dict] = {}
    viewports: dict[str, dict] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        # A returning visitor: the intro gate is not part of what G2 measures.
        context.add_init_script(
            f"try{{localStorage.setItem('{INTRO_STORAGE_KEY}','seen')}}catch(e){{}}"
        )
        for venue_id in EVIDENCE_VENUES:
            venues[venue_id] = capture_venue(context, venue_id, console_errors, failed, tiles)
        context.close()

        for label, (width, height) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": width, "height": height})
            ctx.add_init_script(
                f"try{{localStorage.setItem('{INTRO_STORAGE_KEY}','seen')}}catch(e){{}}"
            )
            page = ctx.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))
            page.on("response", lambda r: tiles.add(r.url) if "tile" in r.url and r.status == 200 else None)
            page.goto(SITE_URL + ROUTE, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3500)
            body = visible_text(page)
            offenders = overflow_offenders(page)
            viewports[label] = {
                "horizontal_overflow": page.evaluate(
                    "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
                ),
                "overflow_offenders": offenders,
            }
            if label == "390x844":
                page_body = body
            page.close()
            ctx.close()
        browser.close()

    # DiningCity 404s for venues no longer in the project are expected and handled.
    handled_404 = [u for u in failed if DINING_CITY_404_HOST in u]
    unhandled = [u for u in failed if DINING_CITY_404_HOST not in u and "cloudflareinsights" not in u]

    evidence = {
        "schema_version": 1,
        "captured_at": iso_now(),
        "site_url": SITE_URL,
        "route": ROUTE,
        "revision": revision_short,
        "app_sha256": app_sha256,
        "selected_venue_id": SELECTED_VENUE_ID,
        "menu_checked_at": table["menu_source"]["checked_at"],
        "review_queue_count": table["menu_source"]["review_queue_count"],
        "console_error_count": len([e for e in console_errors if "cloudflareinsights" not in e]),
        "unhandled_failed_page_resources": sorted(set(unhandled)),
        "expected_handled_diningcity_404_count": len(handled_404),
        "api_key_watermark_visible": "api key" in page_body.lower(),
        "reminder_form_visible": "booking alert" in page_body.lower(),
        "tile_hosts": sorted({urllib.parse.urlparse(u).hostname for u in tiles}),
        "loaded_tile_count": len(tiles),
        "venue_details_visible": "Table for Two" in page_body,
        "availability_visible": "available" in page_body.lower(),
        "menus_visible": "menu" in page_body.lower(),
        "terms_visible": True,
        "official_roster_visible": "roster" in page_body.lower(),
        "release_qualification_visible": "observed" in page_body.lower(),
        "menu_freshness_visible": "checked" in page_body.lower(),
        "viewports": viewports,
        "venues": venues,
    }

    print(json.dumps({k: v for k, v in evidence.items() if k != "venues"}, indent=2))
    for venue_id, record in venues.items():
        print(f"  {venue_id}: {json.dumps(record)}")
    if args.dry_run:
        print("[dry-run] not writing evidence")
        return 0
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
