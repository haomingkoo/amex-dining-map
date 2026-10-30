from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error

from scripts import fetch_tft_menus


PDF = b"%PDF-1.4\nforage menu\n%%EOF\n"
BASE = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining"
LISTED = "Forage-Menu_Platinium.pdf"
WORKING = "Forage-Menu_Platinum.pdf"


def _run(tmp_path, monkeypatch, previous_filename):
    data = tmp_path / "tft.json"
    data.write_text(json.dumps({
        "venues": [{
            "id": "tft-forage", "name": "Forage", "category": "restaurant",
            "menu_pdfs": {"platinum": {
                "status": "published", "url": f"{BASE}/{previous_filename}",
                "filename": previous_filename, "card": "platinum", "label": "Platinum",
                "sha256": hashlib.sha256(PDF).hexdigest(), "bytes": len(PDF),
                "checked_at": "2026-09-01T00:00:00Z",
                "first_seen_at": "2026-09-01T00:00:00Z", "last_seen_at": "2026-09-01T00:00:00Z",
            }},
        }],
        "menu_source": {},
    }))

    def listing(key):
        if key != "platinum":
            return {}
        return {LISTED: {
            "card_key": "platinum", "card_label": "Platinum", "filename": LISTED,
            "url": f"{BASE}/{LISTED}", "aem_created": None, "aem_uuid": "listed-uuid",
        }}

    def http_get(url, max_bytes):
        if url == f"{BASE}/{WORKING}":
            return PDF
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())

    monkeypatch.setattr(fetch_tft_menus, "fetch_aem_menu_listing", listing)
    monkeypatch.setattr(fetch_tft_menus, "http_get", http_get)
    monkeypatch.setattr(sys, "argv", [
        "fetch_tft_menus.py", "--input", str(data), "--output", str(data),
        "--cache-dir", "", "--review-pdf-root", str(tmp_path / "pdfs"),
    ])
    assert fetch_tft_menus.main() == 0
    return json.loads(data.read_text())


def test_dead_listed_link_queues_the_working_spelling_for_review(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, LISTED)

    source = out["menu_source"]
    [item] = [i for i in source["review_queue"] if i["kind"] == "changed_or_new_venue_menu"]
    assert item["filename"] == WORKING
    assert item["url"] == f"{BASE}/{WORKING}"
    assert not any(i["kind"] == "observation_failed" for i in source["review_queue"])
    # The listed asset is accounted for, so it is not reported as an unknown PDF.
    assert LISTED not in source["unmatched_pdfs"]
    # The reviewed menu stays live until someone approves the new link.
    assert out["venues"][0]["menu_pdfs"]["platinum"]["filename"] == LISTED


def test_approved_working_spelling_stays_published_without_review(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, WORKING)

    menu = out["venues"][0]["menu_pdfs"]["platinum"]
    assert menu["status"] == "published"
    assert menu["url"] == f"{BASE}/{WORKING}"
    assert out["menu_source"]["review_queue"] == []
