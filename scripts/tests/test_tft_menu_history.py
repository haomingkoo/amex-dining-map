"""Menu history keeps every published PDF version per venue and card, with dish-level changes."""

from __future__ import annotations

from pathlib import Path

from scripts import build_tft_menu_history as history


def menu(sha: str, card: str = "platinum") -> dict:
    return {"status": "published", "sha256": sha, "filename": f"{sha}.pdf", "bytes": 10,
            "url": f"https://www.americanexpress.com/{sha}.pdf", "card": card}


def payload(**menus: dict) -> dict:
    return {"venues": [{"id": "tft-vineyard", "name": "Vineyard", "menu_pdfs": menus}]}


TEXT = {
    "a" * 64: "Blue Swimmer Crab Rémoulade\nConfit Duck Pastilla\nCoffee or Tea",
    "b" * 64: "Red Prawn Tartare\nConfit  Duck Pastilla\nCOFFEE OR TEA\n3",
}


def build(steps: list[tuple[str, dict]], root: Path) -> dict:
    data = history.empty_history()
    for observed_at, source in steps:
        history.record_versions(data, source, observed_at)
    history.fill_changes(data, root, text_of=lambda path: TEXT[path.stem])
    return data


def archive(tmp_path: Path, *shas: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for sha in shas:
        (tmp_path / f"{sha}.pdf").write_bytes(b"%PDF")
    return tmp_path


A, B = "a" * 64, "b" * 64


def test_same_pdf_extends_the_version_instead_of_adding_one(tmp_path: Path) -> None:
    data = build([("2026-07-04T00:00:00Z", payload(platinum=menu(A))),
                  ("2026-07-05T00:00:00Z", payload(platinum=menu(A)))], archive(tmp_path, A))

    [version] = data["venues"]["tft-vineyard"]["platinum"]
    assert (version["first_seen"], version["last_seen"]) == ("2026-07-04T00:00:00Z", "2026-07-05T00:00:00Z")


def test_new_pdf_adds_a_version_with_dish_changes(tmp_path: Path) -> None:
    data = build([("2026-07-04T00:00:00Z", payload(platinum=menu(A))),
                  ("2026-11-03T00:00:00Z", payload(platinum=menu(B)))], archive(tmp_path, A, B))

    old, new = data["venues"]["tft-vineyard"]["platinum"]
    assert old["changes"] is None
    # Spacing, case and page numbers are not menu changes.
    assert new["changes"] == {"added": ["Red Prawn Tartare"], "removed": ["Blue Swimmer Crab Rémoulade"]}
    assert new["archive_path"] == f"menu-archive/{B}.pdf"
    assert new["source_url"] == f"https://www.americanexpress.com/{B}.pdf"


def test_cards_keep_separate_histories(tmp_path: Path) -> None:
    data = build([("2026-07-04T00:00:00Z", payload(platinum=menu(A), centurion=menu(B, "centurion")))],
                 archive(tmp_path, A, B))

    assert [v["sha256"] for v in data["venues"]["tft-vineyard"]["platinum"]] == [A]
    assert [v["sha256"] for v in data["venues"]["tft-vineyard"]["centurion"]] == [B]


def test_legacy_single_menu_counts_as_platinum(tmp_path: Path) -> None:
    legacy = {"venues": [{"id": "tft-vineyard", "menu_pdf": menu(A)}]}
    data = build([("2026-04-27T00:00:00Z", legacy)], archive(tmp_path, A))

    assert [v["sha256"] for v in data["venues"]["tft-vineyard"]["platinum"]] == [A]


def test_unpublished_menus_are_not_versions(tmp_path: Path) -> None:
    pending = {**menu(A), "status": "review_required"}
    data = build([("2026-07-04T00:00:00Z", payload(platinum=pending))], archive(tmp_path))

    assert data["venues"] == {}


def test_missing_pdf_is_listed_without_a_link_or_diff(tmp_path: Path) -> None:
    data = build([("2026-07-04T00:00:00Z", payload(platinum=menu(A))),
                  ("2026-11-03T00:00:00Z", payload(platinum=menu(B)))], archive(tmp_path, B))

    old, new = data["venues"]["tft-vineyard"]["platinum"]
    assert old["archive_path"] is None
    assert new["changes"] is None


def test_staging_copies_only_archived_versions(tmp_path: Path) -> None:
    root = archive(tmp_path / "pdfs", A, B)
    (root / ("c" * 64 + ".pdf")).write_bytes(b"%PDF")  # rejected candidate, never published
    data = build([("2026-07-04T00:00:00Z", payload(platinum=menu(A))),
                  ("2026-11-03T00:00:00Z", payload(platinum=menu(B)))], root)

    out = tmp_path / "site" / "menu-archive"
    history.stage_archive(data, root, out)

    assert sorted(p.name for p in out.iterdir()) == [f"{A}.pdf", f"{B}.pdf"]


def test_rewrapped_terms_are_not_changes() -> None:
    before = "Each diner receives one full set of the menu. Two\ncomplimentary sets will be served under Table for Two.\nTea"
    after = "Each diner receives one full set of the menu.\nTwo complimentary sets will be served under\nTable for Two.\nCoffee"

    assert history.dish_changes(before, after) == {"added": ["Coffee"], "removed": ["Tea"]}
