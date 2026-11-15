"""The mutation gate's own decisions: which modules a pull request makes it mutate, and when it fails."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

GATE_PATH = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "mutation_gate.py"
SPEC = importlib.util.spec_from_file_location("mutation_gate", GATE_PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


# ─── Import analysis ──────────────────────────────────────────────────────────

PACKAGE = {
    "pkg/alpha.py": "",
    "pkg/beta.py": "",
    "pkg/gamma.py": "",
    "pkg/delta.py": "",
    "pkg/sub/inner.py": "",
}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from pkg import alpha, beta as b\n", {"pkg/alpha.py", "pkg/beta.py"}),
        ("from pkg import (\n    alpha,\n    gamma,\n)\n", {"pkg/alpha.py", "pkg/gamma.py"}),
        ("import pkg.alpha\nimport pkg.beta as b\n", {"pkg/alpha.py", "pkg/beta.py"}),
        ("from pkg.gamma import thing, other\n", {"pkg/gamma.py"}),
        ("from pkg.sub.inner import x\nfrom pkg.sub import inner\n", {"pkg/sub/inner.py"}),
        ("def test():\n    from pkg import delta\n", {"pkg/delta.py"}),
        ("try:\n    from pkg import alpha\nexcept ImportError:\n    import alpha\n", {"pkg/alpha.py"}),
    ],
)
def test_imports_are_read_from_the_syntax_tree(tmp_path, source, expected):
    _write(tmp_path, PACKAGE)
    assert gate.imported_modules(source, tmp_path, "pkg") == expected


def test_names_that_are_not_package_modules_are_ignored(tmp_path):
    _write(tmp_path, PACKAGE)
    source = (
        "import json\n"
        "from other import alpha\n"
        "from tests.helpers import beta\n"
        "from pkg import missing_module\n"
        "from . import gamma\n"
        "import pkgextra.alpha\n"
    )
    assert gate.imported_modules(source, tmp_path, "pkg") == set()


def test_a_module_named_only_in_a_string_or_comment_is_not_an_import(tmp_path):
    # The old gate matched on text: a comment naming alpha, or the first two words of the
    # test's file name, decided coverage. Only an import statement counts now.
    _write(tmp_path, PACKAGE)
    source = '# covers pkg.alpha\nPATH = "pkg/beta.py"\nfrom pkg import gamma\n'
    assert gate.imported_modules(source, tmp_path, "pkg") == {"pkg/gamma.py"}


def test_tests_are_selected_by_what_they_import_directly_or_through_the_package(tmp_path):
    _write(tmp_path, {
        **PACKAGE,
        "pkg/beta.py": "from pkg import alpha\n",
        "pkg/gamma.py": "import pkg.beta\n",
        "pkg/tests/test_direct.py": "from pkg import alpha\n",
        "pkg/tests/test_through_two_modules.py": "from pkg import gamma\n",
        "pkg/tests/test_unrelated.py": "from pkg import delta\n",
        "pkg/tests/test_mentions_only.py": "# alpha is tested elsewhere\nNAME = 'alpha'\n",
        "pkg/tests/helper.py": "from pkg import alpha\n",
    })
    assert gate.tests_for(tmp_path, "pkg", "pkg/tests", "pkg/alpha.py") == [
        "pkg/tests/test_direct.py",
        "pkg/tests/test_through_two_modules.py",
    ]


def test_import_cycles_inside_the_package_terminate(tmp_path):
    _write(tmp_path, {
        "pkg/alpha.py": "from pkg import beta\n",
        "pkg/beta.py": "from pkg import alpha\n",
        "pkg/tests/test_cycle.py": "from pkg import alpha\n",
    })
    assert gate.tests_for(tmp_path, "pkg", "pkg/tests", "pkg/beta.py") == ["pkg/tests/test_cycle.py"]



def test_local_helpers_the_selected_tests_import_are_copied_for_mutmut(tmp_path):
    # mutmut copies only the package and the tests; reminders tests also import evals/.
    _write(tmp_path, {
        **PACKAGE,
        "evals/__init__.py": "",
        "evals/harness.py": "",
        "fixtures.py": "",
        "pkg/tests/test_a.py": "from evals import harness\nimport fixtures\nfrom pkg import alpha\nfrom pkg.tests import helper\n",
        "pkg/tests/test_b.py": "import json\nfrom evals.harness import run\n",
    })
    assert gate.local_imports(tmp_path, "pkg", "pkg/tests", ["pkg/tests/test_a.py", "pkg/tests/test_b.py"]) == ["evals", "fixtures.py"]

# ─── Which modules a diff makes the gate mutate ─────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo shaped like this one: scripts/ at the top, reminders/app with its tests beside it."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "gate@example.test")
    _git(tmp_path, "config", "user.name", "gate")
    _write(tmp_path, {
        "scripts/scrape.py": "",
        "scripts/helper.py": "",
        "scripts/tests/test_scrape.py": "from scripts import scrape\n",
        "scripts/tests/test_helper_and_scrape.py": "from scripts import helper\nfrom scripts import scrape\n",
        "reminders/app/__init__.py": "",
        "reminders/app/history.py": "",
        "reminders/app/main.py": "from app import history\n",
        "reminders/tests/test_history.py": "from app import main, history\n",
        "README.md": "",
    })
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    monkeypatch.setattr(gate, "ROOTS", (
        (tmp_path, "scripts", "scripts/tests"),
        (tmp_path / "reminders", "app", "tests"),
    ))
    return tmp_path


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_a_deleted_test_file_is_listed_as_changed(repo):
    (repo / "scripts/tests/test_scrape.py").unlink()
    _commit(repo, "drop a test")
    assert gate.changed_files("main") == ["scripts/tests/test_scrape.py"]


def test_deleting_a_test_file_mutates_the_modules_it_imported(repo):
    (repo / "scripts/tests/test_helper_and_scrape.py").unlink()
    _commit(repo, "drop a test")
    assert gate.sources_by_root(gate.changed_files("main"), "main") == {repo: ["scripts/helper.py", "scripts/scrape.py"]}


def test_a_deleted_test_is_read_as_it_was_where_the_branch_left_main(repo):
    # main moves on after the branch point; the deleted file's imports come from the merge base.
    (repo / "reminders/tests/test_history.py").unlink()
    _commit(repo, "drop a test")
    _git(repo, "checkout", "-q", "main")
    _write(repo, {"reminders/tests/test_history.py": "from app import main\n"})
    _commit(repo, "main narrows the test")
    _git(repo, "checkout", "-q", "feature")
    found = gate.sources_by_root(gate.changed_files("main"), "main")
    assert found == {repo / "reminders": ["app/history.py", "app/main.py"]}


def test_a_changed_test_mutates_every_package_module_it_imports(repo):
    _write(repo, {"reminders/tests/test_history.py": "from app import main, history\n\ndef test_x():\n    pass\n"})
    _commit(repo, "edit a test")
    assert gate.sources_by_root(gate.changed_files("main"), "main") == {repo / "reminders": ["app/history.py", "app/main.py"]}


def test_a_changed_source_is_mutated_and_a_deleted_source_is_not(repo):
    _write(repo, {"scripts/scrape.py": "X = 1\n"})
    (repo / "scripts/helper.py").unlink()
    _commit(repo, "edit and delete sources")
    assert gate.changed_files("main") == ["scripts/helper.py", "scripts/scrape.py"]
    assert gate.sources_by_root(gate.changed_files("main"), "main") == {repo: ["scripts/scrape.py"]}


def test_files_outside_the_mutated_packages_do_not_trigger_the_gate(repo):
    _write(repo, {"README.md": "changed\n", "scripts/notes.txt": "x\n", "tools/other.py": "\n"})
    _commit(repo, "unrelated")
    assert gate.sources_by_root(gate.changed_files("main"), "main") == {}


# ─── Per-module scores and the verdict ──────────────────────────────────────

KILLED, SURVIVED, NO_TESTS, SKIPPED, TIMEOUT = 1, 0, 33, 34, 36


def _meta(root: Path, module: str, codes: list[int | None]) -> None:
    path = root / "mutants" / f"{module}.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"exit_code_by_key": {f"m{n}": code for n, code in enumerate(codes)}}), encoding="utf-8")


def test_module_counts_come_from_mutmuts_own_status_names(tmp_path):
    _meta(tmp_path, "pkg/a.py", [KILLED] * 3 + [TIMEOUT] + [SURVIVED] * 2 + [NO_TESTS] + [SKIPPED] + [None])
    counts = gate.module_counts(tmp_path, "pkg/a.py")
    assert counts == {"total": 9, "killed": 3, "timeout": 1, "survived": 2, "no_tests": 1, "skipped": 1, "not_checked": 1}


def test_score_counts_timeouts_as_detected_and_leaves_skipped_mutants_out():
    counts = {"total": 9, "killed": 3, "timeout": 1, "survived": 2, "no_tests": 1, "skipped": 1, "not_checked": 1}
    assert gate.score(counts) == 50.0


def test_a_module_without_mutants_has_no_score(tmp_path):
    assert gate.module_counts(tmp_path, "pkg/constants_only.py") is None


def test_each_module_must_reach_the_threshold_on_its_own():
    # 95 of 100 and 4 of 10 average to 90% combined; the weak module still fails.
    strong = {"total": 100, "killed": 95, "timeout": 0, "survived": 5, "no_tests": 0, "skipped": 0, "not_checked": 0}
    weak = {"total": 10, "killed": 4, "timeout": 0, "survived": 6, "no_tests": 0, "skipped": 0, "not_checked": 0}
    assert gate.failing_modules({"pkg/strong.py": strong, "pkg/weak.py": weak}, 80) == ["pkg/weak.py"]


def test_a_module_exactly_at_the_threshold_passes_and_one_just_below_fails():
    at = {"total": 5, "killed": 4, "timeout": 0, "survived": 1, "no_tests": 0, "skipped": 0, "not_checked": 0}
    below = {"total": 1000, "killed": 799, "timeout": 0, "survived": 201, "no_tests": 0, "skipped": 0, "not_checked": 0}
    assert gate.failing_modules({"pkg/at.py": at, "pkg/below.py": below}, 80) == ["pkg/below.py"]


def test_modules_without_mutants_or_without_tests_are_reported_separately():
    clean = {"total": 2, "killed": 2, "timeout": 0, "survived": 0, "no_tests": 0, "skipped": 0, "not_checked": 0}
    assert gate.failing_modules({"pkg/clean.py": clean, "pkg/empty.py": None}, 80) == []
