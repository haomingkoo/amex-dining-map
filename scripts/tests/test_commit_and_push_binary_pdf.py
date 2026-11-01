"""Menu PDFs with no NUL bytes must not trip the staged whitespace check."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PDF = "data/reviews/tft-menu-pdfs/menu.pdf"
JSON = "data/table-for-two.json"

pytestmark = pytest.mark.skipif(
    subprocess.run(["bash", "-c", "type mapfile"], capture_output=True).returncode != 0,
    reason="commit_and_push.sh needs bash 4+ (CI runs ubuntu)",
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    shutil.copytree(ROOT / "scripts", work / "scripts", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copy(ROOT / ".gitattributes", work / ".gitattributes")
    git(work, "config", "user.name", "t")
    git(work, "config", "user.email", "t@example.com")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "seed")
    git(work, "remote", "add", "origin", str(bare))
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def commit_and_push(repo: Path, must_stage: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
        "COMMIT_MESSAGE": "chore: refresh table for two data",
        "MUST_STAGE": must_stage,
        "MAX_ATTEMPTS": "1",
    }
    return subprocess.run(
        ["bash", "scripts/commit_and_push.sh"], cwd=repo, env=env, capture_output=True, text=True
    )


def test_text_like_pdf_with_trailing_whitespace_commits(repo: Path) -> None:
    pdf = repo / PDF
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3 \n1 0 obj\n<</Type/Catalog>>   \nendobj\n%%EOF\n")

    pushed = commit_and_push(repo, f"{PDF}\n")

    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    assert PDF in git(repo, "ls-tree", "-r", "--name-only", "origin/main")


def test_text_file_with_trailing_whitespace_still_rejected(repo: Path) -> None:
    data = repo / JSON
    data.parent.mkdir(parents=True)
    data.write_text('{"venues": []}   \n', encoding="utf-8")

    pushed = commit_and_push(repo, f"{JSON}\n")

    assert pushed.returncode != 0
    assert "failed conflict-marker/whitespace checks" in pushed.stderr
