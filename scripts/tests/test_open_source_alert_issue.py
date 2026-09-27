from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "open_source_alert_issue.sh"
# Stub gh: log each call, echo the posted body, answer list/view from env.
FAKE_GH = """#!/usr/bin/env bash
echo "CALL $1 $2" >> "$GH_LOG"
case "$1 $2" in
  "issue list") echo "$FAKE_ISSUE" ;;
  "issue view") cat "$FAKE_BODIES" ;;
  "issue create"|"issue comment") cat "${@: -1}" >> "$GH_LOG" ;;
esac
"""


def alert_body(checked_at: str, signal: str) -> str:
    return (
        "# Japan Dining source changed\n\n"
        f"- Checked at: `{checked_at}`\n"
        f"- Source cache time: `{checked_at}`\n\n"
        f"## Source Signals\n\n- {signal}\n"
    )


def run_alert(tmp_path: Path, body: str, issue: str = "", existing: str = "") -> str:
    gh = tmp_path / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (tmp_path / "body.md").write_text(body)
    (tmp_path / "existing.txt").write_text(existing)
    log = tmp_path / "gh.log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "FAKE_ISSUE": issue,
        "FAKE_BODIES": str(tmp_path / "existing.txt"),
    }
    subprocess.run(
        ["bash", str(SCRIPT), "Japan Dining source changed", str(tmp_path / "body.md"), "japan-dining"],
        check=True,
        env=env,
        capture_output=True,
    )
    return log.read_text()


def test_new_issue_carries_fingerprint_marker(tmp_path: Path) -> None:
    log = run_alert(tmp_path, alert_body("2026-09-26T00:00:00Z", "Open review"))

    assert "CALL issue create" in log
    assert "<!-- source-alert-fingerprint: " in log


def test_unchanged_signals_with_new_timestamps_do_not_comment(tmp_path: Path) -> None:
    first = run_alert(tmp_path, alert_body("2026-09-26T00:00:00Z", "Open review"))

    log = run_alert(tmp_path, alert_body("2026-09-27T00:00:00Z", "Open review"), issue="25", existing=first)

    assert "CALL issue comment" not in log


def test_changed_signals_comment_on_existing_issue(tmp_path: Path) -> None:
    first = run_alert(tmp_path, alert_body("2026-09-26T00:00:00Z", "Open review"))

    log = run_alert(tmp_path, alert_body("2026-09-27T00:00:00Z", "Record count: 1 -> 2"), issue="25", existing=first)

    assert "CALL issue comment" in log


def test_issue_without_marker_gets_one_comment(tmp_path: Path) -> None:
    log = run_alert(tmp_path, alert_body("2026-09-27T00:00:00Z", "Open review"), issue="25", existing="old body\n")

    assert "CALL issue comment" in log
