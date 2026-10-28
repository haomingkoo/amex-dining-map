from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts import dispatch_owner_updates

ROOT = Path(__file__).resolve().parents[2]
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def test_published_data_has_no_unaccounted_japanese_prefectures_or_cuisines():
    records = json.loads((ROOT / "data" / "japan-restaurants.json").read_text())
    meta = json.loads((ROOT / "data" / "japan-dining-source.json").read_text())
    localized = [
        record["id"]
        for record in records
        if JAPANESE.search(record.get("prefecture") or "")
        or any(JAPANESE.search(cuisine) for cuisine in record.get("cuisines") or [])
    ]

    assert len(localized) <= int(meta.get("locale_unretained_count") or 0), localized


def test_japanese_script_names_are_bilingual_english_records():
    records = json.loads((ROOT / "data" / "japan-restaurants.json").read_text())
    named = {record["id"]: record for record in records if JAPANESE.search(record.get("name") or "")}

    for venue_id, record in named.items():
        assert record.get("prefecture") and not JAPANESE.search(record["prefecture"]), venue_id
        assert record.get("cuisines") and not any(JAPANESE.search(cuisine) for cuisine in record["cuisines"]), venue_id
    if any(record["id"] == "pocket-245510" for record in records):
        assert "pocket-245510" in named


def test_locale_glitch_events_are_retracted_and_never_dispatched(tmp_path: Path):
    events = json.loads((ROOT / "data" / "updates.json").read_text())["updates"]
    glitch = [
        event
        for event in events
        if event.get("program") == "Japan Dining"
        and event.get("kind") == "details_updated"
        and str(event.get("detected_at", "")).startswith("2026-10-28T00:15")
    ]

    assert len(glitch) == 100
    assert {event["status"] for event in glitch} == {"retracted"}
    assert all(event.get("retracted_at") and event.get("retraction_note") for event in glitch)
    # Drop delivery receipts so only the retraction can keep them from the owner.
    undelivered = tmp_path / "updates.json"
    undelivered.write_text(
        json.dumps({"updates": [{k: v for k, v in event.items() if not k.startswith("owner_delivery")} for event in glitch]})
    )
    assert dispatch_owner_updates.published_events(undelivered, days=36500, now=datetime.now(timezone.utc)) == []
