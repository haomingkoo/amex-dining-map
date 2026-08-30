from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_tft_official_documents.py"
SPEC = importlib.util.spec_from_file_location("verify_tft_official_documents", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


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
