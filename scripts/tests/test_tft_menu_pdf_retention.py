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
