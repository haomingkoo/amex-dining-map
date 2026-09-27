from pathlib import Path

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))


def test_every_commit_of_source_health_also_commits_the_update_ledger():
    # build_source_health.py writes both files; leaving one unstaged blocks the rebase before push.
    missing = []
    for path in WORKFLOWS:
        for step in path.read_text(encoding="utf-8").split("      - name: ")[1:]:
            stages_health = "data/source-health.json" in step or "git add data/" in step
            if stages_health and "data/updates.json" not in step and "git add data/" not in step:
                missing.append(f"{path.name}: {step.splitlines()[0]}")

    assert missing == []
