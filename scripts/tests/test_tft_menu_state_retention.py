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


def test_a_rebuild_never_drops_a_field_the_published_roster_carries() -> None:
    """The bug class that cost this repo three separate incidents.

    build_payload rebuilds every venue from scratch, so any field it forgets to
    carry is silently deleted. menu_source went that way, and so did Capitol
    Bistro's officially sourced permanently_closed flag, which vanished on every
    daily refresh and returned on the next availability run.

    Deliberately no exclusion set: build_payload always emits availability,
    booking_project_status, slot_source_status, menu_pdfs and menu_pdf, so a bare
    "no key disappears" assertion is satisfiable today. Excluding
    tft_roster_reviews.RUNTIME_FIELDS would pass while the bug is live, because
    that tuple contains all five operational_status keys.
    """
    existing = json.loads((ROOT / "data/table-for-two.json").read_text())
    by_id = {v["id"]: v for v in existing["venues"]}

    rebuilt = scrape_table_for_two.normalized_venues(
        existing_by_id=by_id,
        roster=[dict(v) for v in existing["venues"]],
        booking_project_source=existing.get("booking_project_source"),
    )

    dropped = {
        record["id"]: sorted(set(by_id[record["id"]]) - set(record))
        for record in rebuilt
        if record["id"] in by_id and set(by_id[record["id"]]) - set(record)
    }
    assert dropped == {}, f"rebuild dropped fields: {dropped}"


def test_a_rebuild_keeps_an_officially_sourced_operational_status() -> None:
    """No live venue carries operational_status, so the check above cannot see it drop."""
    existing = json.loads((ROOT / "data/table-for-two.json").read_text())
    by_id = {v["id"]: dict(v) for v in existing["venues"]}
    venue_id = existing["venues"][0]["id"]
    by_id[venue_id]["operational_status"] = "permanently_closed"
    by_id[venue_id]["operational_status_source"] = "official"

    rebuilt = scrape_table_for_two.normalized_venues(
        existing_by_id=by_id,
        roster=[dict(v) for v in existing["venues"]],
        booking_project_source=existing.get("booking_project_source"),
    )

    record = {r["id"]: r for r in rebuilt}[venue_id]
    assert record.get("operational_status") == "permanently_closed"
    assert record.get("operational_status_source") == "official"
