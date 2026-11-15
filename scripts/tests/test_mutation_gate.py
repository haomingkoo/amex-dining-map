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


def test_deleting_a_test_file_ratchets_the_modules_it_imported(repo):
    (repo / "scripts/tests/test_helper_and_scrape.py").unlink()
    _commit(repo, "drop a test")
    assert gate.plan(gate.changed_files("main"), "main") == {"strict": [], "ratchet": ["scripts/helper.py", "scripts/scrape.py"]}


def test_a_deleted_test_is_read_as_it_was_where_the_branch_left_main(repo):
    # main moves on after the branch point; the deleted file's imports come from the merge base.
    (repo / "reminders/tests/test_history.py").unlink()
    _commit(repo, "drop a test")
    _git(repo, "checkout", "-q", "main")
    _write(repo, {"reminders/tests/test_history.py": "from app import main\n"})
    _commit(repo, "main narrows the test")
    _git(repo, "checkout", "-q", "feature")
    assert gate.plan(gate.changed_files("main"), "main")["ratchet"] == ["reminders/app/history.py", "reminders/app/main.py"]


def test_a_changed_test_ratchets_what_it_imports_now_and_what_it_imported_before(repo):
    # Dropping the history import must not take history out of scope.
    _write(repo, {"reminders/tests/test_history.py": "from app import main\n"})
    _commit(repo, "narrow a test")
    assert gate.plan(gate.changed_files("main"), "main")["ratchet"] == ["reminders/app/history.py", "reminders/app/main.py"]


def test_a_changed_source_is_strict_and_leaves_the_ratchet(repo):
    _write(repo, {"scripts/scrape.py": "X = 1\n", "scripts/tests/test_scrape.py": "from scripts import scrape\n# edited\n"})
    (repo / "scripts/helper.py").unlink()
    _commit(repo, "edit and delete sources")
    assert gate.changed_files("main") == ["scripts/helper.py", "scripts/scrape.py", "scripts/tests/test_scrape.py"]
    assert gate.plan(gate.changed_files("main"), "main") == {"strict": ["scripts/scrape.py"], "ratchet": []}


def test_files_outside_the_mutated_packages_do_not_trigger_the_gate(repo):
    _write(repo, {"README.md": "changed\n", "scripts/notes.txt": "x\n", "tools/other.py": "\n"})
    _commit(repo, "unrelated")
    assert gate.plan(gate.changed_files("main"), "main") == {"strict": [], "ratchet": []}


# ─── Scores ──────────────────────────────────────────────────────────────────

KILLED, SURVIVED, NO_TESTS, SKIPPED, TIMEOUT = 1, 0, 33, 34, 36


def test_statuses_come_from_mutmuts_results_file(tmp_path):
    path = tmp_path / "mutants" / "pkg" / "a.py.meta"
    path.parent.mkdir(parents=True)
    codes = {"m1": KILLED, "m2": TIMEOUT, "m3": SURVIVED, "m4": NO_TESTS, "m5": SKIPPED, "m6": None}
    path.write_text(json.dumps({"exit_code_by_key": codes}), encoding="utf-8")
    assert gate.statuses(tmp_path, "pkg/a.py") == {
        "m1": "killed", "m2": "timeout", "m3": "survived", "m4": "no tests", "m5": "skipped", "m6": "not checked",
    }
    assert gate.statuses(tmp_path, "pkg/absent.py") == {}


def test_score_counts_timeouts_as_detected_and_leaves_skipped_mutants_out():
    found = {"a": "killed", "b": "timeout", "c": "survived", "d": "no tests", "e": "skipped"}
    assert gate.score(found) == 50.0


# ─── The verdict ─────────────────────────────────────────────────────────────

def _side(side, strict=(), ratchet=(), **modules):
    """Results for one side; each keyword is a module name (dots for slashes) mapped to statuses or a state."""
    entries = {}
    for name, value in modules.items():
        module = name.replace("__", "/") + ".py"
        entries[module] = {"state": value, "statuses": {}} if isinstance(value, str) else {"state": "scored", "statuses": value}
    return {"side": side, "plan": {"strict": list(strict), "ratchet": list(ratchet)}, "modules": entries}


def _mutants(detected: int, survived: int) -> dict[str, str]:
    return {f"m{n}": "killed" if n < detected else "survived" for n in range(detected + survived)}


def test_each_changed_source_must_reach_the_threshold_on_its_own():
    # 95 of 100 and 4 of 10 average to 90% combined; the weak module still fails.
    head = _side("head", strict=["pkg/strong.py", "pkg/weak.py"], pkg__strong=_mutants(95, 5), pkg__weak=_mutants(4, 6))
    ok, lines = gate.compare(head, None, 80)
    assert not ok
    assert "::error::mutation-gate: pkg/weak.py scores 40.0%, below 80%" in lines
    assert not any("pkg/strong.py scores" in line for line in lines)


def test_a_source_exactly_at_the_threshold_passes_and_one_just_below_fails():
    head = _side("head", strict=["pkg/at.py"], pkg__at=_mutants(4, 1))
    assert gate.compare(head, None, 80)[0]
    head = _side("head", strict=["pkg/below.py"], pkg__below=_mutants(799, 201))
    assert not gate.compare(head, None, 80)[0]


def test_a_changed_source_no_test_imports_fails():
    ok, lines = gate.compare(_side("head", strict=["pkg/a.py"], pkg__a="untested"), None, 80)
    assert not ok and lines == ["::error::mutation-gate: pkg/a.py: no test imports it; add tests that import it as a package module"]


def test_a_ratchet_module_passes_below_the_threshold_when_nothing_was_lost():
    # An old gap is not this pull request's to fix.
    head = _side("head", ratchet=["pkg/old.py"], pkg__old=_mutants(3, 7))
    base = _side("base", ratchet=["pkg/old.py"], pkg__old=_mutants(3, 7))
    ok, lines = gate.compare(head, base, 80)
    assert ok
    assert lines[0] == (
        "mutation-gate: pkg/old.py (tests changed): head 30.0% (killed 3, survived 7; 10 mutants); "
        "base 30.0% (killed 3, survived 7; 10 mutants)"
    )


def test_a_mutant_the_base_tests_killed_that_now_survives_fails_even_if_the_score_holds():
    base = {"m0": "killed", "m1": "survived", "m2": "killed"}
    head = {"m0": "survived", "m1": "killed", "m2": "timeout"}
    ok, lines = gate.compare(_side("head", ratchet=["pkg/a.py"], pkg__a=head), _side("base", ratchet=["pkg/a.py"], pkg__a=base), 80)
    assert not ok
    assert "::error::mutation-gate: pkg/a.py: 1 mutants the base tests detected now survive: m0" in lines
    assert not any("score fell" in line for line in lines)


def test_a_lower_ratchet_score_fails():
    base = {"m0": "killed", "m1": "killed", "m2": "survived"}
    head = {"m0": "killed", "m1": "no tests", "m2": "survived"}
    ok, lines = gate.compare(_side("head", ratchet=["pkg/a.py"], pkg__a=head), _side("base", ratchet=["pkg/a.py"], pkg__a=base), 80)
    assert not ok
    assert "::error::mutation-gate: pkg/a.py: score fell from 66.7% to 33.3%" in lines


def test_deleting_the_only_test_of_a_module_fails_the_ratchet():
    base = _side("base", ratchet=["pkg/a.py"], pkg__a=_mutants(2, 0))
    ok, lines = gate.compare(_side("head", ratchet=["pkg/a.py"], pkg__a="untested"), base, 80)
    assert not ok
    assert "::error::mutation-gate: pkg/a.py: score fell from 100.0% to 0.0%" in lines


def test_a_module_the_base_tests_never_imported_cannot_regress():
    head = _side("head", ratchet=["pkg/new.py"], pkg__new=_mutants(1, 1))
    assert gate.compare(head, _side("base", ratchet=["pkg/new.py"], pkg__new="untested"), 80)[0]


@pytest.mark.parametrize(
    ("head_state", "base_state", "message"),
    [
        ("skipped", None, "pkg/a.py: head run skipped, out of budget"),
        (None, "skipped", "pkg/a.py: base run skipped, out of budget"),
        (None, "failed", "pkg/a.py: base run failed (mutmut could not run the base tests); see that job's log"),
    ],
)
def test_a_side_that_did_not_finish_fails_loudly(head_state, base_state, message):
    head = _side("head", ratchet=["pkg/a.py"], pkg__a=head_state or _mutants(1, 0))
    base = _side("base", ratchet=["pkg/a.py"], pkg__a=base_state or _mutants(1, 0))
    ok, lines = gate.compare(head, base, 80)
    assert not ok and f"::error::mutation-gate: {message}" in lines


def test_missing_results_fail_rather_than_pass():
    assert gate.compare(None, None, 80) == (False, ["::error::mutation-gate: head results are missing; the head job failed or timed out"])
    ok, lines = gate.compare(_side("head", ratchet=["pkg/a.py"], pkg__a=_mutants(1, 0)), None, 80)
    assert not ok and lines == ["::error::mutation-gate: base results are missing; the base job failed or timed out"]


def test_nothing_in_scope_skips():
    assert gate.compare(_side("head"), None, 80) == (
        True, ["mutation-gate: skipped, no Python source or test under scripts/ or reminders/ changed"],
    )


def test_mutating_different_code_on_each_side_is_an_error():
    head = _side("head", ratchet=["pkg/a.py"], pkg__a={"m0": "killed"})
    base = _side("base", ratchet=["pkg/a.py"], pkg__a={"m1": "killed"})
    ok, lines = gate.compare(head, base, 80)
    assert not ok and any("mutated different code" in line for line in lines)


# ─── End to end with real mutmut: a weakened test fails, its revert passes ──

CALC = "def is_adult(age):\n    return age >= 18\n\n\ndef double(x):\n    return x * 2\n"
STRONG = (
    "from scripts import calc\n\n\n"
    "def test_double():\n    assert calc.double(3) == 6\n\n\n"
    "def test_adult_boundary():\n    assert calc.is_adult(18)\n    assert not calc.is_adult(17)\n"
)
WEAK = STRONG.replace("    assert calc.is_adult(18)\n", "")


def _verdict(repo_path: Path) -> tuple[bool, list[str]]:
    head = gate.score_side("head", "main", 300)
    base = gate.score_side("base", "main", 300)
    assert (repo_path / "setup.cfg").read_text() == "[committed]\n", "the gate must restore the committed setup.cfg"
    return gate.compare(head, base, 80)


def test_weakening_a_test_fails_the_gate_and_reverting_it_passes(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "gate@example.test")
    _git(tmp_path, "config", "user.name", "gate")
    _write(tmp_path, {"scripts/calc.py": CALC, "scripts/tests/test_calc.py": STRONG, "setup.cfg": "[committed]\n"})
    _commit(tmp_path, "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    monkeypatch.setattr(gate, "ROOTS", ((tmp_path, "scripts", "scripts/tests"),))

    _write(tmp_path, {"scripts/tests/test_calc.py": WEAK})
    _commit(tmp_path, "weaken the boundary test")
    ok, lines = _verdict(tmp_path)
    assert not ok, lines
    lost = [line for line in lines if "the base tests detected now survive" in line]
    assert len(lost) == 1 and "x_is_adult__mutmut_" in lost[0]

    _git(tmp_path, "revert", "--no-edit", "HEAD")
    ok, lines = _verdict(tmp_path)
    # The revert leaves no test change versus main, so nothing is in scope.
    assert ok and lines == ["mutation-gate: skipped, no Python source or test under scripts/ or reminders/ changed"]

    _write(tmp_path, {"scripts/tests/test_calc.py": STRONG + "\n\ndef test_double_zero():\n    assert calc.double(0) == 0\n"})
    _commit(tmp_path, "add a test")
    ok, lines = _verdict(tmp_path)
    assert ok, lines
    assert lines[0].startswith("mutation-gate: scripts/calc.py (tests changed): head ") and lines[-1] == "mutation-gate: passed"
