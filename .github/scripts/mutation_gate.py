"""Mutation-test the Python source files a pull request changed, or whose tests it changed.

Each module is mutated with mutmut and run against the tests that mention it. The job fails when the share of mutants the tests detect falls
below the threshold, so a change cannot ship with tests that pass whatever
the code does.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# (directory mutmut runs in, source package inside it, tests directory inside it)
ROOTS = (
    (REPO, "scripts", "scripts/tests"),
    (REPO / "reminders", "app", "tests"),
)


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.endswith(".py")]


def covered_modules(root: Path, package: str, test: str) -> set[str]:
    """Modules a changed test is about, so a PR that only weakens a test is still checked.

    A test counts for a module it imports when the module's name contains the first two
    words of the test's name: test_love_dining_parser.py covers scrape_love_dining.py and
    test_tft_slot_history.py covers tft_slot_history.py, but not the app/main.py it imports.
    """
    subject = "_".join(Path(test).stem.removeprefix("test_").split("_")[:2])
    text = (root / test).read_text(encoding="utf-8")
    groups = re.findall(rf"^from {package} import ([\w, ]+)", text, re.MULTILINE)
    groups += re.findall(rf"^import {package}\.(\w+)", text, re.MULTILINE)
    names = {name.split(" as ")[0].strip() for group in groups for name in group.split(",")}
    return {f"{package}/{name}.py" for name in names if subject in name and (root / package / f"{name}.py").exists()}


def sources_by_root(paths: list[str]) -> dict[Path, list[str]]:
    found: dict[Path, list[str]] = {}
    for root, package, tests in ROOTS:
        prefix = root.relative_to(REPO).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        modules: set[str] = set()
        for path in paths:
            local = path[len(prefix):]
            if not path.startswith(prefix) or not (REPO / path).exists():
                continue
            if local.startswith(tests + "/"):
                modules |= covered_modules(root, package, local)
            elif local.startswith(package + "/"):
                modules.add(local)
        if modules:
            found[root] = sorted(modules)
    return found


def tests_for(root: Path, tests: str, module: str) -> list[str]:
    stem = Path(module).stem
    return sorted(
        test.relative_to(root).as_posix()
        for test in (root / tests).glob("test_*.py")
        if stem in test.read_text(encoding="utf-8")
    )


def run_root(root: Path, package: str, tests: str, modules: list[str]) -> dict[str, int]:
    selection = sorted({test for module in modules for test in tests_for(root, tests, module)})
    print(f"mutation-gate: {root.relative_to(REPO.parent)}: mutating {', '.join(modules)}")
    if not selection:
        raise SystemExit(f"::error::mutation-gate: no test under {tests}/ mentions {', '.join(modules)}; add tests for them")
    print(f"mutation-gate: tests {', '.join(selection)}")
    config = ["[mutmut]", f"source_paths={package}", "only_mutate="]
    config += [f"    {module}" for module in modules]
    config += ["pytest_add_cli_args_test_selection="] + [f"    {test}" for test in selection]
    (root / "setup.cfg").write_text("\n".join(config) + "\n", encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=root)
    subprocess.run([sys.executable, "-m", "mutmut", "results"], cwd=root, check=False)
    subprocess.run([sys.executable, "-m", "mutmut", "export-cicd-stats"], cwd=root, check=False)
    stats_path = root / "mutants" / "mutmut-cicd-stats.json"
    if run.returncode != 0 or not stats_path.exists():
        raise SystemExit(f"mutation-gate: mutmut failed in {root} (exit {run.returncode}); see the log above")
    return json.loads(stats_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="git ref to diff against, e.g. origin/main")
    parser.add_argument("--threshold", type=float, default=80.0)
    args = parser.parse_args()

    found = sources_by_root(changed_files(args.base))
    if not found:
        print(f"mutation-gate: skipped, no Python source or test under scripts/ or reminders/ changed versus {args.base}")
        return 0

    totals = {"total": 0, "killed": 0, "timeout": 0, "skipped": 0, "survived": 0, "no_tests": 0}
    for root, package, tests in ROOTS:
        if root in found:
            stats = run_root(root, package, tests, found[root])
            for key in totals:
                totals[key] += int(stats.get(key, 0))
    tested = totals["total"] - totals["skipped"]
    score = 100.0 * (totals["killed"] + totals["timeout"]) / tested if tested else 0.0
    print(
        f"mutation-gate: score {score:.1f}% (killed {totals['killed']}, timeout {totals['timeout']}, "
        f"survived {totals['survived']}, no tests {totals['no_tests']}, of {tested}); threshold {args.threshold:.0f}%"
    )
    if totals["no_tests"]:
        print("mutation-gate: 'no tests' usually means a test loads the module by file path; import it as a package instead")
    if score < args.threshold:
        print(f"::error::Mutation score {score:.1f}% is below {args.threshold:.0f}%. Strengthen the tests for the surviving mutants listed above.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
