from __future__ import annotations

import json
import re
from pathlib import Path

import pypdf
import pytest

from scripts import build_tft_guide_catalog, official_document_reviews as reviews


ROOT = Path(__file__).resolve().parents[2]
PIN_FILE = ROOT / "requirements-pdf.txt"
HISTORICAL_EXTRACTORS = {
    f"pypdf {version} extract_text normalized-whitespace-v1"
    for version in ("6.15.0", "6.16.2", "6.19.0")
}
# Hotel terms page 2 extracts differently under 6.21.3 than under the 6.19.0 that reviewed it.
PINNED_PYPDF_PAGE_DRIFT = {
    "30a6a4fa068470f8ef80752d4cb228965b62d65541760e4103d2ab7a83b174ca",
    "5b9a7e525dae8b4f00840f1fef47bfd572636bd466e0682d13c9d633cde19d5c",
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
    blocks = (ROOT / ".github/dependabot.yml").read_text().split("- package-ecosystem: ")[1:]
    pip = {re.search(r"directory: (\S+)", block).group(1): block for block in blocks if block.startswith("pip")}
    assert set(pip) == {"/", "/reminders"}
    assert "dependency-name: pypdf" not in pip["/"]
    assert re.search(r"ignore:\s*\n\s*- dependency-name: pypdf\s*$", pip["/reminders"])


def test_retained_official_pdfs_verify_offline_with_the_pinned_pypdf():
    review_root = ROOT / "data/reviews/official-documents"
    # Refreshes retain observed PDFs before review, so only reviewed pairs are checked.
    pairs = [
        (pdf, review_root / pdf.parent.name / f"{pdf.stem}.json")
        for pdf in sorted((ROOT / "data/reviews/official-document-pdfs").glob("*/*.pdf"))
        if (review_root / pdf.parent.name / f"{pdf.stem}.json").exists()
    ]
    assert pairs
    verified, drifted = set(), set()
    for pdf, manifest_path in pairs:
        manifest = json.loads(manifest_path.read_text())
        spec = reviews.DocumentSpec(
            document_id=pdf.parent.name,
            **{field: manifest[field] for field in ("program", "program_id", "route", "kind", "title", "source_url")},
        )
        if pdf.stem in PINNED_PYPDF_PAGE_DRIFT:
            with pytest.raises(ValueError, match="does not match the PDF"):
                reviews.verify_version(spec, pdf.read_bytes(), manifest)
            drifted.add(pdf.stem)
        else:
            assert reviews.verify_version(spec, pdf.read_bytes(), manifest)["raw_sha256"] == pdf.stem
            verified.add(pdf.stem)
    assert verified
    assert drifted == PINNED_PYPDF_PAGE_DRIFT
