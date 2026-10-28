"""Only commit_and_push.sh merges updates.json rebase conflicts, so every ledger push goes through it."""

import re
import shlex
from pathlib import Path

import yaml

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))
LEDGER_PATHSPECS = {"data/updates.json", "data/", "data", ".", "./", "-A", "--all"}


def steps():
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                yield f"{path.name}:{job_id}:{step.get('name', step.get('uses'))}", step


def stages_ledger(script: str) -> bool:
    for line in script.splitlines():
        words = shlex.split(line, comments=True)
        if words[:2] == ["git", "add"] and LEDGER_PATHSPECS & set(words[2:]):
            return True
        if words[:2] == ["git", "commit"] and ("-a" in words or "--all" in words):
            return True
    return False


def test_no_step_pushes_the_ledger_with_raw_git() -> None:
    offenders = [
        name
        for name, step in steps()
        if re.search(r"\bgit push\b", step.get("run", "")) and stages_ledger(step["run"])
    ]

    assert offenders == []


def test_every_ledger_stage_runs_commit_and_push() -> None:
    offenders = [
        name
        for name, step in steps()
        if "data/updates.json" in str(step.get("env", {}).get("MUST_STAGE", ""))
        and "bash scripts/commit_and_push.sh" not in step.get("run", "")
    ]

    assert offenders == []


def test_ledger_rule_catches_raw_pushes() -> None:
    assert stages_ledger("git add data/\ngit push origin HEAD:main")
    assert stages_ledger("git add data/love-dining.json data/updates.json")
    assert not stages_ledger("git add data/love-dining.json  # data/updates.json")
