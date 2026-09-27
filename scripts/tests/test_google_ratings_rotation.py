from scripts.scrape_google_ratings_playwright import oldest_first


def test_oldest_first_puts_missing_then_oldest_ratings_first():
    pairs = [("q-global", "amex-1"), ("q-japan", "pocket-1"), ("q-new", "tft-1")]
    existing = {
        "amex-1": {"scraped_at": "2026-09-01"},
        "pocket-1": {"scraped_at": "2026-04-10"},
    }

    ordered = oldest_first(pairs, existing)

    assert [record_id for _query, record_id in ordered] == ["tft-1", "pocket-1", "amex-1"]
