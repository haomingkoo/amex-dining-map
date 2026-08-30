from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_tft_official_documents.py"
SPEC = importlib.util.spec_from_file_location("verify_tft_official_documents", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)
ROOT = MODULE_PATH.parents[1]


def test_page_hashes_are_deterministic_normalized_text(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        is_encrypted = False
        pages = [Page("One\n  two"), Page("Three\t four")]

    monkeypatch.setattr(MODULE, "PdfReader", lambda *_args, **_kwargs: Reader())

    first = MODULE.page_hashes(b"%PDF fake")
    second = MODULE.page_hashes(b"%PDF fake")

    assert first == second
    assert len(first) == 2
    assert all(len(value) == 64 for value in first)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.americanexpress.com/file.pdf",
        "https://evil.example/file.pdf",
        "https://user@www.americanexpress.com/file.pdf",
    ],
)
def test_fetch_rejects_non_fixed_sources_before_network(monkeypatch, url: str):
    monkeypatch.setattr(
        MODULE.urllib.request,
        "build_opener",
        lambda *_args: (_ for _ in ()).throw(AssertionError("network should not run")),
    )

    with pytest.raises(ValueError):
        MODULE.fetch_pdf(url)


def test_non_pdf_and_empty_page_fail_closed(monkeypatch):
    with pytest.raises(ValueError, match="not a PDF"):
        MODULE.page_hashes(b"not a pdf")

    class EmptyReader:
        is_encrypted = False
        pages = [type("Page", (), {"extract_text": lambda self: ""})()]

    monkeypatch.setattr(MODULE, "PdfReader", lambda *_args, **_kwargs: EmptyReader())
    with pytest.raises(ValueError, match="empty or oversized"):
        MODULE.page_hashes(b"%PDF fake")


def _offline_pdf_dir(tmp_path: Path) -> Path:
    pdf_dir = tmp_path / "observed"
    pdf_dir.mkdir()
    source = json.loads((ROOT / "data/table-for-two.json").read_text())
    for document_id, (_url_key, hash_key) in MODULE.DOCUMENTS.items():
        raw_hash = source["source_documents"][hash_key]
        cached = (
            ROOT
            / "data/reviews/official-document-pdfs"
            / document_id
            / f"{raw_hash}.pdf"
        )
        (pdf_dir / f"{document_id}.pdf").write_bytes(cached.read_bytes())
    return pdf_dir


def test_current_retained_reviews_verify_offline(tmp_path):
    assert (
        MODULE.verify(
            ROOT / "data/table-for-two.json",
            ROOT / "data/reviews/official-documents",
            _offline_pdf_dir(tmp_path),
            ROOT / "data/reviews/official-document-pdfs",
        )
        == 0
    )


def test_verifier_reuses_content_addressed_observation_without_refetch(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "fetch_pdf",
        lambda *_args: (_ for _ in ()).throw(AssertionError("network should not run")),
    )

    assert (
        MODULE.verify(
            ROOT / "data/table-for-two.json",
            ROOT / "data/reviews/official-documents",
            None,
            ROOT / "data/reviews/official-document-pdfs",
        )
        == 0
    )


def test_unreviewed_successor_retains_approved_evidence_and_is_source_scoped(tmp_path):
    source = json.loads((ROOT / "data/table-for-two.json").read_text())
    pdf_dir = _offline_pdf_dir(tmp_path)
    successor = (pdf_dir / "tft-terms.pdf").read_bytes()
    successor_hash = hashlib.sha256(successor).hexdigest()
    (pdf_dir / "tft-faq.pdf").write_bytes(successor)
    source["source_documents"]["faq_sha256"] = successor_hash
    source["document_reviews"]["tft-faq"].update(
        status="review_required",
        review_required=True,
        observed_sha256=successor_hash,
    )
    source_path = tmp_path / "table-for-two.json"
    source_path.write_text(json.dumps(source))

    assert (
        MODULE.verify(
            source_path,
            ROOT / "data/reviews/official-documents",
            pdf_dir,
            ROOT / "data/reviews/official-document-pdfs",
        )
        == 1
    )


def test_unreviewed_successor_without_review_state_fails_closed(tmp_path):
    source = json.loads((ROOT / "data/table-for-two.json").read_text())
    pdf_dir = _offline_pdf_dir(tmp_path)
    successor = (pdf_dir / "tft-terms.pdf").read_bytes()
    successor_hash = hashlib.sha256(successor).hexdigest()
    (pdf_dir / "tft-faq.pdf").write_bytes(successor)
    source["source_documents"]["faq_sha256"] = successor_hash
    source_path = tmp_path / "table-for-two.json"
    source_path.write_text(json.dumps(source))

    with pytest.raises(ValueError, match="unreviewed observed state mismatch"):
        MODULE.verify(
            source_path,
            ROOT / "data/reviews/official-documents",
            pdf_dir,
            ROOT / "data/reviews/official-document-pdfs",
        )


def test_interrupted_owner_event_application_is_actionable(tmp_path):
    source = json.loads((ROOT / "data/table-for-two.json").read_text())
    source["document_reviews"]["tft-faq"]["pending_events"] = [{"id": "pending"}]
    source_path = tmp_path / "table-for-two.json"
    source_path.write_text(json.dumps(source))

    with pytest.raises(ValueError, match="review-application retry"):
        MODULE.verify(
            source_path,
            ROOT / "data/reviews/official-documents",
            _offline_pdf_dir(tmp_path),
            ROOT / "data/reviews/official-document-pdfs",
        )
