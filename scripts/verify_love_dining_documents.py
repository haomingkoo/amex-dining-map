#!/usr/bin/env python3
"""Verify current Love Dining PDF review manifests against fixed Amex sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.official_document_reviews import DocumentSpec, manifest_sha256, verify_version
from scripts.verify_tft_official_documents import fetch_pdf


META = Path("data/love-dining-source.json")
REVIEW_ROOT = Path("data/reviews/official-documents")
DOCUMENTS = {
    "restaurants": (
        "love-dining-restaurant-terms",
        "Love Dining Restaurants Terms and Conditions",
    ),
    "hotels": (
        "love-dining-hotel-terms",
        "Love Dining Hotels Terms and Conditions",
    ),
}


def document_spec(document_id: str, title: str, source_url: str) -> DocumentSpec:
    return DocumentSpec(
        document_id=document_id,
        program="Love Dining",
        program_id="love-dining",
        route="#/love-dining",
        kind="terms",
        title=title,
        source_url=source_url,
    )


def verify(meta_path: Path, review_root: Path, pdf_dir: Path | None) -> int:
    meta = json.loads(meta_path.read_text())
    pending = 0
    for key, (document_id, title) in DOCUMENTS.items():
        source_url = (meta.get("terms") or {}).get(key)
        current_hash = (meta.get("terms_hashes") or {}).get(key)
        decision_path = review_root / document_id / f"{current_hash}.json"
        if not decision_path.exists():
            print(f"{document_id}: current hash verified; page review pending")
            pending += 1
            continue
        pdf_path = pdf_dir / f"{key}.pdf" if pdf_dir else None
        pdf_bytes = pdf_path.read_bytes() if pdf_path else fetch_pdf(str(source_url))
        manifest = json.loads(decision_path.read_text())
        reviewed = verify_version(
            document_spec(document_id, title, str(source_url)), pdf_bytes, manifest
        )
        if reviewed["raw_sha256"] != current_hash:
            raise ValueError(f"current metadata hash mismatch for {document_id}")
        if (meta.get("reviewed_terms_hashes") or {}).get(key) == current_hash and (
            meta.get("reviewed_terms_manifest_sha256") or {}
        ).get(key) != manifest_sha256(reviewed):
            raise ValueError(f"reviewed manifest identity mismatch for {document_id}")
        print(
            f"{document_id}: raw hash, {reviewed['page_count']} pages, "
            f"and {len(reviewed['clauses'])} reviewed clauses verified"
        )
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, default=META)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    parser.add_argument("--pdf-dir", type=Path)
    args = parser.parse_args()
    pending = verify(args.meta, args.review_root, args.pdf_dir)
    if pending:
        print(f"{pending} current Love Dining document(s) await page review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
