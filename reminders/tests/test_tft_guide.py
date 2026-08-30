from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

from app import tft_guide


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.fromisoformat(
    tft_guide.load_catalog()["release_source"]["updated_at"].replace("Z", "+00:00")
) + timedelta(hours=1)


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
    assert _catalog()["schema_version"] == 4
    assert [(item["id"], item["review_status"]) for item in _catalog()["documents"]] == [
        ("tft-terms", "current_baseline"),
        ("tft-faq", "current_baseline"),
    ]
    assert len(_catalog()["venues"]) == 23


def test_vue_platinum_natural_query_is_exact_and_cited():
    answer = tft_guide.handle_message(
        "Show me the VUE Platinum menu", _catalog(), NOW
    )

    assert "VUE — Platinum menu" in answer
    assert "VUE-Menu_Platinum.pdf" in answer
    assert "VUE-Menu_Centurion.pdf" not in answer
    vue = next(item for item in _catalog()["venues"] if item["id"] == "tft-vue")
    assert f"checked: {tft_guide._date(vue['menus']['platinum']['checked_at'])}" in answer
    assert "#/table-for-two?venue=tft-vue" in answer


def test_venue_start_link_returns_reviewed_venue_context():
    answer = tft_guide.handle_message("/start venue_tft-vue", _catalog(), NOW)

    assert "VUE — official menu variants" in answer
    assert "VUE-Menu_Platinum.pdf" in answer
    assert "VUE-Menu_Centurion.pdf" in answer


def test_unknown_start_payload_falls_back_to_help():
    answer = tft_guide.handle_message("/start https://attacker.example", _catalog(), NOW)

    assert answer.startswith("Table for Two helper")
    assert "attacker.example" not in answer


def test_about_and_common_program_questions_are_bounded_and_cited():
    for query in (
        "/about",
        "What is Table for Two?",
        "How does TFT work?",
        "Tell me about Table for Two",
    ):
        answer = tft_guide.handle_message(query, _catalog(), NOW)

        assert answer.startswith("American Express Table for Two by Platinum")
        assert "reviewed Table for Two venue roster" in answer
        assert "does not determine personal eligibility" in answer
        assert _catalog()["official_url"] in answer
        assert "Roster checked:" in answer
        assert "#/table-for-two" in answer
        assert len(answer) <= tft_guide.MAX_REPLY_LENGTH


def test_about_rejects_untrusted_official_source_url():
    catalog = copy.deepcopy(_catalog())
    catalog["official_url"] = "https://attacker.example/program"

    answer = tft_guide.handle_message("What is TFT?", catalog, NOW)

    assert "could not be verified safely" in answer
    assert "attacker.example" not in answer


def test_exact_venue_details_work_for_command_and_safe_common_questions():
    for query in (
        "/venue VUE",
        "Where is VUE?",
        "Tell me about VUE",
    ):
        answer = tft_guide.handle_message(query, _catalog(), NOW)

        assert answer.startswith("VUE — reviewed venue details")
        assert "OUE Bayfront, 50 Collyer Quay" in answer
        assert "Indexed official menus: Centurion, Platinum" in answer
        assert "Roster checked:" in answer
        assert "Menu index checked:" in answer
        assert _catalog()["official_url"] in answer
        assert "#/table-for-two?venue=tft-vue" in answer
        assert len(answer) <= tft_guide.MAX_REPLY_LENGTH

    menu = tft_guide.handle_message("Does VUE have a menu?", _catalog(), NOW)
    assert menu.startswith("VUE — official menu variants")
    assert "VUE-Menu_Platinum.pdf" in menu
    assert "VUE-Menu_Centurion.pdf" in menu


def test_venue_details_do_not_fuzzy_guess_or_echo_unsafe_address():
    unknown = tft_guide.handle_message("Where is VUW?", _catalog(), NOW)
    assert "could not match" in unknown
    assert "OUE Bayfront" not in unknown

    catalog = copy.deepcopy(_catalog())
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    vue["address"] = "Injected\nhttps://attacker.example"
    answer = tft_guide.handle_message("/venue VUE", catalog, NOW)

    assert "Address: unavailable in the reviewed snapshot" in answer
    assert "attacker.example" not in answer


def test_venue_details_disclose_stale_roster_and_menu_review_state():
    catalog = copy.deepcopy(_catalog())
    catalog["roster_checked_at"] = (NOW - timedelta(hours=37)).isoformat()

    answer = tft_guide.handle_message("/venue VUE", catalog, NOW)

    assert "Roster snapshot is older than 36 hours" in answer
    assert "2 items awaiting manual review" in answer


def test_vue_centurion_is_not_conflated_with_platinum():
    answer = tft_guide.handle_message("VUE black card menu", _catalog(), NOW)
    assert "VUE — Centurion menu" in answer
    assert "VUE-Menu_Centurion.pdf" in answer
    assert "VUE-Menu_Platinum.pdf" not in answer


def test_retained_menu_discloses_pending_menu_review_queue():
    answer = tft_guide.handle_message(
        "/menu Osteria Mozza platinum", _catalog(), NOW
    )

    assert "Official Amex PDF" in answer
    assert "items awaiting manual review" in answer


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
    assert "2 items awaiting manual review" in answer


def test_missing_and_buffet_states_show_stale_and_specific_review_context():
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
        assert "2 items awaiting manual review" in answer
    assert "Manual review is pending" in missing
    assert "Manual review is pending" not in buffet


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
    assert "2 items awaiting manual review" in answer


def test_venues_lists_current_reviewed_roster_without_stale_caveat():
    answer = tft_guide.handle_message("/venues", _catalog(), NOW)
    assert "• VUE" in answer
    assert "• One-Ninety" in answer
    assert "awaiting manual review" not in answer
    assert _catalog()["official_url"] in answer
    assert len(answer) <= tft_guide.MAX_REPLY_LENGTH


def test_venues_warns_when_bundled_roster_is_stale():
    catalog = copy.deepcopy(_catalog())
    catalog["roster_checked_at"] = (NOW - timedelta(hours=37)).isoformat()
    answer = tft_guide.handle_message("/venues", catalog, NOW)
    assert "older than 36 hours" in answer


def test_vue_dinner_release_pattern_is_observed_bounded_and_cited():
    answer = tft_guide.handle_message("/release VUE dinner", _catalog(), NOW)

    assert answer.startswith("VUE — observed first-detection pattern")
    assert "median first-detected lead 60 days (range 18–60)" in answer
    assert "8 observations; tracker confidence: medium" in answer
    assert "around 00:30 SGT in about 62% of observations" in answer
    assert "Latest included detection: 30 Aug 2026, 02:52 SGT" in answer
    assert "not an Amex or restaurant release policy" in answer
    assert "does not show current seat availability" in answer
    assert _catalog()["official_url"] in answer
    assert "#/table-for-two?venue=tft-vue" in answer
    assert "currently available" not in answer
    assert "sold out" not in answer


def test_release_without_meal_keeps_meals_separate_and_bounded():
    answer = tft_guide.handle_message("/release VUE", _catalog(), NOW)

    assert "Lunch: median first-detected lead" in answer
    assert "Dinner: median first-detected lead" in answer
    assert answer.index("Dinner:") < answer.index("Lunch:")
    assert len(answer) <= tft_guide.MAX_REPLY_LENGTH


def test_release_time_is_omitted_when_confidence_policy_suppresses_it():
    catalog = copy.deepcopy(_catalog())
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    dinner = next(
        pattern for pattern in vue["release_patterns"] if pattern["meal"] == "Dinner"
    )
    dinner["typical_first_seen_sgt"] = None
    dinner["typical_time_observation_share"] = 0.5

    answer = tft_guide.handle_message("/release VUE dinner", catalog, NOW)

    assert "median first-detected lead" in answer
    assert "First detected around" not in answer


def test_release_snapshot_staleness_is_explicit_without_suppressing_history():
    catalog = copy.deepcopy(_catalog())
    snapshot = NOW - timedelta(hours=37)
    catalog["release_source"]["updated_at"] = snapshot.isoformat()
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    dinner = next(
        pattern for pattern in vue["release_patterns"] if pattern["meal"] == "Dinner"
    )
    dinner["latest_observation_at"] = (snapshot - timedelta(hours=1)).isoformat()

    answer = tft_guide.handle_message("/release VUE dinner", catalog, NOW)

    assert "older than 36 hours" in answer
    assert "treat the pattern as stale" in answer
    assert "median first-detected lead" in answer


def test_invalid_or_future_release_evidence_is_not_reported():
    catalog = copy.deepcopy(_catalog())
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")
    dinner = next(
        pattern for pattern in vue["release_patterns"] if pattern["meal"] == "Dinner"
    )
    dinner["latest_observation_at"] = (NOW + timedelta(days=1)).isoformat()

    answer = tft_guide.handle_message("/release VUE dinner", catalog, NOW)

    assert "not enough valid repeated Dinner observations" in answer
    assert "median first-detected lead" not in answer


def test_invalid_release_snapshot_suppresses_pattern_metrics():
    catalog = copy.deepcopy(_catalog())
    catalog["release_source"]["updated_at"] = "not-a-date"

    answer = tft_guide.handle_message("/release VUE dinner", catalog, NOW)

    assert "could not be verified safely" in answer
    assert "median first-detected lead" not in answer


def test_wrong_release_project_suppresses_pattern_metrics():
    catalog = copy.deepcopy(_catalog())
    catalog["release_source"]["project"] = "GenericDiningCity"

    answer = tft_guide.handle_message("/release VUE dinner", catalog, NOW)

    assert "could not be verified safely" in answer
    assert "median first-detected lead" not in answer


def test_unknown_release_venue_and_meal_do_not_guess():
    venue = tft_guide.handle_message("/release VUW dinner", _catalog(), NOW)
    meal = tft_guide.handle_message("/release VUE breakfast", _catalog(), NOW)

    assert "could not match" in venue
    assert "could not match" in meal
    assert "median first-detected lead" not in venue + meal


def test_release_help_uses_current_reviewed_source_context():
    help_text = tft_guide.handle_message("/help", _catalog(), NOW)
    answer = tft_guide.handle_message("/release VUE dinner", _catalog(), NOW)

    assert "/release VUE dinner" in help_text
    assert "awaiting manual review" not in answer


def test_release_projection_joins_by_stable_venue_id_not_display_name():
    module_path = ROOT / "scripts" / "build_tft_guide_catalog.py"
    spec = importlib.util.spec_from_file_location("build_tft_guide_catalog_join", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    source = json.loads((ROOT / "data" / "table-for-two.json").read_text())
    history = json.loads(
        (ROOT / "data" / "table-for-two-release-history.json").read_text()
    )
    for item in history["patterns"]:
        if item["venue_id"] == "tft-vue":
            item["venue_name"] = "Untrusted renamed display value"
    for item in history["observations"]:
        if item["venue_id"] == "tft-vue":
            item["venue_name"] = "Another untrusted display value"
    history["observations"].append(
        {
            "venue_id": "tft-vue",
            "venue_name": "Untrusted newer baseline",
            "meal": "Dinner",
            "slot_date": "2026-12-31",
            "first_seen_at": "2026-08-30T02:00:00Z",
            "lead_days": 123,
            "baseline": True,
        }
    )

    catalog = module.build_catalog(source, history)
    vue = next(venue for venue in catalog["venues"] if venue["id"] == "tft-vue")

    assert vue["name"] == "VUE"
    assert {pattern["meal"] for pattern in vue["release_patterns"]} == {
        "Lunch",
        "Dinner",
    }
    dinner = next(
        pattern for pattern in vue["release_patterns"] if pattern["meal"] == "Dinner"
    )
    assert dinner["latest_observation_at"] == "2026-08-29T18:52:06Z"
