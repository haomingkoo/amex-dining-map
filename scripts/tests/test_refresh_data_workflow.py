import re
import subprocess
from pathlib import Path

import pytest


WORKFLOW = Path(".github/workflows/refresh-data.yml")


def step_block(name: str, next_name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"      - name: {name}")
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def finalize(outcomes: dict[str, str]) -> list[str]:
    block = step_block("Finalize source health", "Commit refreshed data")
    script = block.split("run: |\n", 1)[1]
    script = re.sub(
        r"\$\{\{ steps\.(\w+)\.outcome \}\}",
        lambda match: outcomes[match.group(1)],
        script,
    )
    script = script.replace("python3 scripts/build_source_health.py", "echo")
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line.startswith("--source")]


def test_finalize_does_not_use_the_shared_job_status() -> None:
    assert "job.status" not in step_block("Finalize source health", "Commit refreshed data")


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (
            {"japan_refresh": "success", "pocket_refresh": "success", "japan_alert": "success",
             "plat_stay_refresh": "failure", "plat_stay_alert": "skipped"},
            ["--source japan-dining --attempt-outcome success",
             "--source plat-stay --attempt-outcome failure"],
        ),
        (
            {"japan_refresh": "failure", "pocket_refresh": "skipped", "japan_alert": "skipped",
             "plat_stay_refresh": "skipped", "plat_stay_alert": "skipped"},
            ["--source japan-dining --attempt-outcome failure"],
        ),
        (
            {"japan_refresh": "success", "pocket_refresh": "failure", "japan_alert": "skipped",
             "plat_stay_refresh": "skipped", "plat_stay_alert": "skipped"},
            ["--source japan-dining --attempt-outcome failure"],
        ),
        (
            {"japan_refresh": "success", "pocket_refresh": "success", "japan_alert": "success",
             "plat_stay_refresh": "success", "plat_stay_alert": "success"},
            ["--source japan-dining --attempt-outcome success",
             "--source plat-stay --attempt-outcome success"],
        ),
    ],
)
def test_each_source_records_only_its_own_steps(outcomes, expected) -> None:
    assert finalize(outcomes) == expected
