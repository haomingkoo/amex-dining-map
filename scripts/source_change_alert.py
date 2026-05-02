#!/usr/bin/env python3
"""Build a GitHub Actions alert body when source-backed data changes.

Compares current files against HEAD so refresh workflows can open/update a
GitHub issue only when source hashes, counts, or official records move.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IGNORED_RECORD_FIELDS = {
    "lat",
    "lon",
    "lng",
    "search_text",
    "summary_ai",
    "last_synced_at",
    "last_verified_at",
    "availability",
    "slot_source_status",
}

# Nested keys (under any dict, at any depth) that flip every scrape but do not
# represent a real change to the venue. Stripped before hashing.
IGNORED_NESTED_KEYS = {
    "captured_at",
    "checked_at",
    "fetched_at",
    "last_checked_at",
    "last_synced_at",
    "last_verified_at",
}

META_FIELD_LABELS = {
    "record_count": "Record count",
    "mapped_count": "Mapped count",
    "city_count": "City count",
    "restaurant_count": "Restaurant count",
    "hotel_outlet_count": "Hotel outlet count",
    "page_count": "Source page count",
    "sha256": "Source SHA-256",
    "records_sha256": "Official records SHA-256",
    "manual_review_required": "Manual review flag",
    "source_images.participating_merchants_sha256": "Participating merchants image hash",
    "source_images.voucher_cycles_sha256": "Voucher cycles image hash",
    "terms_hashes.restaurants": "Restaurant T&C PDF hash",
    "terms_hashes.hotels": "Hotel T&C PDF hash",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_show_json(path: str) -> Any | None:
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw)


def nested_get(payload: Any, dotted_path: str) -> Any:
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "records", "restaurants", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    return []


def record_key(record: dict[str, Any]) -> str:
    return str(
        record.get("id")
        or record.get("source_merchant_id")
        or "|".join(str(record.get(field, "")) for field in ("country", "city", "name", "address"))
    )


def record_label(record: dict[str, Any]) -> str:
    parts = [
        record.get("name") or record.get("app_name") or record.get("hotel") or "Unknown",
        record.get("city") or record.get("app_area") or record.get("country"),
    ]
    return " / ".join(str(part) for part in parts if part)


def _strip_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_nested(sub)
            for key, sub in value.items()
            if key not in IGNORED_NESTED_KEYS
        }
    if isinstance(value, list):
        return [_strip_nested(item) for item in value]
    return value


def stable_record_hash(record: dict[str, Any]) -> str:
    cleaned = {
        key: _strip_nested(value)
        for key, value in record.items()
        if key not in IGNORED_RECORD_FIELDS
    }
    raw = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compare_records(old_payload: Any | None, new_payload: Any | None) -> dict[str, list[str]]:
    old_records = records_from_payload(old_payload) if old_payload is not None else []
    new_records = records_from_payload(new_payload) if new_payload is not None else []
    old_by_key = {record_key(record): record for record in old_records}
    new_by_key = {record_key(record): record for record in new_records}

    added = sorted(record_label(new_by_key[key]) for key in set(new_by_key) - set(old_by_key))
    removed = sorted(record_label(old_by_key[key]) for key in set(old_by_key) - set(new_by_key))
    changed = sorted(
        record_label(new_by_key[key])
        for key in set(old_by_key) & set(new_by_key)
        if stable_record_hash(old_by_key[key]) != stable_record_hash(new_by_key[key])
    )
    return {"added": added, "removed": removed, "changed": changed}


def append_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"{name}={value}")
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def format_limited(items: list[str], limit: int = 12) -> list[str]:
    if len(items) <= limit:
        return items
    return items[:limit] + [f"... and {len(items) - limit} more"]


def append_changelog(
    changelog_path: Path,
    program: str,
    record_diffs: list[tuple[str, dict[str, list[str]]]],
) -> None:
    """Append a dated entry to the per-program changelog.

    Only logs additions and removals — those are the interesting events
    (new venues, dropped venues). Field-level changes are intentionally
    omitted; they're noisy and most useful in the issue body, not a
    permanent log.
    """
    has_changes = any(diff["added"] or diff["removed"] for _, diff in record_diffs)
    if not has_changes:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [f"## {timestamp} — {program}", ""]
    for data_path, diff in record_diffs:
        if not (diff["added"] or diff["removed"]):
            continue
        lines.append(f"Source: `{data_path}`")
        lines.append("")
        for key, title in (("added", "Added"), ("removed", "Removed")):
            items = diff[key]
            if not items:
                continue
            lines.append(f"- **{title} ({len(items)})**")
            lines.extend(f"  - {item}" for item in format_limited(items, limit=50))
        lines.append("")

    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8").rstrip() + "\n\n"
    else:
        existing = f"# {program} change log\n\n"
    changelog_path.write_text(existing + "\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--data", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--changelog",
        help="Append a dated entry to this changelog file when records changed.",
    )
    args = parser.parse_args()

    current_meta = load_json(args.meta)
    previous_meta = git_show_json(args.meta)
    reasons: list[str] = []

    if previous_meta is not None:
        for path, label in META_FIELD_LABELS.items():
            old_value = nested_get(previous_meta, path)
            new_value = nested_get(current_meta, path)
            if old_value != new_value:
                reasons.append(f"{label}: `{old_value}` → `{new_value}`")
    elif Path(args.meta).exists():
        append_output("alert_required", "false")
        Path(args.output).write_text(
            f"# {args.program} source snapshot initialized\n\nNo previous `{args.meta}` exists in HEAD, so this run establishes the baseline.\n",
            encoding="utf-8",
        )
        return 0

    if current_meta.get("manual_review_required"):
        for reason in current_meta.get("major_change_reasons") or ["Manual source review is required."]:
            if reason not in reasons:
                reasons.append(str(reason))

    record_diffs: list[tuple[str, dict[str, list[str]]]] = []
    for data_path in args.data:
        previous_data = git_show_json(data_path)
        current_data = load_json(data_path)
        diff = compare_records(previous_data, current_data)
        if diff["added"] or diff["removed"] or diff["changed"]:
            record_diffs.append((data_path, diff))

    alert_required = bool(reasons or record_diffs)
    append_output("alert_required", "true" if alert_required else "false")

    if args.changelog:
        append_changelog(Path(args.changelog), args.program, record_diffs)

    lines = [
        f"# {args.program} source changed" if alert_required else f"# {args.program} source unchanged",
        "",
        f"- Checked at: `{now_iso()}`",
        f"- Metadata file: `{args.meta}`",
    ]
    if current_meta.get("last_checked_at") or current_meta.get("fetched_at"):
        lines.append(f"- Source cache time: `{current_meta.get('last_checked_at') or current_meta.get('fetched_at')}`")
    if current_meta.get("record_count") is not None:
        lines.append(f"- Current record count: `{current_meta.get('record_count')}`")
    lines.append("")

    source_links: list[tuple[str, str]] = []
    if isinstance(current_meta.get("official_pages"), dict):
        source_links.extend((f"official page: {key}", value) for key, value in current_meta["official_pages"].items())
    if isinstance(current_meta.get("terms"), dict):
        source_links.extend((f"terms: {key}", value) for key, value in current_meta["terms"].items())
    if current_meta.get("official_url"):
        source_links.append(("official page", current_meta["official_url"]))
    if current_meta.get("terms_url"):
        source_links.append(("terms", current_meta["terms_url"]))
    if current_meta.get("faq_url"):
        source_links.append(("FAQ", current_meta["faq_url"]))
    if current_meta.get("canonical_url"):
        source_links.append(("canonical source", current_meta["canonical_url"]))
    if current_meta.get("resolved_url"):
        source_links.append(("resolved source", current_meta["resolved_url"]))
    if source_links:
        lines.extend(["## Source Links", ""])
        lines.extend(f"- {label}: {url}" for label, url in source_links)
        lines.append("")

    if reasons:
        lines.extend(["## Source Signals", ""])
        lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")

    for data_path, diff in record_diffs:
        lines.extend([f"## Record Changes: `{data_path}`", ""])
        for key, title in (("added", "Added"), ("removed", "Removed"), ("changed", "Changed")):
            if diff[key]:
                lines.append(f"### {title}")
                lines.extend(f"- {item}" for item in format_limited(diff[key]))
                lines.append("")

    if alert_required:
        lines.extend([
            "## Review Checklist",
            "",
            "- Open the official source links in the metadata file.",
            "- Re-check benefit wording, blackout notes, closed venues, and newly added/removed records.",
            "- If the displayed wording is still correct, update the reviewed baseline or close this issue.",
        ])
    else:
        lines.append("No watched source hashes, counts, or official records changed.")

    Path(args.output).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
