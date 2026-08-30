#!/usr/bin/env python3
"""Reproduce hash and page-text evidence for reviewed official TFT PDFs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pypdf
from pypdf import PdfReader


SOURCE = Path("data/table-for-two.json")
REVIEW_ROOT = Path("data/reviews/official-documents")
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
MAX_PAGE_CHARACTERS = 50_000
EXTRACTOR = "pypdf 6.15.0 extract_text normalized-whitespace-v1"
DOCUMENTS = {
    "tft-terms": ("terms_url", "terms_sha256"),
    "tft-faq": ("faq_url", "faq_sha256"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        raise ValueError(f"unexpected redirect for fixed official document: {code}")


def fetch_pdf(url: str) -> bytes:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or (host != "americanexpress.com" and not host.endswith(".americanexpress.com"))
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("document URL is not a fixed Amex HTTPS source")
    request = urllib.request.Request(
        url, headers={"User-Agent": "AmexExplorerDocumentVerifier/1.0"}
    )
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=20) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_PDF_BYTES:
            raise ValueError("official PDF exceeds byte cap")
        payload = response.read(MAX_PDF_BYTES + 1)
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("official PDF exceeds byte cap")
    return payload


def page_hashes(pdf_bytes: bytes) -> list[str]:
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("official document is not a PDF")
    reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
        raise ValueError("unsupported official PDF page structure")
    hashes = []
    for page in reader.pages:
        normalized = " ".join((page.extract_text() or "").split())
        if not normalized or len(normalized) > MAX_PAGE_CHARACTERS:
            raise ValueError("official PDF page text is empty or oversized")
        hashes.append(hashlib.sha256(normalized.encode()).hexdigest())
    return hashes


def verify(source_path: Path, review_root: Path, pdf_dir: Path | None) -> int:
    if pypdf.__version__ != "6.15.0":
        raise ValueError(f"expected pypdf 6.15.0, found {pypdf.__version__}")
    source = json.loads(source_path.read_text())
    source_hashes = source.get("source_documents") or {}
    pending = 0
    for document_id, (url_key, hash_key) in DOCUMENTS.items():
        url = source.get(url_key)
        expected_hash = source_hashes.get(hash_key)
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise ValueError(f"invalid source hash for {document_id}")
        pdf_path = pdf_dir / f"{document_id}.pdf" if pdf_dir else None
        pdf_bytes = pdf_path.read_bytes() if pdf_path else fetch_pdf(str(url))
        actual_hash = hashlib.sha256(pdf_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"raw PDF hash mismatch for {document_id}")
        decision_path = review_root / document_id / f"{actual_hash}.json"
        if not decision_path.exists():
            print(f"{document_id}: current hash verified; page review pending")
            pending += 1
            continue
        decision = json.loads(decision_path.read_text())
        hashes = page_hashes(pdf_bytes)
        if (
            decision.get("source_url") != url
            or decision.get("raw_sha256") != actual_hash
            or decision.get("extractor") != EXTRACTOR
            or decision.get("page_count") != len(hashes)
            or decision.get("page_text_sha256") != hashes
        ):
            raise ValueError(f"review evidence mismatch for {document_id}")
        print(f"{document_id}: raw hash and {len(hashes)} page hashes verified")
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    parser.add_argument("--pdf-dir", type=Path)
    args = parser.parse_args()
    pending = verify(args.source, args.review_root, args.pdf_dir)
    if pending:
        print(f"{pending} current document(s) have no reviewed clause projection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
