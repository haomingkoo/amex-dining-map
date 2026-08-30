from __future__ import annotations

import json
from pathlib import Path

from scripts import scrape_table_for_two, tft_document_reviews


ROOT = Path(__file__).resolve().parents[2]


def test_later_observation_does_not_replace_prior_exact_pdf(monkeypatch, tmp_path):
    existing = json.loads((ROOT / "data/table-for-two.json").read_text())
    terms_b = b"%PDF-1.4\nobserved version B\n%%EOF\n"
    terms_c = b"%PDF-1.4\nobserved version C\n%%EOF\n"
    faq = b"%PDF-1.4\nstable FAQ\n%%EOF\n"
    participating = b"participating"
    cycles = b"cycles"
    current_terms = terms_b

    def fetch(url: str) -> bytes:
        if url == scrape_table_for_two.OFFICIAL_URL:
            return b"official page"
        if url == scrape_table_for_two.TERMS_URL:
            return current_terms
        if url == scrape_table_for_two.FAQ_URL:
            return faq
        if url == "https://example.test/participating.png":
            return participating
        if url == "https://example.test/cycles.png":
            return cycles
        raise AssertionError(f"unexpected URL: {url}")

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
        scrape_table_for_two,
        "fetch_live_availability",
        lambda *_args: ({}, {}),
    )
    monkeypatch.setattr(
        scrape_table_for_two,
        "fetch_diningcity_profiles",
        lambda *_args: ({}, {}),
    )

    first = scrape_table_for_two.build_payload(existing, tmp_path)
    hash_b = first["source_documents"]["terms_sha256"]
    assert tft_document_reviews.pdf_path("tft-terms", hash_b, tmp_path).read_bytes() == terms_b

    current_terms = terms_c
    second = scrape_table_for_two.build_payload(first, tmp_path)
    hash_c = second["source_documents"]["terms_sha256"]

    assert hash_c != hash_b
    assert tft_document_reviews.pdf_path("tft-terms", hash_b, tmp_path).read_bytes() == terms_b
    assert tft_document_reviews.pdf_path("tft-terms", hash_c, tmp_path).read_bytes() == terms_c
