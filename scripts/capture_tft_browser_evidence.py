#!/usr/bin/env python3
"""Capture the production browser evidence that gate G2 verifies.

The evidence file was hand-maintained, so it went stale and recorded claims no
browser ever measured. This drives a real browser against production and writes
the file, so the gate can be re-run instead of curated.

    python3 scripts/capture_tft_browser_evidence.py

Every venue in the deployed roster is visited, because G2's missing-menu rule
has to hold for every venue that publishes no menu rather than for a sample.
This records what the page did; scripts/verify-tft-browser-evidence.mjs decides
whether that is acceptable.

Requires playwright. Verify afterwards with:

    node scripts/verify-tft-browser-evidence.mjs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SITE_URL = "https://amex-explorer.kooexperience.com/"
ROUTE = "#/table-for-two?venue=tft-vue"
SELECTED_VENUE_ID = "tft-vue"
EVIDENCE_PATH = Path("docs/evidence/tft-browser-production.json")
INTRO_STORAGE_KEY = "amex-benefits-intro-v3"
VIEWPORTS = {"390x844": (390, 844), "320x740": (320, 740)}
CARD_RENDER_TIMEOUT_MS = 30000


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


def fetch_table() -> dict:
    return json.loads(fetch_text(f"{SITE_URL}data/table-for-two.json"))


def display_name(record: dict) -> str:
    return str(record.get("app_name") or record.get("name") or "").strip()


def browser_cancelled(entry: str) -> bool:
    """Was this request cancelled by the browser rather than failed by a server?

    The capture reloads every page, and each reload cancels whatever the first
    load still had in flight; Leaflet also cancels tiles whenever the map view
    moves. Both report net::ERR_ABORTED. Nothing served those badly, and
    treating them as failures reddens the gate on run-to-run timing alone.

    A resource that genuinely does not load is still caught: it reports a
    transport or CSP error rather than ERR_ABORTED, and a missing app bundle or
    payload leaves the focus card unrendered, which fails
    deep_link_survives_reload and the deployed app.js digest check.
    """
    return "net::ERR_ABORTED" in entry


def attach_sinks(page, sinks: dict) -> None:
    """Record console errors, failed requests, and served tiles for one page."""
    page.on("console", lambda m: sinks["console_errors"].append(m.text) if m.type == "error" else None)
    page.on("requestfailed", lambda r: sinks["failed"].append(f"{r.url} {r.failure}"))
    page.on("response", lambda r: sinks["tiles"].add(r.url) if "tile" in r.url and r.status == 200 else None)


def settle(page) -> None:
    """Wait for the page to stop fetching, so late failures still get recorded."""
    try:
        page.wait_for_load_state("networkidle", timeout=CARD_RENDER_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass


def card_rendered(page, title: str) -> bool:
    """Wait until the focus card shows this venue instead of the placeholder."""
    try:
        page.wait_for_function(
            """(title) => {
                const el = document.querySelector('#tft-focus-card .focus-title');
                return !!el && el.innerText.trim() === title;
            }""",
            arg=title,
            timeout=CARD_RENDER_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        return False
    return True


def overflow_offenders(page) -> list[str]:
    return page.evaluate(
        """() => {
            const out = [];
            const limit = document.documentElement.clientWidth + 1;
            // Content parked inside its own horizontal scroller is reachable by
            // scrolling that strip, so the viewport is not clipping it. The
            // primary nav is one: measured at 390px its box ends at 374 of a 391
            // limit while its links run to 600, and it scrolls 584 within 358.
            // Only auto/scroll ancestors excuse a child; a clip or hidden
            // ancestor really does hide what runs past it.
            const inOwnScroller = (el) => {
                for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
                    const overflowX = getComputedStyle(p).overflowX;
                    if (overflowX !== 'auto' && overflowX !== 'scroll') continue;
                    const box = p.getBoundingClientRect();
                    if (box.right <= limit && box.left >= -1) return true;
                }
                return false;
            };
            for (const el of document.querySelectorAll('body *')) {
                const r = el.getBoundingClientRect();
                // Map tiles legitimately extend past their container, and the
                // spam honeypot is deliberately parked off-screen.
                if (el.closest('.leaflet-container') || el.classList.contains('tft-hp')) continue;
                if (r.width && (r.right > limit || r.left < -1) && !inOwnScroller(el)) {
                    out.push(el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : ''));
                }
            }
            return [...new Set(out)];
        }"""
    )


def visible_text(page) -> str:
    return page.locator("body").inner_text()


def read_card(page) -> dict:
    return page.evaluate(
        """() => {
            const el = document.querySelector('#tft-focus-card');
            if (!el) return { notes: [], pdfs: [], links: [] };
            return {
                notes: [...el.querySelectorAll('.focus-note')].map((n) => n.innerText.trim()).filter(Boolean),
                pdfs: [...el.querySelectorAll('a[href$=".pdf"]')].map((a) => a.href),
                links: [...el.querySelectorAll('a[href]')].map((a) => a.href),
            };
        }"""
    )


def capture_venue(context, record: dict, program_pdfs: set[str], sinks: dict) -> dict:
    """Deep-link straight to a venue, reload, and record what the card showed."""
    venue_id = record["id"]
    title = display_name(record)
    page = context.new_page()
    attach_sinks(page, sinks)
    page.goto(f"{SITE_URL}#/table-for-two?venue={venue_id}", wait_until="domcontentloaded", timeout=90000)
    card_rendered(page, title)
    page.reload(wait_until="domcontentloaded", timeout=90000)
    survives = card_rendered(page, title)
    if not survives:
        # One slow production response is not a broken deep link. A card that
        # never comes back is, and stays recorded as false for the gate to fail on.
        page.reload(wait_until="domcontentloaded", timeout=90000)
        survives = card_rendered(page, title)
    settle(page)
    card = read_card(page)
    body = visible_text(page)
    on_route = f"venue={venue_id}" in page.url
    page.close()
    return {
        "deep_link_survives_reload": survives and on_route,
        # Raw note copy, not a verdict. The verifier asserts that a venue with no
        # published menu says something; it does not pin the wording, because a
        # pinned wording is what left G2 red for five days after a routine edit.
        "card_notes": sorted(set(card["notes"])),
        # The program-wide T&Cs and FAQ are linked from every card and are not
        # this venue's menu.
        "card_menu_pdf_urls": sorted({url for url in card["pdfs"] if url.rstrip("?") not in program_pdfs}),
        "google_maps_visible": "Google Maps" in body,
    }


def capture_viewport(browser, size: tuple[int, int], title: str, sinks: dict) -> tuple[dict, dict]:
    """Load the deep-linked route at one viewport and report layout plus card."""
    context = browser.new_context(viewport={"width": size[0], "height": size[1]})
    context.add_init_script(f"try{{localStorage.setItem('{INTRO_STORAGE_KEY}','seen')}}catch(e){{}}")
    page = context.new_page()
    attach_sinks(page, sinks)
    page.goto(SITE_URL + ROUTE, wait_until="domcontentloaded", timeout=90000)
    if not card_rendered(page, title):
        raise RuntimeError(f"{size[0]}x{size[1]} never rendered the {SELECTED_VENUE_ID} card")
    # Tiles and lazy panels settle after the card; layout is measured once they have.
    settle(page)
    page.wait_for_timeout(1500)
    layout = {
        "horizontal_overflow": page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
        ),
        "overflow_offenders": overflow_offenders(page),
    }
    seen = {"body": visible_text(page), "links": read_card(page)["links"]}
    page.close()
    context.close()
    return layout, seen


def production_moved(table: dict, app_sha256: str) -> bool:
    """Did the deployment or the payload change while the browser was walking it?

    A refresh partway through a 30-venue walk leaves the cards and the payload
    fields describing different snapshots, and the gate reads that disagreement
    as a fault. Recapture instead of writing evidence that contradicts itself.
    """
    current_sha256, _ = deployed_app_digest()
    if current_sha256 != app_sha256:
        return True
    current = fetch_table()
    if current["menu_source"]["checked_at"] != table["menu_source"]["checked_at"]:
        return True
    return [v["id"] for v in current["venues"]] != [v["id"] for v in table["venues"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    app_sha256, revision_short = deployed_app_digest()
    table = fetch_table()
    selected = next((v for v in table["venues"] if v["id"] == SELECTED_VENUE_ID), None)
    if selected is None:
        raise RuntimeError(f"deployed roster no longer contains {SELECTED_VENUE_ID}")
    program_pdfs = {str(url).rstrip("?") for url in (table.get("terms_url"), table.get("faq_url")) if url}

    sinks: dict = {"console_errors": [], "failed": [], "tiles": set()}
    venues: dict[str, dict] = {}
    viewports: dict[str, dict] = {}
    seen: dict = {"body": "", "links": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        # A returning visitor: the intro gate is not part of what G2 measures.
        context.add_init_script(
            f"try{{localStorage.setItem('{INTRO_STORAGE_KEY}','seen')}}catch(e){{}}"
        )
        for record in table["venues"]:
            venues[record["id"]] = capture_venue(context, record, program_pdfs, sinks)
        context.close()

        for label, size in VIEWPORTS.items():
            viewports[label], measured = capture_viewport(browser, size, display_name(selected), sinks)
            if label == "390x844":
                seen = measured
        browser.close()

    if production_moved(table, app_sha256):
        print("production changed during capture; re-run before verifying", file=sys.stderr)
        return 1

    tile_hosts = sorted({urllib.parse.urlparse(u).hostname for u in sinks["tiles"]})
    unhandled = sorted({
        entry
        for entry in sinks["failed"]
        if "cloudflareinsights" not in entry and not browser_cancelled(entry)
    })
    card_links = {link.rstrip("?") for link in seen["links"]}

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
        "console_error_count": len([e for e in sinks["console_errors"] if "cloudflareinsights" not in e]),
        "unhandled_failed_page_resources": unhandled,
        "api_key_watermark_visible": "api key" in seen["body"].lower(),
        "reminder_form_visible": "booking alert" in seen["body"].lower(),
        "tile_hosts": tile_hosts,
        "loaded_tile_count": len(sinks["tiles"]),
        "venue_details_visible": "Table for Two" in seen["body"],
        "availability_visible": "available" in seen["body"].lower(),
        "menus_visible": "menu" in seen["body"].lower(),
        # Link identity, not body copy: the old "roster" word sniff flipped between
        # runs because the word only appears while the card is fully painted.
        "terms_pdf_linked": str(table.get("terms_url", "")).rstrip("?") in card_links,
        "official_roster_linked": str(table.get("official_url", "")).rstrip("?") in card_links,
        "release_qualification_visible": "observed" in seen["body"].lower(),
        "menu_freshness_visible": "checked" in seen["body"].lower(),
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
