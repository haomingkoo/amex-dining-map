"""Deterministic answers from hash-bound, page-reviewed TFT documents."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse


MAX_REPLY_LENGTH = 3900
DOCUMENT_IDENTITIES = {
    ("tft-terms", "terms"): "Table for Two - Platinum Edition Terms and Conditions",
    ("tft-faq", "faq"): "Table for Two - Frequently Asked Questions",
}
NATURAL_POLICY_CUES = (
    "eligible",
    "eligibility",
    "qualify",
    "supplementary voucher",
    "voucher used",
    "voucher redeemed",
    "cancellation",
    "cancel",
    "no show",
    "no-show",
    "blackout",
    "takeaway",
    "take away",
    "solo",
    "party size",
    "number of guests",
    "unavailable date",
    "otp",
    "face id",
    "myca",
    "reservation confirmed",
    "confirmation sms",
    "table for two terms",
    "table for two rules",
    "child",
    "children",
    "bring a guest",
    "bring guests",
    "book directly",
    "dates unavailable",
    "voucher is used",
    "account is locked",
    "account locked",
    "reservation is confirmed",
    "reservation confirmed",
    "card required",
    "card is required",
    "centurion card",
)
UNSUPPORTED_POLICY_CUES = (
    "transfer",
    "legally",
    "legal meaning",
    "interpret this",
    "my dispute",
    "am i entitled",
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _trusted_amex_url(value: Any) -> str | None:
    raw = str(value or "")
    if "\\" in raw or any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in raw
    ):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or (host != "americanexpress.com" and not host.endswith(".americanexpress.com"))
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return raw


def _time(value: Any, now: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed > now + timedelta(minutes=5):
        return None
    return parsed.astimezone(timezone.utc)


def _valid_document(document: dict, now: datetime) -> bool:
    raw_hash = document.get("raw_sha256")
    clauses = document.get("clauses")
    page_count = document.get("page_count")
    reviewed = _time(document.get("reviewed_at"), now)
    captured = _time(document.get("captured_at"), now)
    page_hashes = document.get("page_text_sha256")
    identity = (document.get("id"), document.get("kind"))
    base_valid = (
        identity in DOCUMENT_IDENTITIES
        and document.get("review_status") in {"approved", "current_baseline"}
        and document.get("title") == DOCUMENT_IDENTITIES.get(identity)
        and document.get("extractor")
        == "pypdf 6.15.0 extract_text normalized-whitespace-v1"
        and document.get("lexical_index_version") == "reviewed-topics-v1"
        and _trusted_amex_url(document.get("source_url")) is not None
        and isinstance(raw_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", raw_hash) is not None
        and isinstance(page_count, int)
        and 1 <= page_count <= 100
        and isinstance(clauses, list)
        and clauses
        and isinstance(page_hashes, list)
        and len(page_hashes) == page_count
        and all(
            isinstance(page_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", page_hash) is not None
            for page_hash in page_hashes
        )
        and reviewed is not None
        and captured is not None
    )
    if not base_valid:
        return False
    seen_ids = set()
    for clause in clauses:
        if not isinstance(clause, dict):
            return False
        clause_id = clause.get("id")
        page = clause.get("page")
        topics = clause.get("topics")
        summary = clause.get("summary")
        if (
            not isinstance(clause_id, str)
            or re.fullmatch(r"[a-z0-9-]{1,64}", clause_id) is None
            or clause_id in seen_ids
            or not isinstance(page, int)
            or not 1 <= page <= page_count
            or not isinstance(topics, list)
            or not topics
            or any(not isinstance(topic, str) or not topic for topic in topics)
            or not isinstance(summary, str)
            or not 1 <= len(summary) <= 600
        ):
            return False
        seen_ids.add(clause_id)
    return True


def _chooser() -> str:
    return (
        "Table for Two official-document help\n\n"
        "/terms eligibility - eligible card scope\n"
        "/terms benefit - voucher frequency and sharing\n"
        "/terms guests - party, extra diners, children\n"
        "/terms booking - reservation and confirmation rules\n"
        "/terms cancellation - merchant policy boundary\n"
        "/faq unavailable dates - why a date may not appear\n"
        "/faq party size - why guest counts disappear\n"
        "/faq otp - login and account-lock support\n"
        "/faq voucher used - shared-account troubleshooting\n\n"
        "I summarize reviewed official pages and do not decide personal eligibility, interpret a dispute, or make a booking."
    )


def _fallback(documents: list[dict], restricted_kind: str | None) -> str:
    labels = []
    for document in documents:
        if restricted_kind and document.get("kind") != restricted_kind:
            continue
        url = _trusted_amex_url(document.get("source_url"))
        if url:
            labels.append(f"Official {str(document.get('kind')).upper()}: {url}")
    source_lines = "\n".join(labels)
    message = (
        "I could not map that to one reviewed Table for Two policy topic, so I will not interpret or guess. "
        "Try /terms or /faq for supported topics."
    )
    if source_lines:
        message += f"\n{source_lines}"
    return message[:MAX_REPLY_LENGTH]


def _review_pending(document: dict) -> str:
    kind = str(document.get("kind") or "document").upper()
    url = _trusted_amex_url(document.get("source_url"))
    message = (
        f"The current official {kind} version has not passed page-level review, so I will not summarize it."
    )
    if url:
        message += f"\nOfficial {kind}: {url}"
    return message[:MAX_REPLY_LENGTH]


def _review_notice(document: dict) -> str:
    if not document.get("review_required"):
        return ""
    observed = document.get("observed_sha256")
    version = f" ({observed[:12]})" if isinstance(observed, str) else ""
    return (
        f"Update pending review: a newer official {str(document.get('kind') or 'document').upper()}"
        f"{version} was observed. The answer below remains bound to the last reviewed version.\n\n"
    )


def _score(query: str, clause: dict) -> float:
    score = 0.0
    for topic in clause.get("topics") or []:
        normalized = _normalize(str(topic))
        if normalized and re.search(rf"(?:^| )({re.escape(normalized)})(?: |$)", query):
            score += len(normalized.split()) * 3 + min(len(normalized), 40) / 40
    return score


def answer(message: str, catalog: dict, now: datetime) -> str | None:
    """Return a fixed reviewed document answer, a bounded fallback, or None."""
    compact = " ".join(message.strip().split())
    lowered = compact.casefold()
    restricted_kind = None
    if lowered == "/terms" or lowered.startswith("/terms "):
        restricted_kind = "terms"
        query = compact[len("/terms") :].strip()
    elif lowered == "/faq" or lowered.startswith("/faq "):
        restricted_kind = "faq"
        query = compact[len("/faq") :].strip()
    else:
        if compact.startswith("/"):
            return None
        normalized_message = _normalize(compact)
        if not any(cue in normalized_message for cue in NATURAL_POLICY_CUES):
            return None
        query = compact
    if not query:
        return _chooser()[:MAX_REPLY_LENGTH]

    documents = catalog.get("documents") or []
    if not isinstance(documents, list):
        return "Official Table for Two document metadata is unavailable, so I will not summarize it."
    normalized_query = _normalize(query)
    if any(cue in normalized_query for cue in UNSUPPORTED_POLICY_CUES):
        return _fallback(documents, restricted_kind)
    candidates = []
    pending = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if restricted_kind and document.get("kind") != restricted_kind:
            continue
        if not _valid_document(document, now):
            pending.append(document)
            continue
        for clause in document.get("clauses") or []:
            score = _score(normalized_query, clause)
            if score > 0:
                candidates.append((score, document, clause))
    candidates.sort(key=lambda item: (-item[0], item[1]["id"], item[2]["id"]))
    if not candidates:
        if pending and restricted_kind:
            return _review_pending(pending[0])
        return _fallback(documents, restricted_kind)
    best = candidates[0]
    if len(candidates) > 1 and best[0] - candidates[1][0] < 1.5:
        return _fallback(documents, restricted_kind)
    _, document, clause = best
    page = clause.get("page")
    if not isinstance(page, int) or not 1 <= page <= document["page_count"]:
        return _review_pending(document)
    captured = _time(document.get("captured_at"), now)
    if captured is None:
        return _review_pending(document)
    label = "T&C" if document["kind"] == "terms" else "FAQ"
    citation = (
        f"Official {label} - p. {page} - version {document['raw_sha256'][:12]} - "
        f"captured {captured.strftime('%d %b %Y, %H:%M UTC')}"
    )
    answer_text = (
        f"{_review_notice(document)}{document['title']}\n\n{clause['summary']}\n\n"
        f"{citation}\n{document['source_url']}\n\n"
        "This is a source summary, not a personal eligibility decision, legal interpretation, reservation, or availability guarantee."
    )
    return answer_text[:MAX_REPLY_LENGTH]
