"""Mutation-test the Python source files a pull request changed, or whose tests it changed or deleted.

Each module is mutated with mutmut and run against the tests that import it. The job fails when the share of mutants the tests detect falls
below the threshold in any one module, so a change cannot ship with tests that pass whatever
the code does.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# (directory mutmut runs in, source package inside it, tests directory inside it)
ROOTS = (
    (REPO, "scripts", "scripts/tests"),
    (REPO / "reminders", "app", "tests"),
)
COUNTED = ("killed", "timeout", "survived", "no_tests", "skipped", "not_checked")


def changed_files(base: str) -> list[str]:
    """Python files added, modified, renamed or deleted versus the merge base with base."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMRD", f"{base}...HEAD"],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.endswith(".py")]


def _source_before(base: str, path: str) -> str:
    """A deleted file as it was where the branch left base."""
    fork = subprocess.run(
        ["git", "merge-base", base, "HEAD"], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()
    return subprocess.run(
        ["git", "show", f"{fork}:{path}"], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout


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


def _read_imports(root: Path, package: str, module: str, cache: dict[str, set[str]]) -> set[str]:
    if module not in cache:
        cache[module] = imported_modules((root / module).read_text(encoding="utf-8"), root, package)
    return cache[module]


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
            pending.extend(_read_imports(root, package, current, cache))
        if module in seen:
            selected.append(test.relative_to(root).as_posix())
    return selected


def sources_by_root(paths: list[str], base: str) -> dict[Path, list[str]]:
    """Modules to mutate: changed sources that still exist, and every module a changed or deleted test imports."""
    found: dict[Path, list[str]] = {}
    for root, package, tests in ROOTS:
        prefix = root.relative_to(REPO).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        modules: set[str] = set()
        for path in paths:
            if not path.startswith(prefix):
                continue
            local = path[len(prefix):]
            exists = (REPO / path).exists()
            if local.startswith(tests + "/"):
                source = (REPO / path).read_text(encoding="utf-8") if exists else _source_before(base, path)
                modules |= imported_modules(source, root, package)
            elif local.startswith(package + "/") and exists:
                modules.add(local)
        if modules:
            found[root] = sorted(modules)
    return found


def module_counts(root: Path, module: str) -> dict[str, int] | None:
    """Mutant outcomes for one module from mutmut's results file, or None when it has no mutants."""
    from mutmut.stats import status_by_exit_code

    meta = root / "mutants" / f"{module}.meta"
    if not meta.exists():
        return None
    codes = json.loads(meta.read_text(encoding="utf-8")).get("exit_code_by_key") or {}
    if not codes:
        return None
    counts = {key: 0 for key in COUNTED}
    for code in codes.values():
        status = status_by_exit_code[code].replace(" ", "_")
        if status in counts:
            counts[status] += 1
    counts["total"] = len(codes)
    return counts


def score(counts: dict[str, int]) -> float:
    tested = counts["total"] - counts["skipped"]
    return 100.0 * (counts["killed"] + counts["timeout"]) / tested if tested else 0.0


def failing_modules(scores: dict[str, dict[str, int] | None], threshold: float) -> list[str]:
    return sorted(module for module, counts in scores.items() if counts is not None and score(counts) < threshold)


def run_root(root: Path, package: str, tests: str, modules: list[str]) -> tuple[dict[str, dict[str, int] | None], list[str]]:
    """Mutate modules under root. Returns counts per module and the modules no test imports."""
    selection_by_module = {module: tests_for(root, package, tests, module) for module in modules}
    untested = [module for module, selection in selection_by_module.items() if not selection]
    mutated = [module for module in modules if module not in untested]
    if not mutated:
        return {}, untested
    selection = sorted({test for module in mutated for test in selection_by_module[module]})
    print(f"mutation-gate: {root.relative_to(REPO.parent)}: mutating {', '.join(mutated)}")
    print(f"mutation-gate: tests {', '.join(selection)}")
    config = ["[mutmut]", f"source_paths={package}", "only_mutate="]
    config += [f"    {module}" for module in mutated]
    config += ["pytest_add_cli_args_test_selection="] + [f"    {test}" for test in selection]
    (root / "setup.cfg").write_text("\n".join(config) + "\n", encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=root)
    subprocess.run([sys.executable, "-m", "mutmut", "results"], cwd=root, check=False)
    if run.returncode != 0:
        raise SystemExit(f"mutation-gate: mutmut failed in {root} (exit {run.returncode}); see the log above")
    return {module: module_counts(root, module) for module in mutated}, untested


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="git ref to diff against, e.g. origin/main")
    parser.add_argument("--threshold", type=float, default=80.0)
    args = parser.parse_args()

    found = sources_by_root(changed_files(args.base), args.base)
    if not found:
        print(f"mutation-gate: skipped, no Python source or test under scripts/ or reminders/ changed versus {args.base}")
        return 0

    scores: dict[str, dict[str, int] | None] = {}
    untested: list[str] = []
    for root, package, tests in ROOTS:
        if root in found:
            prefix = root.relative_to(REPO).as_posix()
            prefix = "" if prefix == "." else prefix + "/"
            counts, missing = run_root(root, package, tests, found[root])
            scores |= {prefix + module: value for module, value in counts.items()}
            untested += [prefix + module for module in missing]

    for module, counts in sorted(scores.items()):
        if counts is None:
            print(f"mutation-gate: {module}: no mutants, nothing to score")
            continue
        print(
            f"mutation-gate: {module}: score {score(counts):.1f}% (killed {counts['killed']}, timeout {counts['timeout']}, "
            f"survived {counts['survived']}, no tests {counts['no_tests']}, of {counts['total'] - counts['skipped']})"
        )
        if counts["no_tests"]:
            print(f"mutation-gate: {module}: 'no tests' usually means a test loads the module by file path; import it as a package instead")
    failed = failing_modules(scores, args.threshold)
    for module in failed:
        print(f"::error::Mutation score for {module} is {score(scores[module]):.1f}%, below {args.threshold:.0f}%. Strengthen its tests for the surviving mutants listed above.")
    for module in untested:
        print(f"::error::mutation-gate: no test imports {module}; add tests that import it as a package module")
    if failed or untested:
        return 1
    print(f"mutation-gate: every module reached {args.threshold:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
