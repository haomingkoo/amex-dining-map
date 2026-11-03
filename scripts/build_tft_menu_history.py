#!/usr/bin/env python3
"""Keep every published Table for Two menu PDF version per venue and card, with dish-level changes."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DEFAULT_SOURCE = Path("data/table-for-two.json")
DEFAULT_OUTPUT = Path("data/tft-menu-history.json")
DEFAULT_PDF_ROOT = Path("data/reviews/tft-menu-pdfs")
PUBLIC_ARCHIVE_DIR = "menu-archive"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def empty_history() -> dict:
    return {"schema_version": 1, "program_id": "table-for-two", "generated_at": None, "venues": {}}


def _published_menus(venue: dict) -> dict[str, dict]:
    menus = {card: m for card, m in (venue.get("menu_pdfs") or {}).items() if isinstance(m, dict)}
    # Before Centurion was tracked, the single menu_pdf was the Platinum menu.
    if not menus and isinstance(venue.get("menu_pdf"), dict):
        menus = {"platinum": venue["menu_pdf"]}
    return {card: m for card, m in menus.items()
            if m.get("status") == "published" and SHA_RE.match(str(m.get("sha256") or ""))}


def record_versions(data: dict, source: dict, observed_at: str) -> None:
    for venue in source.get("venues") or []:
        venue_id = venue.get("id")
        if not venue_id:
            continue
        for card, menu in _published_menus(venue).items():
            versions = data["venues"].setdefault(venue_id, {}).setdefault(card, [])
            if versions and versions[-1]["sha256"] == menu["sha256"]:
                versions[-1]["last_seen"] = max(versions[-1]["last_seen"], observed_at)
                continue
            versions.append({
                "sha256": menu["sha256"],
                "filename": menu.get("filename") or "",
                "source_url": menu.get("url") or "",
                "bytes": menu.get("bytes"),
                "first_seen": observed_at,
                "last_seen": observed_at,
            })


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def _menu_lines(text: str) -> list[tuple[str, str]]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        key = re.sub(r"[^0-9a-z]", "", line.casefold())
        # Page numbers and stray glyphs are layout, not dishes.
        if len(key) >= 3 and not key.isdigit():
            lines.append((key, line))
    return lines


REWRAP_MIN_KEY = 12


def _changed_lines(lines: list[tuple[str, str]], other: list[tuple[str, str]]) -> list[str]:
    keys, joined = {k for k, _ in other}, "".join(k for k, _ in other)
    changed = []
    for index, (key, line) in enumerate(lines):
        prev_key = lines[index - 1][0] if index else ""
        next_key = lines[index + 1][0] if index + 1 < len(lines) else ""
        # A line, or a line joined to its neighbour, that still appears in the other text was only rewrapped.
        spans = [key, prev_key + key, key + next_key]
        if key in keys or any(len(span) >= REWRAP_MIN_KEY and span in joined for span in spans):
            continue
        changed.append(line)
    return list(dict.fromkeys(changed))


def dish_changes(before: str, after: str) -> dict:
    old, new = _menu_lines(before), _menu_lines(after)
    return {"added": _changed_lines(new, old), "removed": _changed_lines(old, new)}


def fill_changes(data: dict, pdf_root: Path, text_of: Callable[[Path], str] = pdf_text) -> None:
    for cards in data["venues"].values():
        for versions in cards.values():
            for index, version in enumerate(versions):
                path = pdf_root / f"{version['sha256']}.pdf"
                version["archive_path"] = f"{PUBLIC_ARCHIVE_DIR}/{version['sha256']}.pdf" if path.exists() else None
                if version.get("changes") is not None:
                    continue
                previous = versions[index - 1] if index else None
                previous_path = previous and pdf_root / f"{previous['sha256']}.pdf"
                if previous_path and previous_path.exists() and path.exists():
                    version["changes"] = dish_changes(text_of(previous_path), text_of(path))
                else:
                    version["changes"] = None


def stage_archive(data: dict, pdf_root: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for cards in data["venues"].values():
        for versions in cards.values():
            for version in versions:
                if version.get("archive_path"):
                    shutil.copy2(pdf_root / f"{version['sha256']}.pdf", output_dir / f"{version['sha256']}.pdf")
                    copied += 1
    return copied


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def backfill_from_git(data: dict, source: Path) -> None:
    for line in reversed(_git("log", "--format=%H %cI", "--", str(source)).splitlines()):
        commit, committed_at = line.split(" ", 1)
        try:
            snapshot = json.loads(_git("show", f"{commit}:{source}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print(f"skip {commit[:8]}: {error}", file=sys.stderr)
            continue
        observed = datetime.fromisoformat(committed_at).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record_versions(data, snapshot, observed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pdf-root", type=Path, default=DEFAULT_PDF_ROOT)
    parser.add_argument("--backfill-from-git", action="store_true", help="rebuild from every committed roster")
    parser.add_argument("--stage-archive", type=Path, help="copy archived PDFs here and skip rebuilding")
    args = parser.parse_args()
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    if args.stage_archive:
        data = json.loads(args.output.read_text(encoding="utf-8"))
        print(f"staged {stage_archive(data, args.pdf_root, args.stage_archive)} menu PDFs")
        return 0

    if args.backfill_from_git or not args.output.exists():
        data = empty_history()
        backfill_from_git(data, args.source)
    else:
        data = json.loads(args.output.read_text(encoding="utf-8"))
    source = json.loads(args.source.read_text(encoding="utf-8"))
    record_versions(data, source, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    fill_changes(data, args.pdf_root)
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    versions = sum(len(v) for cards in data["venues"].values() for v in cards.values())
    print(f"menu history: {len(data['venues'])} venues, {versions} versions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
