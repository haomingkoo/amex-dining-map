from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import apply_tft_menu_review, fetch_tft_menus


PDF_B = b"%PDF-1.4\nmenu observation B\n%%EOF\n"
PDF_C = b"%PDF-1.4\nmenu observation C\n%%EOF\n"
ROOT = Path(__file__).resolve().parents[2]


def test_observation_b_remains_retrievable_after_c(tmp_path):
    path_b = fetch_tft_menus.retain_review_pdf(PDF_B, tmp_path)
    path_c = fetch_tft_menus.retain_review_pdf(PDF_C, tmp_path)

    assert path_b != path_c
    assert path_b.read_bytes() == PDF_B
    assert path_c.read_bytes() == PDF_C


def test_existing_mismatched_hash_path_fails_closed(tmp_path):
    digest = hashlib.sha256(PDF_B).hexdigest()
    (tmp_path / f"{digest}.pdf").write_bytes(PDF_C)

    with pytest.raises(ValueError, match="hash collision"):
        fetch_tft_menus.retain_review_pdf(PDF_B, tmp_path)


def test_repository_archive_covers_current_observed_menu_versions():
    source = json.loads((ROOT / "data/table-for-two.json").read_text())
    expected = {}
    for venue in source.get("venues") or []:
        for menu in (venue.get("menu_pdfs") or {}).values():
            if menu.get("status") == "published" and menu.get("sha256"):
                expected[menu["sha256"]] = menu["bytes"]
    for item in (source.get("menu_source") or {}).get("review_queue") or []:
        if item.get("sha256") and item.get("bytes"):
            expected[item["sha256"]] = item["bytes"]

    archive = ROOT / "data/reviews/tft-menu-pdfs"
    assert expected
    for digest, byte_count in expected.items():
        payload = (archive / f"{digest}.pdf").read_bytes()
        assert len(payload) == byte_count
        assert hashlib.sha256(payload).hexdigest() == digest

    for path in archive.iterdir():
        assert path.is_file()
        assert path.name == f"{hashlib.sha256(path.read_bytes()).hexdigest()}.pdf"


def test_approval_defaults_to_retained_candidate_bytes(tmp_path, monkeypatch):
    retained = fetch_tft_menus.retain_review_pdf(PDF_B, tmp_path / "archive")
    manifest = {
        "decision": "approved",
        "asset_sha256": hashlib.sha256(PDF_B).hexdigest(),
        "bytes": len(PDF_B),
    }
    data = {"menu_source": {"review_queue": [1]}}
    manifest_path = tmp_path / "review.json"
    data_path = tmp_path / "data.json"
    updates_path = tmp_path / "updates.json"
    catalog_path = tmp_path / "catalog.json"
    manifest_path.write_text(json.dumps(manifest))
    data_path.write_text(json.dumps(data))
    captured = {}

    def apply(payload, supplied_manifest, pdf_bytes=None):
        captured["pdf"] = pdf_bytes
        return payload, None

    monkeypatch.setattr(apply_tft_menu_review.tft_menu_reviews, "apply_review", apply)
    monkeypatch.setattr(
        apply_tft_menu_review.tft_menu_reviews,
        "verify_decision_receipts",
        lambda _payload: None,
    )
    monkeypatch.setattr(apply_tft_menu_review, "_receipt", lambda *_args: {})
    monkeypatch.setattr(apply_tft_menu_review, "_catalog", lambda *_args: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_tft_menu_review.py",
            "--manifest",
            str(manifest_path),
            "--pdf-root",
            str(retained.parent),
            "--data",
            str(data_path),
            "--updates",
            str(updates_path),
            "--catalog",
            str(catalog_path),
        ],
    )

    assert apply_tft_menu_review.main() == 0
    assert captured["pdf"] == PDF_B


@pytest.mark.parametrize("state", ["missing", "tampered"])
def test_default_approval_fails_when_retained_candidate_is_unusable(
    tmp_path, monkeypatch, state
):
    digest = hashlib.sha256(PDF_B).hexdigest()
    root = tmp_path / "archive"
    root.mkdir()
    if state == "tampered":
        (root / f"{digest}.pdf").write_bytes(PDF_C)
    manifest_path = tmp_path / "review.json"
    data_path = tmp_path / "data.json"
    manifest_path.write_text(
        json.dumps(
            {"decision": "approved", "asset_sha256": digest, "bytes": len(PDF_B)}
        )
    )
    data_path.write_text(json.dumps({"menu_source": {"review_queue": []}}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_tft_menu_review.py",
            "--manifest",
            str(manifest_path),
            "--pdf-root",
            str(root),
            "--data",
            str(data_path),
        ],
    )

    with pytest.raises(ValueError, match="observation archive|content-addressed path"):
        apply_tft_menu_review.main()


PUBLISHED_MENU = {
    "status": "published",
    "url": "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining/Sarnies-Menu.pdf",
    "filename": "Sarnies-Menu.pdf",
    "card": "platinum",
    "label": "Platinum",
    "checked_at": "2026-09-08T23:49:22Z",
    "first_seen_at": "2026-09-02T22:00:42Z",
    "last_seen_at": "2026-09-08T23:49:22Z",
    "sha256": "3c1a4122d5d589755dce2fb4aaa677385edf65ccc0cc412681023a811ce03f95",
    "bytes": 3298511,
    "aem_created": "Tue Jun 30 2026 02:40:36 GMT-0700",
    "changed_at": None,
    "review_manifest_sha256": "0017058c0dfb0baf2f7293628e87e6ddc0e4b52e101d33371ed0cfe868ff2607",
    "reviewed_at": "2026-09-02T22:01:32Z",
}


def test_one_listing_miss_does_not_unpublish_a_reviewed_menu():
    """A menu absent from a single listing fetch must survive that fetch.

    A transient discovery miss wiped Sarnies' approved menu on 2026-09-09 while
    the PDF was still live at its recorded URL. That wedged the whole pipeline:
    the approved receipt still claimed the menu was published, so
    verify_decision_receipts raised, and because fetch_tft_menus calls that
    verifier on startup the fetcher could no longer re-discover and republish.
    """
    info = fetch_tft_menus.venue_menu_info(
        {"id": "tft-sarnies", "name": "Sarnies", "category": "cafe"},
        None,
        None,
        "2026-09-09T23:48:32Z",
        dict(PUBLISHED_MENU),
    )

    assert info["status"] == "published"
    assert info["sha256"] == PUBLISHED_MENU["sha256"]
    assert info["review_manifest_sha256"] == PUBLISHED_MENU["review_manifest_sha256"]


def test_a_listing_miss_still_unpublishes_a_menu_that_was_never_published():
    """Retention is only for state worth keeping, so a non-published menu still clears."""
    info = fetch_tft_menus.venue_menu_info(
        {"id": "tft-example", "name": "Example", "category": "cafe"},
        None,
        None,
        "2026-09-09T23:48:32Z",
        {"status": "no_pdf_found", "sha256": None, "filename": None},
    )

    assert info["status"] == "no_pdf_found"
    assert info["sha256"] is None


def test_a_buffet_listing_miss_keeps_reporting_buffet():
    """The buffet branch must not be swallowed by the retention guard."""
    info = fetch_tft_menus.venue_menu_info(
        {"id": "tft-buffet", "name": "Buffet Place", "category": "buffet"},
        None,
        None,
        "2026-09-09T23:48:32Z",
        {},
    )

    assert info["status"] == "buffet_no_menu_expected"
