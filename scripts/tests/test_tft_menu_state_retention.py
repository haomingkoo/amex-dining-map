from __future__ import annotations

import json
from pathlib import Path

from scripts import scrape_table_for_two


ROOT = Path(__file__).resolve().parents[2]


def test_roster_refresh_keeps_menu_review_state(monkeypatch, tmp_path) -> None:
    existing = json.loads((ROOT / "data/table-for-two.json").read_text())
    existing["menu_source"] = {"review_decisions": [{"candidate_id": "a" * 64}]}

    def fetch(url: str) -> bytes:
        if url == scrape_table_for_two.OFFICIAL_URL:
            return b"official page"
        if url in (scrape_table_for_two.TERMS_URL, scrape_table_for_two.FAQ_URL):
            return b"%PDF-1.4\nstable document\n%%EOF\n"
        return b"image"

    monkeypatch.setattr(scrape_table_for_two, "fetch_bytes", fetch)
    monkeypatch.setattr(
        scrape_table_for_two,
        "extract_image_url",
        lambda _html, alt: (
            "https://example.test/participating.png"
            if alt == "Participating Merchants"
            else "https://example.test/cycles.png"
        ),
    )
    monkeypatch.setattr(
        scrape_table_for_two.tft_roster_reviews,
        "review_state",
        lambda *_args: ([], {"review_required": False}),
    )
    monkeypatch.setattr(
        scrape_table_for_two, "fetch_live_availability", lambda *_args: ({}, {})
    )
    monkeypatch.setattr(
        scrape_table_for_two, "fetch_diningcity_profiles", lambda *_args: ({}, {})
    )

    refreshed = scrape_table_for_two.build_payload(existing, tmp_path)

    assert refreshed["menu_source"] == existing["menu_source"]
