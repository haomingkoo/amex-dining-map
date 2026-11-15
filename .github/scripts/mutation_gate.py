"""Mutation-test the Python modules a pull request touches.

Two rules, chosen by why a module is in scope:

- A source module the pull request changed must reach the threshold on its own.
- A module pulled in only because a test that imports it changed or was deleted is
  scored twice, against the head tests and against the tests as they were where the
  branch left base. It fails on a lower score, or on any mutant the base tests
  detected that the head tests no longer do. So a pull request that weakens or deletes
  a test fails, without making it fix every older gap in the modules that test imports.

Each side runs as `--side head` or `--side base` (CI runs them as parallel jobs) and
writes a results file; `--compare` reads both and decides. A side that runs out of
its budget records the modules it skipped, and the comparison fails on them.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# (directory mutmut runs in, source package inside it, tests directory inside it)
ROOTS = (
    (REPO, "scripts", "scripts/tests"),
    (REPO / "reminders", "app", "tests"),
)
DETECTED = {"killed", "timeout"}


# ─── Git ──────────────────────────────────────────────────────────────────────

def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO, check=True, capture_output=True, text=True,
    ).stdout


def changed_files(base: str) -> list[str]:
    """Python files added, modified, renamed or deleted versus the merge base with base."""
    out = _git("diff", "--name-only", "--diff-filter=AMRD", f"{base}...HEAD")
    return [line for line in out.splitlines() if line.endswith(".py")]


def _fork(base: str) -> str:
    return _git("merge-base", base, "HEAD").strip()


def _source_before(base: str, path: str) -> str | None:
    """A file as it was where the branch left base, or None if it did not exist there."""
    fork = _fork(base)
    if not _git("ls-tree", "--name-only", fork, "--", path).strip():
        return None
    return _git("show", f"{fork}:{path}")


# ─── Import analysis ──────────────────────────────────────────────────────────

def _module_file(root: Path, parts: list[str]) -> str | None:
    """The longest prefix of a dotted name that is a .py file under root, as a root-relative path."""
    for end in range(len(parts), 1, -1):
        candidate = Path(*parts[:end]).with_suffix(".py")
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def imported_modules(source: str, root: Path, package: str) -> set[str]:
    """Modules of package that source imports, anywhere in the file (inside functions and try blocks too)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".") for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            prefix = node.module.split(".")
            # `from pkg.mod import name` imports pkg.mod, and pkg.mod.name too when name is a submodule.
            names = [prefix] + [prefix + [alias.name] for alias in node.names]
        else:
            continue
        for parts in names:
            if parts[0] == package and (module := _module_file(root, parts)):
                found.add(module)
    return found


def tests_for(root: Path, package: str, tests: str, module: str) -> list[str]:
    """Test files that import module, directly or through other modules of the package."""
    cache: dict[str, set[str]] = {}
    selected = []
    for test in sorted((root / tests).glob("test_*.py")):
        seen: set[str] = set()
        pending = list(imported_modules(test.read_text(encoding="utf-8"), root, package))
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if current not in cache:
                cache[current] = imported_modules((root / current).read_text(encoding="utf-8"), root, package)
            pending.extend(cache[current])
        if module in seen:
            selected.append(test.relative_to(root).as_posix())
    return selected


def local_imports(root: Path, package: str, tests: str, selection: list[str]) -> list[str]:
    """Top-level files and directories under root, besides the package and tests, that the tests import.

    mutmut copies only the package and the tests into mutants/, so these are passed as also_copy.
    """
    skip = {package, tests.split("/")[0]}
    found: set[str] = set()
    for test in selection:
        for node in ast.walk(ast.parse((root / test).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                heads = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                heads = [node.module.split(".")[0]]
            else:
                continue
            for head in heads:
                if head in skip:
                    continue
                if (root / head).is_dir():
                    found.add(head)
                elif (root / f"{head}.py").is_file():
                    found.add(f"{head}.py")
    return sorted(found)


# ─── Scope ────────────────────────────────────────────────────────────────────

def _prefix(root: Path, repo: Path) -> str:
    local = root.relative_to(repo).as_posix()
    return "" if local == "." else local + "/"


def plan(paths: list[str], base: str) -> dict[str, list[str]]:
    """Repo-relative modules to score: changed sources (strict) and modules only changed or deleted tests import (ratchet)."""
    strict: set[str] = set()
    ratchet: set[str] = set()
    for root, package, tests in ROOTS:
        prefix = _prefix(root, REPO)
        for path in paths:
            if not path.startswith(prefix):
                continue
            local = path[len(prefix):]
            if local.startswith(tests + "/"):
                # Both versions count: a test that stops importing a module still lowers its coverage.
                versions = [_source_before(base, path)]
                if (REPO / path).exists():
                    versions.append((REPO / path).read_text(encoding="utf-8"))
                for source in filter(None, versions):
                    ratchet |= {prefix + module for module in imported_modules(source, root, package)}
            elif local.startswith(package + "/") and (REPO / path).exists():
                strict.add(path)
    return {"strict": sorted(strict), "ratchet": sorted(ratchet - strict)}


# ─── Running mutmut ───────────────────────────────────────────────────────────

def statuses(root: Path, module: str) -> dict[str, str]:
    """mutmut's status for each mutant of one module, from its results file."""
    from mutmut.stats import status_by_exit_code

    meta = root / "mutants" / f"{module}.meta"
    if not meta.exists():
        return {}
    codes = json.loads(meta.read_text(encoding="utf-8")).get("exit_code_by_key") or {}
    return {name: status_by_exit_code[code] for name, code in sorted(codes.items())}


def _run_with_deadline(command: list[str], cwd: Path, env: dict[str, str], deadline: float) -> int | None:
    """Exit code, or None when the deadline passed and the process group was killed."""
    process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        return process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return None


def run_root(root: Path, package: str, tests: str, modules: list[str], repo: Path, deadline: float) -> dict[str, dict]:
    """Mutate root-relative modules under root. Returns a result per module."""
    selection_by_module = {module: tests_for(root, package, tests, module) for module in modules}
    results: dict[str, dict] = {
        module: {"state": "untested", "statuses": {}} for module, selection in selection_by_module.items() if not selection
    }
    mutated = [module for module in modules if module not in results]
    if not mutated:
        return results
    if time.monotonic() >= deadline:
        return results | {module: {"state": "skipped", "statuses": {}} for module in mutated}
    selection = sorted({test for module in mutated for test in selection_by_module[module]})
    print(f"mutation-gate: {root}: mutating {', '.join(mutated)}")
    print(f"mutation-gate: tests {', '.join(selection)}")
    config = ["[mutmut]", f"source_paths={package}", "only_mutate="]
    config += [f"    {module}" for module in mutated]
    config += ["pytest_add_cli_args_test_selection="] + [f"    {test}" for test in selection]
    if extra := local_imports(root, package, tests, selection):
        config += ["also_copy="] + [f"    {path}" for path in extra]
    setup_cfg = root / "setup.cfg"
    committed = setup_cfg.read_bytes() if setup_cfg.exists() else None
    shutil.rmtree(root / "mutants", ignore_errors=True)
    # Tests run from the repository root in CI, so scripts they load by path can import their siblings.
    env = os.environ | {"PYTHONPATH": str(repo)}
    try:
        setup_cfg.write_text("\n".join(config) + "\n", encoding="utf-8")
        code = _run_with_deadline([sys.executable, "-m", "mutmut", "run"], root, env, deadline)
    finally:
        if committed is None:
            setup_cfg.unlink(missing_ok=True)
        else:
            setup_cfg.write_bytes(committed)
    if code is None:
        print(f"::error::mutation-gate: {root}: out of budget; skipped {', '.join(mutated)}")
        return results | {module: {"state": "skipped", "statuses": {}} for module in mutated}
    if code != 0:
        print(f"::error::mutation-gate: mutmut failed in {root} (exit {code}); see the log above")
        return results | {module: {"state": "failed", "statuses": {}} for module in mutated}
    for module in mutated:
        found = statuses(root, module)
        results[module] = {"state": "scored" if found else "no_mutants", "statuses": found}
    return results


def _overlay_base_tests(worktree: Path, base: str, changed: list[str]) -> None:
    """Put every changed or deleted test-directory file back to its merge-base version."""
    fork = _fork(base)
    for _root, _package, tests in ROOTS:
        tests_dir = _prefix(_root, REPO) + tests + "/"
        for path in changed:
            if not path.startswith(tests_dir):
                continue
            if _source_before(base, path) is None:
                (worktree / path).unlink(missing_ok=True)  # added by the branch
            else:
                _git("checkout", fork, "--", path, cwd=worktree)


def score_side(side: str, base: str, budget_seconds: float) -> dict:
    """Score one side: head scores strict and ratchet modules, base scores ratchet modules on the base tests."""
    deadline = time.monotonic() + budget_seconds
    changed = changed_files(base)
    scope = plan(changed, base)
    wanted = scope["strict"] + scope["ratchet"] if side == "head" else scope["ratchet"]
    result = {"side": side, "plan": scope, "modules": {}}
    if not wanted:
        return result
    repo = REPO
    worktree = None
    if side == "base":
        worktree = Path(tempfile.mkdtemp(prefix="mutation-base-")) / "repo"
        _git("worktree", "add", "--detach", str(worktree), "HEAD")
        _overlay_base_tests(worktree, base, changed)
        repo = worktree
    try:
        for root, package, tests in ROOTS:
            prefix = _prefix(root, REPO)
            modules = [
                path[len(prefix):] for path in wanted
                if path.startswith(prefix) and path[len(prefix):].startswith(package + "/")
            ]
            if not modules:
                continue
            side_root = repo / root.relative_to(REPO)
            for module, value in run_root(side_root, package, tests, modules, repo, deadline).items():
                result["modules"][prefix + module] = value
    finally:
        if worktree is not None:
            _git("worktree", "remove", "--force", str(worktree))
            shutil.rmtree(worktree.parent, ignore_errors=True)
    return result


# ─── Verdict ──────────────────────────────────────────────────────────────────

def score(found: dict[str, str]) -> float:
    tested = [status for status in found.values() if status != "skipped"]
    return 100.0 * sum(status in DETECTED for status in tested) / len(tested) if tested else 0.0


def _summary(found: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for status in found.values():
        counts[status] = counts.get(status, 0) + 1
    parts = ", ".join(f"{status} {count}" for status, count in sorted(counts.items()))
    return f"{score(found):.1f}% ({parts}; {len(found)} mutants)"


def compare(head: dict | None, base: dict | None, threshold: float) -> tuple[bool, list[str]]:
    """The verdict and the lines that explain it."""
    if head is None:
        return False, ["::error::mutation-gate: head results are missing; the head job failed or timed out"]
    scope = head["plan"]
    if not scope["strict"] and not scope["ratchet"]:
        return True, ["mutation-gate: skipped, no Python source or test under scripts/ or reminders/ changed"]
    if scope["ratchet"] and base is None:
        return False, ["::error::mutation-gate: base results are missing; the base job failed or timed out"]
    ok = True
    lines: list[str] = []

    def fail(message: str) -> None:
        nonlocal ok
        ok = False
        lines.append(f"::error::mutation-gate: {message}")

    def usable(module: str, entry: dict | None, side: str) -> bool:
        state = (entry or {}).get("state")
        if state == "skipped":
            fail(f"{module}: {side} run skipped, out of budget")
        elif state == "failed":
            fail(f"{module}: {side} run failed (mutmut could not run the {side} tests); see that job's log")
        elif entry is None:
            fail(f"{module}: no {side} result")
        return state in {"scored", "no_mutants", "untested"}

    def absolute(module: str, entry: dict | None, why: str) -> None:
        if not usable(module, entry, "head"):
            return
        if entry["state"] == "untested":
            fail(f"{module}: no test imports it; add tests that import it as a package module")
        elif entry["state"] == "no_mutants":
            lines.append(f"mutation-gate: {module}: no mutants, nothing to score")
        else:
            lines.append(f"mutation-gate: {module} ({why}): head {_summary(entry['statuses'])}; threshold {threshold:.0f}%")
            if score(entry["statuses"]) < threshold:
                fail(f"{module} scores {score(entry['statuses']):.1f}%, below {threshold:.0f}%")

    for module in scope["strict"]:
        absolute(module, head["modules"].get(module), "changed source")

    for module in scope["ratchet"]:
        now, before = head["modules"].get(module), base["modules"].get(module)
        if (before or {}).get("state") == "failed":
            # Nothing to compare against, so the module has to clear the bar on its own.
            lines.append(f"::warning::base unmeasurable (mutmut could not run the base tests), requiring head >= {threshold:.0f}%")
            absolute(module, now, "tests changed, no baseline")
            continue
        if not (usable(module, now, "head") & usable(module, before, "base")):
            continue
        head_found, base_found = now["statuses"], before["statuses"]
        names = set(head_found) | set(base_found)
        if head_found and base_found and set(head_found) != set(base_found):
            fail(f"{module}: head and base mutated different code; its source must not differ between the two runs")
            continue
        # A side with no tests importing the module detected nothing.
        head_found = head_found or {name: "no tests" for name in names}
        base_found = base_found or {name: "no tests" for name in names}
        lines.append(f"mutation-gate: {module} (tests changed): head {_summary(head_found)}; base {_summary(base_found)}")
        lost = sorted(name for name in names if base_found[name] in DETECTED and head_found[name] not in DETECTED)
        if lost:
            fail(f"{module}: {len(lost)} mutants the base tests detected now survive: {', '.join(lost)}")
        if score(head_found) < score(base_found):
            fail(f"{module}: score fell from {score(base_found):.1f}% to {score(head_found):.1f}%")
    if ok:
        lines.append("mutation-gate: passed")
    return ok, lines


def _load(path: str) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="git ref to diff against, e.g. origin/main")
    parser.add_argument("--side", choices=("head", "base"), help="score one side and write --out")
    parser.add_argument("--out", help="results file for --side")
    parser.add_argument("--budget-minutes", type=float, default=25.0)
    parser.add_argument("--compare", nargs=2, metavar=("HEAD_JSON", "BASE_JSON"), help="decide from two results files")
    parser.add_argument("--threshold", type=float, default=80.0)
    args = parser.parse_args()

    if args.compare:
        ok, lines = compare(_load(args.compare[0]), _load(args.compare[1]), args.threshold)
        print("\n".join(lines))
        return 0 if ok else 1
    if not args.base:
        parser.error("--base is required unless --compare is given")
    budget = args.budget_minutes * 60
    if args.side:
        if not args.out:
            parser.error("--side needs --out")
        result = score_side(args.side, args.base, budget)
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(f"mutation-gate: {args.side} results written to {args.out}")
        return 0
    head = score_side("head", args.base, budget)
    base = score_side("base", args.base, budget)
    ok, lines = compare(head, base, args.threshold)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
