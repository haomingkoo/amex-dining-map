from scripts.scrape_google_ratings_playwright import oldest_first


def test_oldest_first_puts_missing_then_oldest_ratings_first():
    pairs = [(["q-global"], {"id": "amex-1"}), (["q-japan"], {"id": "pocket-1"}), (["q-new"], {"id": "tft-1"})]
    existing = {
        "amex-1": {"scraped_at": "2026-09-01"},
        "pocket-1": {"scraped_at": "2026-04-10"},
    }

    ordered = oldest_first(pairs, existing)

    assert [record["id"] for _targets, record in ordered] == ["tft-1", "pocket-1", "amex-1"]
