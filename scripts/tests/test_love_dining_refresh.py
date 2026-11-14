from __future__ import annotations

import hashlib
import io
import json
import sys
import types
import urllib.error

import pytest

from scripts import scrape_love_dining as MODULE


@pytest.fixture
def paths(tmp_path, monkeypatch):
    output = tmp_path / "love-dining.json"
    meta = tmp_path / "love-dining-source.json"
    cache = tmp_path / "geocode-cache.json"
    monkeypatch.setattr(MODULE, "OUTPUT_PATH", output)
    monkeypatch.setattr(MODULE, "META_PATH", meta)
    monkeypatch.setattr(MODULE, "GEOCODE_CACHE_PATH", cache)
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)
    return types.SimpleNamespace(output=output, meta=meta, cache=cache)


def test_inline_text_collapses_whitespace_and_non_breaking_spaces():
    assert MODULE.normalize_inline_text("  a\xa0\n b\t c ") == "a b c"
    assert MODULE.normalize_inline_text(None) == ""


def test_phone_count_counts_slash_separated_numbers():
    assert MODULE.phone_count("6111 1111 / 6222 2222/6333 3333") == 3
    assert MODULE.phone_count("6111 1111") == 1
    assert MODULE.phone_count(" / ") == 0
    assert MODULE.phone_count(None) == 0


def test_address_block_count_takes_the_larger_of_postcodes_and_streets():
    assert MODULE.address_block_count("1 Raffles Place, Singapore 048616") == 1
    assert MODULE.address_block_count("Singapore 048616 and Singapore 238879") == 2
    assert MODULE.address_block_count("10 Bayfront Avenue; 2 orchard turn") == 2
    assert MODULE.address_block_count("5 Marina Crescent; 6 Raffles City Center") == 2
    assert MODULE.address_block_count("1234567") == 0
    assert MODULE.address_block_count(None) == 0


def test_bundle_with_several_phones_and_addresses_hides_its_map_pin():
    record = {"phone": "6111 1111 / 6222 2222", "address": "1 Raffles Place 048616 2 Orchard Turn 238801"}
    MODULE.annotate_location_metadata(record)
    assert record["multi_location"] is True
    assert record["location_pin_hidden"] is True
    assert record["map_pin_note"].startswith("This Love Dining entry bundles multiple outlets into one source record, so")


def test_bundle_naming_itself_twice_in_notes_hides_its_map_pin():
    record = {"name": "Din Tai Fung", "phone": "1 / 2", "notes": "Din Tai Fung Paragon. Din Tai Fung Raffles.", "address": "x"}
    MODULE.annotate_location_metadata(record)
    assert record["location_pin_hidden"] is True


def test_branch_directory_address_hides_its_map_pin():
    record = {"address": "See the FULL LIST of LOCATIONS online"}
    MODULE.annotate_location_metadata(record)
    assert record["multi_location"] is True


@pytest.mark.parametrize(
    "record",
    [
        {"phone": "6111 1111", "address": "1 Raffles Place 048616 2 Orchard Turn 238801"},
        {"phone": "1 / 2", "address": "1 Raffles Place 048616"},
        {"name": "Din Tai Fung", "phone": "1 / 2", "notes": "Din Tai Fung Paragon.", "address": "x"},
        {"name": "", "phone": "1 / 2", "notes": "x x", "address": "x"},
    ],
)
def test_single_outlet_keeps_its_map_pin(record):
    record, before = dict(record), dict(record)
    MODULE.annotate_location_metadata(record)
    assert record == before


@pytest.mark.parametrize(
    ("record", "status", "effective"),
    [
        ({"notes": "Privileges will only be valid until 30 April 2026."}, "ineligible", "2026-05-01"),
        ({"closing_note": "Not eligible from 26 April 2026"}, "ineligible", "2026-04-26"),
        ({"notes": "Permanently closed from 1 May 2026"}, "ineligible", "2026-05-01"),
        ({"notes": "Changes effective from 3 June 2026"}, "ineligible", "2026-06-03"),
        ({"notes": "Privileges will resume on 2 July 2026"}, "eligible", "2026-07-02"),
        ({"notes": "The outlet will reopen on 4 August 2026"}, "eligible", "2026-08-04"),
        ({"notes": "Privileges resume on 5 August 2026", "closing_note": None}, "eligible", "2026-08-05"),
    ],
)
def test_official_dates_in_notes_set_eligibility(record, status, effective):
    record = dict(record)  # parametrize shares this dict between runs
    MODULE.annotate_eligibility_metadata(record)
    assert (record["eligibility_status"], record["eligibility_effective_from"]) == (status, effective)


def test_valid_until_wins_over_a_later_resume_date():
    record = {"notes": "Privileges will only be valid until 30 April 2026. Will reopen on 1 June 2026."}
    MODULE.annotate_eligibility_metadata(record)
    assert record["eligibility_effective_from"] == "2026-05-01"


@pytest.mark.parametrize(
    "notes",
    [
        "Privileges will only be valid until 31 Smarch 2026",
        "Not eligible from 31 Smarch 2026",
        "Will reopen on 31 Smarch 2026",
        "Book ahead.",
    ],
)
def test_notes_without_a_real_date_leave_eligibility_unset(notes):
    record = {"notes": notes}
    MODULE.annotate_eligibility_metadata(record)
    assert record == {"notes": notes}


def test_enrichment_carries_coordinates_to_the_refreshed_record(paths):
    paths.output.write_text(json.dumps([
        {"id": "love-a", "name": "A", "address": "1 Road", "lat": 1.3, "lon": 103.8},
        {"id": "love-b", "name": "B", "address": "2 Road", "lat": 1.4, "lng": 103.9},
        {"id": "love-hidden", "name": "H", "address": "3 Road", "lat": 1.5, "lng": 104.0},
    ]))
    records = [
        {"id": "love-a", "name": "A"},
        {"id": "love-b", "name": "B", "lat": 9.9},
        {"id": "love-hidden", "name": "H", "location_pin_hidden": True},
        {"id": "love-new", "name": "N", "address": "4 Road"},
    ]
    assert MODULE.preserve_existing_enrichment(records) == [
        {"id": "love-a", "name": "A", "lat": 1.3, "lng": 103.8},
        {"id": "love-b", "name": "B", "lat": 9.9, "lng": 103.9},
        {"id": "love-hidden", "name": "H", "location_pin_hidden": True},
        {"id": "love-new", "name": "N", "address": "4 Road"},
    ]


def test_enrichment_is_not_guessed_when_two_old_records_share_name_and_address(paths):
    paths.output.write_text(json.dumps([
        {"id": "love-old-1", "name": "Bar", "address": "1 Road", "lat": 1.3, "lng": 103.8},
        {"id": "love-old-2", "name": " bar ", "address": "1  ROAD", "lat": 1.4, "lng": 103.9},
        {"id": "love-old-3", "name": "", "address": "", "lat": 1.5, "lng": 104.0},
    ]))
    records = [{"id": "love-new", "name": "Bar", "address": "1 Road"}, {"id": "love-blank", "name": "", "address": ""}]
    assert MODULE.preserve_existing_enrichment(records) == records
    assert "lat" not in records[0] and "lat" not in records[1]


def test_enrichment_without_a_previous_file_returns_records_unchanged(paths):
    records = [{"id": "love-a"}]
    assert MODULE.preserve_existing_enrichment(records) is records


def test_projection_drops_only_coordinates():
    record = {"id": "x", "name": "Café", "lat": 1, "lng": 2, "lon": 3}
    assert MODULE.official_record_projection(record) == {"id": "x", "name": "Café"}


def _fake_terms(monkeypatch, suffix: str = "") -> None:
    monkeypatch.setattr(MODULE, "fetch_bytes", lambda url: (url + suffix).encode())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


RECORDS = [
    {"type": "restaurant", "name": "Café", "id": "love-r", "lat": 1.3},
    {"type": "hotel", "name": "H1", "id": "love-h1"},
    {"type": "hotel", "name": "H2", "id": "love-h2"},
]
RECORDS_SHA = _sha(
    '[{"id": "love-r", "name": "Café", "type": "restaurant"}, '
    '{"id": "love-h1", "name": "H1", "type": "hotel"}, {"id": "love-h2", "name": "H2", "type": "hotel"}]'
)


def test_first_meta_treats_the_current_records_and_terms_as_reviewed(paths, monkeypatch):
    _fake_terms(monkeypatch)
    terms = {"restaurants": _sha(MODULE.RESTAURANTS_TNC_URL), "hotels": _sha(MODULE.HOTELS_TNC_URL)}
    assert MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z") == {
        "dataset": "love_dining",
        "program": "American Express Love Dining Singapore",
        "last_checked_at": "2026-11-01T00:00:00Z",
        "record_count": 3,
        "restaurant_count": 1,
        "hotel_outlet_count": 2,
        "records_sha256": RECORDS_SHA,
        "reviewed_records_sha256": RECORDS_SHA,
        "records_reviewed_at": "2026-11-01T00:00:00Z",
        "terms_hashes": terms,
        "reviewed_terms_hashes": terms,
        "reviewed_terms_manifest_sha256": {},
        "terms_reviewed_at": "2026-11-01T00:00:00Z",
        "terms_reviewed_at_by_document": {},
        "manual_review_required": False,
        "major_change_reasons": [],
        "official_pages": {"restaurants": MODULE.RESTAURANTS_URL, "hotels": MODULE.HOTELS_URL},
        "terms": {"restaurants": MODULE.RESTAURANTS_TNC_URL, "hotels": MODULE.HOTELS_TNC_URL},
        "source_notes": [
            "Restaurant cards use the official Amex Love Dining listing for outlet notes, address, phone, and source links.",
            "Promo rules use the official Love Dining restaurant and hotel T&C PDFs.",
            "Google ratings and AI summaries are enrichment fields and are not the source of truth for Amex benefit eligibility.",
        ],
    }


def test_changed_terms_and_listing_need_manual_review(paths, monkeypatch):
    _fake_terms(monkeypatch)
    paths.meta.write_text(json.dumps(MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z")))
    _fake_terms(monkeypatch, "v2")
    meta = MODULE.build_meta(RECORDS[:1], "2026-11-02T00:00:00Z")
    assert meta["manual_review_required"] is True
    assert meta["major_change_reasons"] == [
        "Love Dining T&C PDF changed: restaurants, hotels",
        "Official Love Dining listing content changed",
    ]
    assert meta["records_reviewed_at"] == meta["terms_reviewed_at"] == "2026-11-01T00:00:00Z"


def test_coordinates_alone_do_not_change_the_listing_hash(paths, monkeypatch):
    _fake_terms(monkeypatch)
    paths.meta.write_text(json.dumps(MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z")))
    moved = [{**record, "lat": 9.0, "lng": 9.0} for record in RECORDS]
    assert MODULE.build_meta(moved, "2026-11-02T00:00:00Z")["manual_review_required"] is False


@pytest.mark.parametrize("flag", ["mark_reviewed", "mark_terms_reviewed"])
def test_terms_review_accepts_the_current_terms(paths, monkeypatch, flag):
    _fake_terms(monkeypatch)
    paths.meta.write_text(json.dumps(MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z")))
    _fake_terms(monkeypatch, "v2")
    meta = MODULE.build_meta(RECORDS, "2026-11-02T00:00:00Z", **{flag: True})
    assert meta["reviewed_terms_hashes"] == meta["terms_hashes"]
    assert meta["terms_reviewed_at"] == "2026-11-02T00:00:00Z"
    assert meta["terms_reviewed_at_by_document"] == {"restaurants": "2026-11-02T00:00:00Z", "hotels": "2026-11-02T00:00:00Z"}
    assert meta["manual_review_required"] is False


@pytest.mark.parametrize("flag", ["mark_reviewed", "mark_records_reviewed"])
def test_records_review_accepts_the_current_listing(paths, monkeypatch, flag):
    _fake_terms(monkeypatch)
    paths.meta.write_text(json.dumps(MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z")))
    meta = MODULE.build_meta(RECORDS[:1], "2026-11-02T00:00:00Z", **{flag: True})
    assert meta["reviewed_records_sha256"] == meta["records_sha256"] != RECORDS_SHA
    assert meta["records_reviewed_at"] == "2026-11-02T00:00:00Z"
    assert meta["major_change_reasons"] == []


def test_review_state_from_the_previous_meta_is_kept(paths, monkeypatch):
    _fake_terms(monkeypatch)
    previous = MODULE.build_meta(RECORDS, "2026-11-01T00:00:00Z")
    previous["reviewed_terms_manifest_sha256"] = {"hotels": "m"}
    previous["terms_reviewed_at_by_document"] = {"hotels": "2026-10-01T00:00:00Z"}
    paths.meta.write_text(json.dumps(previous))
    meta = MODULE.build_meta(RECORDS, "2026-11-02T00:00:00Z")
    assert meta["reviewed_terms_manifest_sha256"] == {"hotels": "m"}
    assert meta["terms_reviewed_at_by_document"] == {"hotels": "2026-10-01T00:00:00Z"}


def test_terms_fetch_sends_a_browser_user_agent(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, agent=request.get_header("User-agent"), timeout=timeout)
        return io.BytesIO(b"%PDF")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    assert MODULE.fetch_bytes("https://example.test/t.pdf") == b"%PDF"
    assert seen == {"url": "https://example.test/t.pdf", "agent": MODULE.CONTEXT_OPTS["user_agent"], "timeout": 30}
    assert MODULE.sha256_hex(b"%PDF") == hashlib.sha256(b"%PDF").hexdigest()


def _nominatim_replies(monkeypatch, replies: list[list[dict]]) -> list[str]:
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        assert request.get_header("User-agent") == "amex-dining-map/1.0"
        assert timeout == 10
        return io.BytesIO(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    return urls


def test_nominatim_query_is_limited_to_singapore(monkeypatch):
    urls = _nominatim_replies(monkeypatch, [[{"lat": "1.25", "lon": "103.5"}], []])
    assert MODULE._nominatim("Singapore 048616") == (1.25, 103.5)
    assert MODULE._nominatim("nowhere") is None
    assert urls[0] == "https://nominatim.openstreetmap.org/search?q=Singapore%20048616&format=json&limit=1&countrycodes=sg"


def _geocoder(monkeypatch, answers: dict[str, tuple[float, float] | None]) -> list[str]:
    queries = []

    def fake(query):
        queries.append(query)
        return answers.get(query)

    monkeypatch.setattr(MODULE, "_nominatim", fake)
    return queries


def test_geocode_prefers_the_postcode_and_caches_it(paths, monkeypatch):
    queries = _geocoder(monkeypatch, {"Singapore 048616": (1.2, 103.8)})
    cache = {}
    assert MODULE.geocode_address("1 Raffles Place, Singapore 048616", cache) == (1.2, 103.8)
    assert cache == {"1 Raffles Place, Singapore 048616": [1.2, 103.8]}
    assert MODULE.geocode_address("1 Raffles Place, Singapore 048616", cache) == [1.2, 103.8]
    assert queries == ["Singapore 048616"]


def test_geocode_prefers_the_postcode_after_singapore(paths, monkeypatch):
    queries = _geocoder(monkeypatch, {"Singapore 048616": (1.2, 103.8)})
    assert MODULE.geocode_address("Unit 100200, Singapore 048616", {}) == (1.2, 103.8)
    assert queries == ["Singapore 048616"]


def test_geocode_falls_back_to_a_bare_postcode_then_the_first_address_block(paths, monkeypatch):
    address = "1 Raffles Place 048616 2 Orchard Turn 238801"
    queries = _geocoder(monkeypatch, {"1 Raffles Place 048616, Singapore": (1.2, 103.8)})
    cache = {}
    assert MODULE.geocode_address(address, cache) == (1.2, 103.8)
    assert queries == ["Singapore 048616", "1 Raffles Place 048616, Singapore"]
    assert cache == {address: [1.2, 103.8]}


def test_geocode_tries_the_full_address_last_and_caches_a_miss(paths, monkeypatch):
    queries = _geocoder(monkeypatch, {"3 Hill Street, Singapore": (1.29, 103.85)})
    cache = {}
    assert MODULE.geocode_address("3 Hill Street", cache) == (1.29, 103.85)
    assert cache == {"3 Hill Street": [1.29, 103.85]}
    assert MODULE.geocode_address("Nowhere 1", cache) is None
    assert cache["Nowhere 1"] is None
    assert queries == ["3 Hill Street, Singapore", "Nowhere 1, Singapore"]


def test_geocode_waits_between_requests_after_each_miss(paths, monkeypatch):
    pauses = []
    monkeypatch.setattr(MODULE.time, "sleep", pauses.append)
    _geocoder(monkeypatch, {})
    MODULE.geocode_address("1 Raffles Place 048616 2 Orchard Turn 238801", {})
    assert pauses == [1.1, 1.1]


def test_geocode_all_fills_coordinates_and_saves_the_cache(paths, monkeypatch, capsys):
    paths.cache.write_text(json.dumps({"1 Road": [1.1, 103.1]}))
    _geocoder(monkeypatch, {"2 Road, Singapore": (1.2, 103.2), "Café Road, Singapore": (1.5, 103.5)})
    pauses = []
    monkeypatch.setattr(MODULE.time, "sleep", pauses.append)
    records = [
        {"name": "Cached", "address": "1 Road"},
        {"name": "Fresh", "address": "2 Road"},
        {"name": "Miss", "address": "3 Road"},
        {"name": "Blank"},
        {"name": "Known", "lat": 1.4, "lon": 103.4},
        {"name": "Bundle", "location_pin_hidden": True, "lat": 1, "lng": 2, "lon": 3},
        {"name": "HasBoth", "address": "9 Road", "lat": 1.6, "lng": 103.6, "lon": 0.0},
        {"name": "NoLat", "address": "Café Road", "lng": 103.0},
    ]
    assert MODULE.geocode_all(records) == [
        {"name": "Cached", "address": "1 Road", "lat": 1.1, "lng": 103.1},
        {"name": "Fresh", "address": "2 Road", "lat": 1.2, "lng": 103.2},
        {"name": "Miss", "address": "3 Road"},
        {"name": "Blank"},
        {"name": "Known", "lat": 1.4, "lng": 103.4},
        {"name": "Bundle", "location_pin_hidden": True},
        {"name": "HasBoth", "address": "9 Road", "lat": 1.6, "lng": 103.6, "lon": 0.0},
        {"name": "NoLat", "address": "Café Road", "lng": 103.5, "lat": 1.5},
    ]
    assert pauses == [1.1] * 4
    assert json.loads(paths.cache.read_text()) == {
        "1 Road": [1.1, 103.1], "2 Road": [1.2, 103.2], "3 Road": None, "Café Road": [1.5, 103.5],
    }
    assert '"Café Road"' in paths.cache.read_text()
    assert paths.cache.read_text().startswith('{\n  "1 Road": [\n    1.1,') and paths.cache.read_text().endswith("]\n}\n")
    assert capsys.readouterr().out.splitlines() == [
        "  [1/8] Cached → 1.1000, 103.1000",
        "  [2/8] Fresh → 1.2000, 103.2000",
        "  [3/8] Miss — geocode failed for: 3 Road",
        "  [4/8] Blank — no address, skipping geocode",
        "  [6/8] Bundle — multiple outlet bundle, skipping single-pin geocode",
        "  [8/8] NoLat → 1.5000, 103.5000",
    ]


def test_geocode_network_failure_is_retried_next_run(paths, monkeypatch, capsys):
    def flaky(query):
        if query == "1 Road, Singapore":
            raise urllib.error.URLError("offline")
        return (1.2, 103.2)

    monkeypatch.setattr(MODULE, "_nominatim", flaky)
    records = [{"name": "A", "address": "1 Road"}, {"name": "B", "address": "2 Road"}]
    assert MODULE.geocode_all(records) == [{"name": "A", "address": "1 Road"}, {"name": "B", "address": "2 Road", "lat": 1.2, "lng": 103.2}]
    assert json.loads(paths.cache.read_text()) == {"2 Road": [1.2, 103.2]}
    assert "  [1/2] A WARNING: geocode request failed: URLError('offline')" in capsys.readouterr().out


def test_geocode_all_skip_touches_nothing(paths):
    records = [{"name": "A", "address": "1 Road"}]
    assert MODULE.geocode_all(records, skip=True) is records
    assert not paths.cache.exists()


def test_diff_lists_added_removed_and_changed_records(paths, capsys):
    paths.output.write_text(json.dumps(
        [{"id": "love-a", "name": "A", "phone": "1"}, {"id": "love-gone", "name": "Gone"}]
        + [{"id": f"love-c{n:02d}", "name": f"C{n:02d}", "notes": "old"} for n in range(26)]
    ))
    new = (
        [{"id": "love-a", "name": "A", "phone": " 1 "}, {"id": "love-new", "name": "New"}]
        + [{"id": f"love-c{n:02d}", "name": f"C{n:02d}", "notes": "new", "address": "x"} for n in range(26)]
    )
    MODULE.run_diff(new)
    lines = capsys.readouterr().out.splitlines()
    assert lines[:5] == ["", "Diff: +1 added, -1 removed, 26 changed, 28 unique names", "  + New", "  - Gone", "  ~ C00: notes, address"]
    assert len(lines) == 5 + 24 + 1
    assert lines[-1] == "  ... and 1 more changed records"


def test_diff_lists_exactly_twenty_five_changes_in_full(paths, capsys):
    paths.output.write_text(json.dumps([{"id": f"love-{n}", "name": str(n), "notes": "old"} for n in range(25)]))
    MODULE.run_diff([{"id": f"love-{n}", "name": str(n), "notes": "new"} for n in range(25)])
    assert "more changed records" not in capsys.readouterr().out


def test_diff_names_every_compared_field(paths, capsys):
    fields = ("notes", "closing_note", "opening_hours", "phone", "address", "cuisine", "terms_url", "source_url")
    paths.output.write_text(json.dumps([{"id": "love-a", "name": "A"}]))
    MODULE.run_diff([{"id": "love-a", "name": "A", **{field: "x" for field in fields}}])
    assert capsys.readouterr().out.splitlines()[-1] == f"  ~ A: {', '.join(fields)}"


def test_diff_without_a_previous_file_says_so(paths, capsys):
    MODULE.run_diff([])
    assert capsys.readouterr().out == "No existing file to diff against.\n"


def test_cli_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scrape_love_dining.py"])
    defaults = MODULE.parse_args()
    assert vars(defaults) == {
        "dry_run": False, "diff": False, "no_geocode": False,
        "mark_reviewed": False, "mark_records_reviewed": False, "mark_terms_reviewed": False,
    }
    flags = ["--dry-run", "--diff", "--no-geocode", "--mark-reviewed", "--mark-records-reviewed", "--mark-terms-reviewed"]
    monkeypatch.setattr(sys, "argv", ["scrape_love_dining.py", *flags])
    assert all(vars(MODULE.parse_args()).values())


class _FakePage:
    def __init__(self, texts: dict[str, str], calls: list):
        self.texts, self.calls, self.url = texts, calls, ""

    def goto(self, url, wait_until, timeout):
        self.url = url
        self.calls.append(("goto", url, wait_until, timeout))

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    def evaluate(self, script):
        assert script == MODULE.DOM_TEXT_JS
        return self.texts[self.url]


def _fake_browser(monkeypatch, texts: dict[str, str]) -> list:
    calls: list = []
    page = _FakePage(texts, calls)

    class Browser:
        def new_context(self, **options):
            calls.append(("context", options))
            return types.SimpleNamespace(new_page=lambda: page)

        def close(self):
            calls.append(("close",))

    class Chromium:
        def launch(self, headless):
            calls.append(("launch", headless))
            return Browser()

    class Playwright:
        def __enter__(self):
            return types.SimpleNamespace(chromium=Chromium())

        def __exit__(self, *exc):
            return False

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = Playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    return calls


REST_TEXT = """Love Dining @ Restaurants Partners
Asian
Jia He Grand Chinese Restaurant
Details
Tel: 6111 1111 / 6222 2222
Address:
1 Raffles Place 048616 2 Orchard Turn 238801
Terms and Conditions
Café Été
Details
Terms and Conditions
Your Love Dining Benefits"""
HOTEL_TEXT = """Love Dining @ Hotels Partners
Grand Hotel
1 Grand Road, Singapore 222222
Bar
Details
Cuisine: Bar
Terms and Conditions
Enjoy 20% off your total bill.
GET AN AMERICAN EXPRESS CARD"""


def _run_main(monkeypatch, *flags: str) -> list:
    calls = _fake_browser(monkeypatch, {MODULE.RESTAURANTS_URL: REST_TEXT, MODULE.HOTELS_URL: HOTEL_TEXT})
    _fake_terms(monkeypatch)
    _geocoder(monkeypatch, {"Singapore 222222": (1.3, 103.9)})
    monkeypatch.setattr(MODULE, "iso_now", lambda: "2026-11-14T00:00:00Z")
    monkeypatch.setattr(sys, "argv", ["scrape_love_dining.py", *flags])
    MODULE.main()
    return calls


def test_refresh_writes_annotated_geocoded_records_and_meta(paths, monkeypatch, capsys):
    calls = _run_main(monkeypatch)
    records = json.loads(paths.output.read_text())
    assert [(r["id"], r.get("lat"), r.get("lng")) for r in records] == [
        ("love-jia-he-grand-chinese-restaurant", None, None),
        ("love-caf-t", None, None),
        ("love-grand-hotel-bar", 1.3, 103.9),
    ]
    assert '"Café Été"' in paths.output.read_text()
    assert records[0]["location_pin_hidden"] is True
    assert records[0]["eligibility_status"] == "ineligible"
    assert records[0]["eligibility_effective_from"] == "2026-04-26"
    assert records[2]["fixed_discount_percent"] == 20
    assert paths.output.read_text().endswith("\n  }\n]\n")
    assert '\n  {\n    "id"' in paths.output.read_text()
    meta = json.loads(paths.meta.read_text())
    assert (meta["record_count"], meta["last_checked_at"], meta["manual_review_required"]) == (3, "2026-11-14T00:00:00Z", False)
    assert paths.meta.read_text().startswith('{\n  "dataset"') and paths.meta.read_text().endswith("}\n")
    assert calls == [
        ("launch", True),
        ("context", MODULE.CONTEXT_OPTS),
        ("goto", MODULE.RESTAURANTS_URL, "domcontentloaded", 30_000),
        ("wait", 5_000),
        ("goto", MODULE.HOTELS_URL, "domcontentloaded", 30_000),
        ("wait", 5_000),
        ("close",),
    ]
    out = capsys.readouterr().out
    assert "Total: 3 venues" in out and "Geocoded: 1/3" in out
    assert f"  Loading {MODULE.RESTAURANTS_URL}\n  Loading {MODULE.HOTELS_URL}\n" in out
    assert f"Written → {paths.output}" in out and f"Written → {paths.meta}" in out


def test_refresh_keeps_coordinates_and_skips_geocoding_when_asked(paths, monkeypatch):
    paths.output.write_text(json.dumps([{"id": "love-grand-hotel-bar", "name": "Bar", "lat": 1.0, "lng": 2.0}]))
    paths.meta.write_text(json.dumps({"reviewed_records_sha256": "old", "records_reviewed_at": "2026-01-01T00:00:00Z"}))
    _run_main(monkeypatch, "--no-geocode", "--mark-records-reviewed")
    records = json.loads(paths.output.read_text())
    assert records[2]["lat"] == 1.0 and records[2]["lng"] == 2.0
    assert not paths.cache.exists()
    meta = json.loads(paths.meta.read_text())
    assert (meta["records_reviewed_at"], meta["manual_review_required"]) == ("2026-11-14T00:00:00Z", False)


def test_refresh_refuses_to_overwrite_a_much_larger_file(paths, monkeypatch):
    paths.output.write_text(json.dumps([{"id": f"love-{n}", "name": str(n)} for n in range(10)]))
    with pytest.raises(SystemExit, match="scrape found 3 records, previous file has 10"):
        _run_main(monkeypatch)
    assert len(json.loads(paths.output.read_text())) == 10


def test_dry_run_prints_the_parsed_records_and_writes_nothing(paths, monkeypatch, capsys):
    _run_main(monkeypatch, "--dry-run")
    out = capsys.readouterr().out
    assert out.endswith(
        "\nRestaurants:\n"
        "  Jia He Grand Chinese Restaurant |  | 1 Raffles Place 048616 2 Orchard Turn 238801 | 6111 1111 / 6222 2222\n"
        "  Café Été |  |  | \n"
        "\nHotel outlets:\n"
        "  [Grand Hotel] Bar | Bar | 1 Grand Road, Singapore 222222 | \n"
    )
    assert not paths.output.exists() and not paths.meta.exists()


def test_diff_mode_prints_the_diff_and_writes_nothing(paths, monkeypatch, capsys):
    previous = json.dumps([{"id": "love-grand-hotel-bar", "name": "Bar"}])
    paths.output.write_text(previous)
    _run_main(monkeypatch, "--diff")
    assert "Diff: +2 added, -0 removed, 1 changed, 3 unique names" in capsys.readouterr().out
    assert paths.output.read_text() == previous and not paths.meta.exists()


@pytest.mark.parametrize("flag", ["--mark-reviewed", "--mark-terms-reviewed"])
def test_terms_review_flags_are_refused(paths, monkeypatch, flag):
    _fake_browser(monkeypatch, {})
    monkeypatch.setattr(sys, "argv", ["scrape_love_dining.py", flag])
    with pytest.raises(SystemExit, match="T&C reviews require an exact hash-bound manifest; use scripts/apply_love_dining_document_review.py"):
        MODULE.main()
