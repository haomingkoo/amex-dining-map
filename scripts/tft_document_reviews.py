#!/usr/bin/env python3
"""Review state and application helpers for fixed Table for Two documents."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROGRAM = "Table for Two"
PROGRAM_ID = "table-for-two"
ROUTE = "#/table-for-two"
REVIEW_ROOT = Path("data/reviews/official-documents")
PDF_ROOT = Path("data/reviews/official-document-pdfs")
TRANSITION_ROOT = Path("data/reviews/official-document-transitions")
MAX_PDF_BYTES = 5 * 1024 * 1024
HASH = re.compile(r"^[0-9a-f]{64}$")
DOCUMENTS = {
    "tft-terms": {
        "kind": "terms",
        "title": "Table for Two - Platinum Edition Terms and Conditions",
        "url_key": "terms_url",
        "hash_key": "terms_sha256",
    },
    "tft-faq": {
        "kind": "faq",
        "title": "Table for Two - Frequently Asked Questions",
        "url_key": "faq_url",
        "hash_key": "faq_sha256",
    },
}


def manifest_sha256(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def spec(source: dict[str, Any], document_id: str) -> Any:
    try:
        from scripts.official_document_reviews import DocumentSpec
    except ModuleNotFoundError:
        from official_document_reviews import DocumentSpec

    config = DOCUMENTS.get(document_id)
    if config is None:
        raise ValueError(f"unknown TFT document: {document_id}")
    source_url = source.get(config["url_key"])
    if not isinstance(source_url, str):
        raise ValueError(f"missing fixed source URL for {document_id}")
    return DocumentSpec(
        document_id=document_id,
        program=PROGRAM,
        program_id=PROGRAM_ID,
        route=ROUTE,
        kind=config["kind"],
        title=config["title"],
        source_url=source_url,
    )


def manifest_path(document_id: str, raw_sha256: str, root: Path = REVIEW_ROOT) -> Path:
    return root / document_id / f"{raw_sha256}.json"


def pdf_path(document_id: str, raw_sha256: str, root: Path = PDF_ROOT) -> Path:
    return root / document_id / f"{raw_sha256}.pdf"


def retain_observed_pdf(
    document_id: str, pdf_bytes: bytes, root: Path = PDF_ROOT
) -> tuple[str, Path]:
    if document_id not in DOCUMENTS:
        raise ValueError(f"unknown TFT document: {document_id}")
    if not pdf_bytes.startswith(b"%PDF") or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError(f"observed {document_id} source is not a bounded PDF")
    raw_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    destination = pdf_path(document_id, raw_sha256, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as retained:
            retained.write(pdf_bytes)
    except FileExistsError:
        if destination.read_bytes() != pdf_bytes:
            raise ValueError(f"retained PDF hash collision for {document_id}")
    return raw_sha256, destination


def transition_path(
    document_id: str,
    before_sha256: str,
    after_sha256: str,
    root: Path = TRANSITION_ROOT,
) -> Path:
    return root / document_id / f"{before_sha256}-to-{after_sha256}.json"


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def baseline_state(
    source: dict[str, Any], document_id: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    config = DOCUMENTS[document_id]
    observed = (source.get("source_documents") or {}).get(config["hash_key"])
    if not _valid_hash(observed) or manifest.get("raw_sha256") != observed:
        raise ValueError(f"baseline manifest does not match observed {document_id}")
    return {
        "status": "approved",
        "review_required": False,
        "observed_sha256": observed,
        "approved_sha256": observed,
        "approved_manifest_sha256": manifest_sha256(manifest),
        "approved_captured_at": manifest.get("captured_at"),
        "reviewed_at": manifest.get("reviewed_at"),
        "review_item": None,
    }


def refresh_states(
    observed_hashes: dict[str, str],
    existing_source: dict[str, Any] | None,
    checked_at: str,
) -> dict[str, dict[str, Any]]:
    existing_source = existing_source or {}
    prior_states = existing_source.get("document_reviews") or {}
    states: dict[str, dict[str, Any]] = {}
    for document_id, config in DOCUMENTS.items():
        observed = observed_hashes.get(config["hash_key"])
        if not _valid_hash(observed):
            raise ValueError(f"invalid observed hash for {document_id}")
        prior = prior_states.get(document_id)
        if not isinstance(prior, dict) or not _valid_hash(prior.get("approved_sha256")):
            raise RuntimeError(
                f"{document_id} has no approved retained baseline; initialize document_reviews first"
            )
        approved = prior["approved_sha256"]
        if observed == approved:
            state = copy.deepcopy(prior)
            state.update(
                status="approved",
                review_required=False,
                observed_sha256=observed,
                review_item=None,
            )
            states[document_id] = state
            continue
        prior_item = prior.get("review_item") or {}
        same_pending_version = (
            prior.get("observed_sha256") == observed
            and prior.get("approved_sha256") == approved
            and prior_item.get("kind") == "unreviewed_official_document"
        )
        detected_at = (
            prior_item.get("detected_at") if same_pending_version else checked_at
        )
        states[document_id] = {
            **copy.deepcopy(prior),
            "status": "review_required",
            "review_required": True,
            "observed_sha256": observed,
            "review_item": {
                "source_id": f"table-for-two-document-{document_id}",
                "kind": "unreviewed_official_document",
                "detected_at": detected_at,
                "document_id": document_id,
                "source_url": existing_source.get(config["url_key"]),
                "observed_sha256": observed,
                "approved_sha256": approved,
            },
        }
    return states


def approved_hash(source: dict[str, Any], document_id: str) -> str | None:
    state = (source.get("document_reviews") or {}).get(document_id) or {}
    value = state.get("approved_sha256")
    return value if _valid_hash(value) else None


def source_review_required(source: dict[str, Any]) -> bool:
    return any(
        isinstance(state, dict) and state.get("review_required") is True
        for state in (source.get("document_reviews") or {}).values()
    )
