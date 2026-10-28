import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import monitor_due


NOW = datetime.now(timezone.utc).replace(microsecond=0)
WORKFLOW = Path(".github/workflows/monitor-source-health.yml")


def stamp(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def job(conclusion: str, minutes_ago: int | None = None, status: str = "completed") -> list[dict]:
    started = stamp(minutes_ago) if minutes_ago is not None else None
    return [
        {"name": "gate", "status": "completed", "conclusion": "success"},
        {"name": "monitor", "status": status, "conclusion": conclusion, "startedAt": started},
    ]


def decide(jobs_by_run: dict[int, list[dict]]):
    return monitor_due.decide(list(jobs_by_run), jobs_by_run.__getitem__, NOW)


def test_recent_monitor_run_is_not_repeated() -> None:
    due, _ = decide({3: job("skipped"), 2: job("success", 10), 1: job("success", 40)})
    assert due is False


def test_gate_only_runs_do_not_reset_the_clock() -> None:
    due, reason = decide({3: job("skipped"), 2: job("skipped"), 1: job("failure", 31)})
    assert due is True
    assert "31" in reason


def test_cancelled_monitor_does_not_hold_the_clock() -> None:
    due, reason = decide({3: job("cancelled"), 2: job("cancelled", 2), 1: job("success", 40)})
    assert due is True
    assert "40" in reason


def test_queued_or_running_monitor_blocks_another() -> None:
    due, _ = decide({2: job("", status="queued"), 1: job("success", 90)})
    assert due is False


def test_no_monitor_in_recent_history_is_due() -> None:
    due, _ = decide({2: job("skipped"), 1: []})
    assert due is True


def test_gh_failure_skips_and_warns(monkeypatch, tmp_path, capsys) -> None:
    def broken(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="rate limited")

    output = tmp_path / "out"
    monkeypatch.setattr(monitor_due.subprocess, "run", broken)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_RUN_ID", "9")

    assert monitor_due.main() == 0
    assert output.read_text() == "due=false\n"
    assert "::warning" in capsys.readouterr().out


def test_current_run_is_excluded(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["gh", "run", "list"]:
            stdout = '[{"databaseId": 9}, {"databaseId": 8}]'
        else:
            stdout = '{"jobs": [{"name": "monitor", "status": "completed", "conclusion": "success", "startedAt": "%s"}]}' % stamp(5)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    output = tmp_path / "out"
    monkeypatch.setattr(monitor_due.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_RUN_ID", "9")

    assert monitor_due.main() == 0
    assert output.read_text() == "due=false\n"
    assert not any("9" in command for command in calls[1:])


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_monitor_follows_table_for_two_alerts_on_main_and_keeps_cron() -> None:
    text = workflow_text()
    assert "workflow_run:" in text
    assert "- Table for Two Alerts" in text
    assert "- main" in text
    assert 'cron: "22,52 * * * *"' in text


def test_gate_runs_outside_the_shared_refresh_queue() -> None:
    text = workflow_text()
    header, jobs = text.split("\njobs:\n", 1)
    # A workflow-level group would let gate-only runs cancel pending refresh runs.
    assert "concurrency" not in header
    gate, monitor = jobs.split("\n  monitor:\n", 1)
    assert "source-ledger-refresh" not in gate
    assert "scripts/monitor_due.py" in gate
    assert "group: source-ledger-refresh" in monitor
    assert "cancel-in-progress: false" in monitor
    assert "needs.gate.outputs.due == 'true'" in monitor
