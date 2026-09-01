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

from scripts import tft_document_reviews
from scripts.official_document_reviews import manifest_sha256, verify_version


SOURCE = Path("data/table-for-two.json")
REVIEW_ROOT = Path("data/reviews/official-documents")
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
MAX_PAGE_CHARACTERS = 50_000
DOCUMENTS = {
    document_id: (config["url_key"], config["hash_key"])
    for document_id, config in tft_document_reviews.DOCUMENTS.items()
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


def verify(
    source_path: Path,
    review_root: Path,
    pdf_dir: Path | None,
    approved_pdf_root: Path = tft_document_reviews.PDF_ROOT,
) -> int:
    if pypdf.__version__ != "6.16.2":
        raise ValueError(f"expected pypdf 6.16.2, found {pypdf.__version__}")
    source = json.loads(source_path.read_text())
    source_hashes = source.get("source_documents") or {}
    pending = 0
    for document_id, (url_key, hash_key) in DOCUMENTS.items():
        url = source.get(url_key)
        expected_hash = source_hashes.get(hash_key)
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise ValueError(f"invalid source hash for {document_id}")
        pdf_path = (
            pdf_dir / f"{document_id}.pdf"
            if pdf_dir
            else approved_pdf_root / document_id / f"{expected_hash}.pdf"
        )
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else fetch_pdf(str(url))
        actual_hash = hashlib.sha256(pdf_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"raw PDF hash mismatch for {document_id}")
        state = (source.get("document_reviews") or {}).get(document_id)
        if not isinstance(state, dict):
            raise ValueError(f"missing retained review state for {document_id}")
        approved_hash = state.get("approved_sha256")
        if not isinstance(approved_hash, str) or re.fullmatch(r"[0-9a-f]{64}", approved_hash) is None:
            raise ValueError(f"invalid approved hash for {document_id}")
        approved_manifest_path = review_root / document_id / f"{approved_hash}.json"
        approved_pdf_path = approved_pdf_root / document_id / f"{approved_hash}.pdf"
        if not approved_manifest_path.exists() or not approved_pdf_path.exists():
            raise ValueError(f"retained approved evidence is missing for {document_id}")
        approved_manifest = json.loads(approved_manifest_path.read_text())
        reviewed = verify_version(
            tft_document_reviews.spec(source, document_id),
            approved_pdf_path.read_bytes(),
            approved_manifest,
        )
        if (
            reviewed["raw_sha256"] != approved_hash
            or state.get("approved_manifest_sha256") != manifest_sha256(reviewed)
        ):
            raise ValueError(f"approved review identity mismatch for {document_id}")
        if state.get("pending_events"):
            raise ValueError(
                f"pending owner events require review-application retry for {document_id}"
            )
        if actual_hash != approved_hash:
            if (
                state.get("status") != "review_required"
                or state.get("review_required") is not True
                or state.get("observed_sha256") != actual_hash
            ):
                raise ValueError(f"unreviewed observed state mismatch for {document_id}")
            print(
                f"{document_id}: observed hash verified; retained approved "
                f"{approved_hash[:12]} pending review"
            )
            pending += 1
            continue
        if state.get("status") != "approved" or state.get("review_required") is not False:
            raise ValueError(f"approved state mismatch for {document_id}")
        print(
            f"{document_id}: raw hash, {reviewed['page_count']} pages, "
            f"and {len(reviewed['clauses'])} reviewed clauses retained"
        )
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--approved-pdf-root", type=Path, default=tft_document_reviews.PDF_ROOT)
    args = parser.parse_args()
    pending = verify(
        args.source, args.review_root, args.pdf_dir, args.approved_pdf_root
    )
    if pending:
        print(
            f"{pending} current document(s) retain the prior reviewed projection "
            "while the observed successor awaits review"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
