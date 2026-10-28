from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from scripts import source_change_alert, sync_japan_mvp  # noqa: E402
import source_health  # noqa: E402

FIXTURE = json.loads((SCRIPTS / "tests" / "fixtures" / "japan_locale_glitch.json").read_text())
VENUES = {item["id"]: item for item in FIXTURE["venues"]}
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
HAKONE = "pocket-245429"
REPRICED = "pocket-244189"
HIRAMATSU = "pocket-245510"
LOCALE_IDS = [venue_id for venue_id in VENUES if venue_id != HIRAMATSU]
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("network access in a unit test")

    monkeypatch.setattr(sync_japan_mvp, "post_json", refuse)
    monkeypatch.setattr(sync_japan_mvp, "geocode_query", refuse)
    monkeypatch.setattr(sync_japan_mvp.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(sync_japan_mvp, "validate_source_coordinates", lambda *_args: None)


def search_record(venue_id: str) -> dict:
    item = VENUES[venue_id]
    return sync_japan_mvp.build_record_from_search_result(copy.deepcopy(item["search_result"]), item["area_name"])


def previous_by_id(*venue_ids: str) -> dict:
    return {venue_id: copy.deepcopy(VENUES[venue_id]["previous"]) for venue_id in venue_ids}


def refresh(venue_ids: list[str], previous: dict) -> tuple[list[dict], tuple[int, int]]:
    records = [search_record(venue_id) for venue_id in venue_ids]
    counts = sync_japan_mvp.retain_english_details(records, previous)
    detail_cache = {
        venue_id.replace("pocket-", "", 1): copy.deepcopy(VENUES[venue_id]["detail"]) for venue_id in venue_ids
    }
    for record in records:
        sync_japan_mvp.enrich_from_source(record, detail_cache, {})
        record["external_signals"] = copy.deepcopy(previous.get(record["id"], {}).get("external_signals", {}))
        record["search_text"] = sync_japan_mvp.build_search_text(record)
    return records, counts


def test_localized_venue_keeps_previous_english_details_and_new_prices():
    previous = previous_by_id(REPRICED, HAKONE)
    records, counts = refresh([REPRICED, HAKONE], previous)
    by_id = {record["id"]: record for record in records}

    assert counts == (2, 0)
    for venue_id, record in by_id.items():
        before = previous[venue_id]
        for field in ("name", "cuisines", "summary_official", "source_search_town", "prefecture", "city", "district"):
            assert record[field] == before[field], (venue_id, field)
        assert record["source_google_map_url"] == before["source_google_map_url"]
        assert record["signature_dish_tags"] == before["signature_dish_tags"]
        assert not JAPANESE.search(record["search_text"]), venue_id
    glitched = VENUES[REPRICED]["search_result"]["priceRanges"]
    dinner = next(item for item in glitched if item["serviceType"] == "DINNER")
    assert by_id[REPRICED]["price_dinner_min_jpy"] == dinner["min"]
    assert by_id[REPRICED]["price_dinner_min_jpy"] != previous[REPRICED]["price_dinner_min_jpy"]
    assert by_id[HAKONE]["city"] == "Hakone"


def test_localized_venue_without_previous_is_kept_and_counted(capsys):
    records = [search_record(HAKONE)]

    counts = sync_japan_mvp.retain_english_details(records, {})

    assert counts == (0, 1)
    assert records[0]["name"] == VENUES[HAKONE]["search_result"]["name"]
    assert "::warning" in capsys.readouterr().out


def test_previous_record_that_is_also_localized_is_not_reused():
    previous = previous_by_id(HAKONE)
    previous[HAKONE]["prefecture"] = "神奈川県"
    previous[HAKONE]["name"] = "箱根本箱"
    records = [search_record(HAKONE)]

    assert sync_japan_mvp.retain_english_details(records, previous) == (0, 1)
    assert records[0]["name"] == VENUES[HAKONE]["search_result"]["name"]


def test_bilingual_name_with_english_prefecture_is_untouched(capsys):
    previous = previous_by_id(HIRAMATSU)
    previous[HIRAMATSU]["name"] = "Old English name"
    records = [search_record(HIRAMATSU)]

    assert sync_japan_mvp.retain_english_details(records, previous) == (0, 0)
    assert records[0]["name"] == "Sushi Hiramatsu（寿し ひらまつ）"
    assert "::warning" not in capsys.readouterr().out


def test_locale_counts_are_recorded_in_meta_without_update_events():
    records = [copy.deepcopy(VENUES[HIRAMATSU]["previous"])]
    old_meta = sync_japan_mvp.build_source_meta(records, "2026-10-27T00:00:00+00:00")
    new_meta = sync_japan_mvp.build_source_meta(
        records, "2026-10-28T00:00:00+00:00", locale_retained_count=100, locale_unretained_count=2
    )

    assert new_meta["locale_retained_count"] == 100
    assert new_meta["locale_unretained_count"] == 2
    assert old_meta["locale_retained_count"] == 0
    for key in ("locale_retained_count", "locale_unretained_count"):
        assert key not in source_change_alert.META_FIELD_LABELS
    assert source_change_alert.build_meta_update_event("Japan Dining", old_meta, new_meta, "2026-10-28T00:15:00Z") is None


def write_health_fixture(root: Path, japan_meta: dict) -> None:
    current = (NOW - timedelta(hours=1)).isoformat()
    payloads = {
        "global-dining-source.json": {"fetched_at": current, "record_count": 1},
        "japan-dining-source.json": {"fetched_at": current, "record_count": 1, **japan_meta},
        "plat-stay-source.json": {"fetched_at": current, "record_count": 1},
        "love-dining-source.json": {"last_checked_at": current, "record_count": 1},
        "japan-restaurants.json": [{"id": "pocket-1"}],
        "table-for-two.json": {"last_verified_at": current, "venues": []},
    }
    for name, payload in payloads.items():
        (root / name).write_text(json.dumps(payload), encoding="utf-8")


def japan_health(root: Path, japan_meta: dict) -> dict:
    write_health_fixture(root, japan_meta)
    payload = source_health.build_source_health(root, NOW)
    return payload, next(item for item in payload["sources"] if item["id"] == "japan-dining")


def test_source_health_surfaces_locale_retention(tmp_path: Path):
    _, clean = japan_health(tmp_path, {"locale_retained_count": 0, "locale_unretained_count": 0})
    old_payload, _ = japan_health(tmp_path, {})
    new_payload, flagged = japan_health(tmp_path, {"locale_retained_count": 100, "locale_unretained_count": 2})

    assert clean["detail"] is None
    assert flagged["detail"] == (
        "100 venue(s) returned in Japanese; kept previous English details. "
        "2 new venue(s) returned in Japanese with no English record to keep."
    )
    assert source_health.build_transition_events(old_payload, new_payload, NOW.isoformat()) == []


def test_replay_of_glitch_emits_no_locale_update_events():
    previous = previous_by_id(*VENUES)
    records, counts = refresh(list(VENUES), previous)

    assert counts == (len(LOCALE_IDS), 0)
    events = source_change_alert.build_record_update_events(
        "Japan Dining", list(previous.values()), records, {}, "2026-10-28T00:15:15Z"
    )
    assert [event for event in events if event["kind"] == "details_updated"] == []


def test_replay_without_guard_reproduces_the_bogus_events():
    previous = previous_by_id(*VENUES)
    records, _ = refresh(list(VENUES), {})

    events = source_change_alert.build_record_update_events(
        "Japan Dining", list(previous.values()), records, {}, "2026-10-28T00:15:15Z"
    )
    assert sorted(event["subject"].split(" / ")[0] for event in events) == sorted(
        VENUES[venue_id]["search_result"]["name"] for venue_id in LOCALE_IDS
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (" ", None),
        (" https://www.cusavilla.com", "https://www.cusavilla.com"),
        ("https://m.facebook.com/kappou.ichika/ ", "https://m.facebook.com/kappou.ichika/"),
        ("http://example.jp/", "http://example.jp/"),
        ("kunn.jp/cunn/index.html", "https://kunn.jp/cunn/index.html"),
        ("//www.example.jp/menu", "https://www.example.jp/menu"),
        ("javascript:alert(1)", None),
        ("mailto:owner@example.jp", None),
        ("ftp://example.jp/file", None),
        ("not a website", None),
    ],
)
def test_website_url_normalization(raw, expected):
    assert sync_japan_mvp.normalize_website_url(raw) == expected


def test_enrichment_stores_normalized_website_url():
    record = search_record(HIRAMATSU)
    detail = copy.deepcopy(VENUES[HIRAMATSU]["detail"])
    detail["websiteUrl"] = "kunn.jp/cunn/index.html"

    sync_japan_mvp.enrich_from_source(record, {HIRAMATSU.replace("pocket-", "", 1): detail}, {})

    assert record["website_url"] == "https://kunn.jp/cunn/index.html"
