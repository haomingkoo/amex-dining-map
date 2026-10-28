from __future__ import annotations

import json
import re
from pathlib import Path

import pypdf

from scripts import build_tft_guide_catalog, official_document_reviews as reviews
from scripts import verify_love_dining_documents


ROOT = Path(__file__).resolve().parents[2]
PIN_FILE = ROOT / "requirements-pdf.txt"
HISTORICAL_EXTRACTORS = {
    f"pypdf {version} extract_text normalized-whitespace-v1"
    for version in ("6.15.0", "6.16.2", "6.19.0")
}


def _pinned_version() -> str:
    pins = re.findall(r"^pypdf==(\d+\.\d+\.\d+)$", PIN_FILE.read_text(), re.MULTILINE)
    assert len(pins) == 1
    return pins[0]


def test_pin_file_is_the_only_pypdf_pin_and_is_patched():
    version = tuple(int(part) for part in _pinned_version().split("."))
    assert version >= (6, 21, 2)
    pinned_elsewhere = [
        str(path.relative_to(ROOT))
        for pattern in (".github/workflows/*.yml", "reminders/requirements*.txt", "scripts/*.py")
        for path in ROOT.glob(pattern)
        if re.search(r"pypdf\s*==\s*\d", path.read_text())
    ]
    assert pinned_elsewhere == []


def test_extractor_version_comes_from_the_pin_file():
    assert reviews.PYPDF_VERSION == _pinned_version()
    assert reviews.EXTRACTOR == f"pypdf {_pinned_version()} extract_text normalized-whitespace-v1"
    assert pypdf.__version__ == reviews.PYPDF_VERSION


def test_committed_manifest_extractors_stay_supported():
    used = {
        json.loads(path.read_text())["extractor"]
        for path in (ROOT / "data/reviews/official-documents").glob("*/*.json")
    }
    assert HISTORICAL_EXTRACTORS <= reviews.SUPPORTED_EXTRACTORS
    assert used <= reviews.SUPPORTED_EXTRACTORS
    for label in used | {reviews.EXTRACTOR}:
        assert build_tft_guide_catalog.EXTRACTOR_LABEL.fullmatch(label)
    assert not build_tft_guide_catalog.EXTRACTOR_LABEL.fullmatch(
        "pypdf latest extract_text normalized-whitespace-v1"
    )


def test_dev_requirements_and_dependabot_track_the_pin_file():
    dev = (ROOT / "reminders/requirements-dev.txt").read_text().splitlines()
    assert "-r ../requirements-pdf.txt" in dev
    assert any(re.fullmatch(r"httpx2==\d+\.\d+\.\d+", line) for line in dev)
    assert not any(line.startswith("httpx==") for line in dev)
    dependabot = (ROOT / ".github/dependabot.yml").read_text()
    assert re.search(r'directories:\s*\n\s*- "?/"?\s*\n\s*- "?/reminders"?', dependabot)
    assert "dependency-name: pypdf" not in dependabot


def test_current_love_dining_reviews_verify_offline_with_the_pinned_pypdf(tmp_path):
    meta = json.loads((ROOT / "data/love-dining-source.json").read_text())
    retained = ROOT / "data/reviews/official-document-pdfs"
    for key, (document_id, _title) in verify_love_dining_documents.DOCUMENTS.items():
        current = meta["terms_hashes"][key]
        pdf = retained / document_id / f"{current}.pdf"
        if pdf.exists():
            (tmp_path / f"{key}.pdf").write_bytes(pdf.read_bytes())

    pending = verify_love_dining_documents.verify(
        ROOT / "data/love-dining-source.json",
        ROOT / "data/reviews/official-documents",
        tmp_path,
    )

    reviewed = sum(
        (ROOT / "data/reviews/official-documents" / document_id / f"{meta['terms_hashes'][key]}.json").exists()
        for key, (document_id, _title) in verify_love_dining_documents.DOCUMENTS.items()
    )
    assert reviewed >= 1
    assert pending == len(verify_love_dining_documents.DOCUMENTS) - reviewed
