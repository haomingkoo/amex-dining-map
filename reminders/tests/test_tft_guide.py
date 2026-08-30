from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import tft_guide


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)


def _catalog() -> dict:
    return tft_guide.load_catalog()


def test_generated_catalog_matches_current_tft_source():
    module_path = ROOT / "scripts" / "build_tft_guide_catalog.py"
    spec = importlib.util.spec_from_file_location("build_tft_guide_catalog", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    source = json.loads((ROOT / "data" / "table-for-two.json").read_text())

    assert module.build_catalog(source) == _catalog()
    assert len(_catalog()["venues"]) == 23


def test_vue_platinum_natural_query_is_exact_and_cited():
    answer = tft_guide.handle_message(
        "Show me the VUE Platinum menu", _catalog(), NOW
    )

    assert "VUE — Platinum menu" in answer
    assert "VUE-Menu_Platinum.pdf" in answer
    assert "VUE-Menu_Centurion.pdf" not in answer
    assert "checked: 29 Aug 2026, 23:52 UTC" in answer
    assert "#/table-for-two?venue=tft-vue" in answer


def test_vue_centurion_is_not_conflated_with_platinum():
    answer = tft_guide.handle_message("VUE black card menu", _catalog(), NOW)
    assert "VUE — Centurion menu" in answer
    assert "VUE-Menu_Centurion.pdf" in answer
    assert "VUE-Menu_Platinum.pdf" not in answer


def test_menu_without_card_shows_both_variants_without_conflating_them():
    answer = tft_guide.handle_message("/menu VUE", _catalog(), NOW)
    assert "official menu variants" in answer
    assert "VUE-Menu_Platinum.pdf" in answer
    assert "VUE-Menu_Centurion.pdf" in answer
    assert "separate files" in answer


def test_missing_and_buffet_menu_states_are_honest():
    missing = tft_guide.handle_message(
        "/menu One Ninety platinum", _catalog(), NOW
    )
    buffet = tft_guide.handle_message("/menu Colony platinum", _catalog(), NOW)

    assert "No official PDF was matched" in missing
    assert "does not prove no menu exists" in missing
    assert "buffet venue" in buffet
    assert "not expected" in buffet


def test_unqualified_missing_menu_does_not_invent_a_card_variant():
    answer = tft_guide.handle_message("/menu One Ninety", _catalog(), NOW)
    assert answer.startswith("One-Ninety — menu")
    assert "Platinum" not in answer
    assert "Centurion" not in answer


def test_absent_requested_variant_shows_source_freshness_and_nonexistence_caveat():
    catalog = copy.deepcopy(_catalog())
    catalog["menu_source"]["checked_at"] = (NOW - timedelta(hours=37)).isoformat()

    answer = tft_guide.handle_message(
        "/menu The Feather Blade centurion", catalog, NOW
    )

    assert "No indexed official Centurion PDF" in answer
    assert "does not prove no such menu exists" in answer
    assert "Menu index checked:" in answer
    assert "older than 36 hours" in answer
    assert "awaiting manual review" in answer


def test_missing_and_buffet_states_show_stale_and_review_context():
    catalog = copy.deepcopy(_catalog())
    stale = (NOW - timedelta(hours=37)).isoformat()
    for venue_id in ("tft-one-ninety", "tft-colony"):
        venue = next(item for item in catalog["venues"] if item["id"] == venue_id)
        venue["menus"]["default"]["checked_at"] = stale

    missing = tft_guide.handle_message("/menu One Ninety", catalog, NOW)
    buffet = tft_guide.handle_message("/menu Colony", catalog, NOW)

    for answer in (missing, buffet):
        assert "Menu index checked:" in answer
        assert "older than 36 hours" in answer
        assert "awaiting manual review" in answer


def test_exact_aliases_match_but_typo_does_not_guess():
    alias = tft_guide.handle_message(
        "/menu Cultivate Cafe platinum", _catalog(), NOW
    )
    typo = tft_guide.handle_message("/menu VUW platinum", _catalog(), NOW)

    assert alias.startswith("Cultivate — Platinum menu")
    assert "could not match" in typo
    assert "VUE-Menu" not in typo


def test_every_canonical_venue_name_resolves_without_stopword_damage():
    catalog = _catalog()
    for venue in catalog["venues"]:
        answer = tft_guide.handle_message(
            f"/menu {venue['name']} platinum", catalog, NOW
        )
        assert "could not match" not in answer, venue["name"]
        assert answer.startswith(venue["name"]), venue["name"]


def test_stale_menu_remains_linked_with_warning():
    catalog = copy.deepcopy(_catalog())
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    checked = NOW - timedelta(hours=36, seconds=1)
    vue["menus"]["platinum"]["checked_at"] = checked.isoformat()

    answer = tft_guide.handle_message("/menu VUE platinum", catalog, NOW)

    assert "older than 36 hours" in answer
    assert "VUE-Menu_Platinum.pdf" in answer


def test_bad_menu_url_fails_safe_without_linking_it():
    catalog = copy.deepcopy(_catalog())
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    vue["menus"]["platinum"]["url"] = "http://127.0.0.1/private"

    answer = tft_guide.handle_message("/menu VUE platinum", catalog, NOW)

    assert "could not be verified safely" in answer
    assert "127.0.0.1" not in answer
    assert "Menu index checked:" in answer
    assert "awaiting manual review" in answer


def test_venues_lists_current_roster_and_review_caveat():
    answer = tft_guide.handle_message("/venues", _catalog(), NOW)
    assert "• VUE" in answer
    assert "• One-Ninety" in answer
    assert "awaiting manual review" in answer
    assert _catalog()["official_url"] in answer
    assert len(answer) <= tft_guide.MAX_REPLY_LENGTH


def test_venues_warns_when_bundled_roster_is_stale():
    catalog = copy.deepcopy(_catalog())
    catalog["roster_checked_at"] = (NOW - timedelta(hours=37)).isoformat()
    answer = tft_guide.handle_message("/venues", catalog, NOW)
    assert "older than 36 hours" in answer
