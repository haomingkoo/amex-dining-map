#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "fetch_tft_menus.py"
spec = importlib.util.spec_from_file_location("menus_mod", MODULE_PATH)
menus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menus)


def main() -> None:
    assert menus.MENU_FILENAME_RE.match("HighHouse-Menu_Platinum.pdf")
    assert menus.MENU_FILENAME_RE.match("HighHouse-Menu_Centurion.pdf")
    assert menus.MENU_FILENAME_RE.match("Osteria-Mozza-Menu-Centurion.pdf")
    assert menus.filename_stem("Feather-Blade_Menu.pdf") == "Feather-Blade"
    assert menus.filename_stem("Osteria-Mozza-Menu-Centurion.pdf") == "Osteria-Mozza"
    assert menus.match_venue_to_filename("HighHouse", ["HighHouse-Menu_Centurion.pdf"]) == "HighHouse-Menu_Centurion.pdf"
    assert menus.direct_menu_candidate_filenames("Kaya", "platinum")[0] == "Kaya-Menu_Platinum.pdf"
    assert "CapitolBistro-Menu.pdf" in menus.direct_menu_candidate_filenames("CapitolBistro", "centurion")
    assert menus.has_buffet_tag({"category": "buffet"})
    assert menus.has_buffet_tag({"app_tags": ["Table for Two", "Buffet"]})
    assert not menus.has_buffet_tag({"category": "restaurant"})
    assert not menus.MENU_FILENAME_RE.match("../../outside-Menu.pdf")
    assert not menus.MENU_FILENAME_RE.match("subdir/VUE-Menu_Platinum.pdf")
    duplicates = [
        "Osteria-Mozza-Menu_Platinum.pdf",
        "Osteria-Mozza-Menu-Platinum.pdf",
    ]
    assert menus.match_venue_candidates("Osteria Mozza", duplicates) == sorted(duplicates)
    assert menus.match_venue_candidates("Osteria Mozza", list(reversed(duplicates))) == sorted(duplicates)
    assert menus.match_venue_to_filename("Osteria Mozza", duplicates) is None


def test_cache_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        menus.maybe_save_pdf(b"%PDF test", "../../outside-Menu.pdf", tmp_path)


def test_one_asset_cannot_be_claimed_by_two_venues():
    claims = {}

    assert menus.claim_menu_asset(claims, "platinum", "Place-Menu.pdf", "venue-a")
    assert not menus.claim_menu_asset(
        claims, "platinum", "Place-Menu.pdf", "venue-b"
    )


def test_cross_venue_collision_is_order_independent():
    venues = [
        {"id": "the-place", "name": "The Place"},
        {"id": "place", "name": "Place"},
    ]
    listings = {"platinum": {"Place-Menu.pdf": {}}}

    forward = menus.strongest_asset_claimants(venues, listings)
    backward = menus.strongest_asset_claimants(list(reversed(venues)), listings)

    assert forward == backward == {
        ("platinum", "Place-Menu.pdf"): {"the-place", "place"}
    }


def test_review_queue_fingerprint_ignores_time_and_order():
    first = [
        {"kind": "missing_venue_menu", "venue_id": "a", "detected_at": "one"},
        {"kind": "ambiguous_exact_match", "venue_id": "b", "detected_at": "one"},
    ]
    second = [
        {"kind": "ambiguous_exact_match", "venue_id": "b", "detected_at": "two"},
        {"kind": "missing_venue_menu", "venue_id": "a", "detected_at": "two"},
    ]

    assert menus.review_queue_sha256(first) == menus.review_queue_sha256(second)
    assert menus.review_queue_sha256(first) != menus.review_queue_sha256(first[:1])


def test_http_get_rejects_untrusted_url_and_oversized_response(monkeypatch):
    with pytest.raises(ValueError, match="Amex HTTPS"):
        menus.http_get("https://example.com/menu.pdf", 10)

    class Response:
        headers = {"Content-Length": "11"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(menus.urllib.request, "build_opener", lambda *_args: Opener())
    with pytest.raises(ValueError, match="byte limit"):
        menus.http_get("https://www.americanexpress.com/menu.pdf", 10)


def test_new_or_changed_menu_requires_review():
    entry = {
        "filename": "VUE-Menu_Platinum.pdf",
        "url": "https://www.americanexpress.com/menu/VUE-Menu_Platinum.pdf",
        "card_key": "platinum",
        "card_label": "Platinum",
        "aem_created": "today",
        "aem_uuid": "uuid",
    }
    previous = {
        "status": "published",
        "filename": entry["filename"],
        "url": entry["url"],
        "card": "platinum",
        "sha256": "a" * 64,
    }

    changed = menus.venue_menu_info(
        {"name": "VUE"}, entry, b"%PDF changed", "2026-08-30T00:00:00Z", previous
    )

    assert changed["status"] == "review_required"
    assert changed["url"] is None
    assert changed["previous_sha256"] == "a" * 64


def test_failed_observation_does_not_advance_previous_freshness():
    entry = {
        "filename": "VUE-Menu_Platinum.pdf",
        "url": "https://www.americanexpress.com/menu/VUE-Menu_Platinum.pdf",
        "card_key": "platinum",
    }
    previous = {
        "status": "published",
        "filename": entry["filename"],
        "url": entry["url"],
        "card": "platinum",
        "sha256": "a" * 64,
        "checked_at": "2026-08-29T00:00:00Z",
    }

    result = menus.venue_menu_info(
        {"name": "VUE"}, entry, None, "2026-08-30T00:00:00Z", previous
    )

    assert result == previous


if __name__ == "__main__":
    main()
